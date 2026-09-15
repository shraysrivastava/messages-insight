/* Shared helpers for both screens.

   The socket half of this file does three jobs beyond "stay connected":
   it keeps a running estimate of the server's clock, it answers heartbeats,
   and it carries the join code. See app/main.py for the protocol. */

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
                "Jul","Aug","Sep","Oct","Nov","Dec"];

function h(tag, cls, txt) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt !== undefined) n.textContent = txt;
  return n;
}

function textNode(txt, color, cls) {
  const n = h("div", cls, txt);
  if (color) n.style.color = color;
  return n;
}

function monthLabel(key) {
  if (!key) return "—";
  const [y, m] = key.split("-");
  return `${MONTHS[parseInt(m, 10) - 1]} ${y}`;
}

function shownGuess(q, guess, S) {
  if (guess === null || guess === undefined) return "no answer";
  if (q.type === "binary" || q.type === "choice") return q.options[guess];
  if (q.type === "number") return Number(guess).toLocaleString();
  if (q.type === "month") return monthLabel(S.meta.months[guess]);
  return String(guess);
}

/* ---------------------------------------------------------------- clock -- */

/* You are in different states, on different networks, and the scoring model
   pays 2x for speed. Timing an answer by when it *reaches* the server would
   quietly charge the slower connection for its latency, every round, all
   night. So: measure the offset between this device's clock and the server's,
   and stamp answers with our own corrected time. The server clamps whatever we
   send into the question window, so the worst a lying client can claim is
   "the instant the question appeared".

   Offset estimation is the plain NTP trick — assume the round trip is
   symmetric, put the server's timestamp in the middle of it. Keep the sample
   from the *fastest* round trip seen, because that's the one with the least
   queueing in it, and a fast sample is a more honest sample. */

let clockOffset = 0;      // add to Date.now()/1000 to get server time
let bestRtt = Infinity;
let synced = false;

function serverNow() {
  return Date.now() / 1000 + clockOffset;
}

function noteSample(c0, s, c1) {
  const rtt = c1 - c0;
  if (rtt < 0 || rtt > 5) return;
  if (rtt <= bestRtt) {
    bestRtt = rtt;
    clockOffset = s + rtt / 2 - c1;
    synced = true;
  }
}

function syncClock() {
  send({ t: "ping", c0: Date.now() / 1000 });
}

/* --------------------------------------------------------------- socket -- */

let sock = null, onState = null, myRole = "player", backoff = 500;
let joinCode = "";
let hostToken = localStorage.getItem("rr_host") || "";
let syncTimer = null;

function send(msg) {
  if (sock && sock.readyState === 1) sock.send(JSON.stringify(msg));
}

function setCode(code) {
  joinCode = (code || "").trim().toUpperCase();
}

function connect(role, handler) {
  myRole = role;
  onState = handler;
  open();
}

function open() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  sock = new WebSocket(`${proto}://${location.host}/ws`);

  sock.onopen = () => {
    backoff = 500;
    send({ t: "hello", role: myRole, token: hostToken, code: joinCode });

    /* Three quick samples to pin the offset down, then one every 20s. That
       doubles as our half of the keepalive — Fly's proxy drops an idle socket
       at about 60 seconds, and a lobby is idle for exactly as long as it takes
       two people to sit down. */
    bestRtt = Infinity;
    syncClock();
    setTimeout(syncClock, 300);
    setTimeout(syncClock, 900);
    clearInterval(syncTimer);
    syncTimer = setInterval(syncClock, 20000);

    if (typeof onOpenExtra === "function") onOpenExtra();
    setStatus(true);
  };

  sock.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.t === "pong") {
      noteSample(msg.c0, msg.s, Date.now() / 1000);
    } else if (msg.t === "ping") {
      send({ t: "pong" });                       // server heartbeat
    } else if (msg.t === "welcome") {
      if (msg.token) {
        hostToken = msg.token;
        localStorage.setItem("rr_host", msg.token);
      }
      if (msg.code) setCode(msg.code);
      if (typeof onWelcome === "function") onWelcome(msg);
    } else if (msg.t === "denied") {
      if (typeof onDenied === "function") onDenied(msg.why);
    } else if (msg.t === "reel") {
      if (typeof onReel === "function") onReel(msg.game);
    } else if (msg.t === "state" && onState) {
      onState(msg);
    }
  };

  sock.onclose = () => {
    clearInterval(syncTimer);
    setStatus(false);
    setTimeout(open, backoff);
    backoff = Math.min(backoff * 1.6, 5000);
  };
  sock.onerror = () => sock.close();
}

function setStatus(up) {
  let el = document.getElementById("netstatus");
  if (!up && !el) {
    el = h("div", null, "Reconnecting…");
    el.id = "netstatus";
    el.style.cssText =
      "position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:99;" +
      "background:#E05C6E;color:#191325;font-family:var(--mono);font-size:12px;" +
      "font-weight:700;padding:8px 16px;border-radius:99px;letter-spacing:.06em";
    document.body.append(el);
  } else if (up && el) {
    el.remove();
  }
}

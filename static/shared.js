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
  /* Options first, by shape rather than by type name: binary, choice, mutual
     and wager all answer with an index, and only this one branch has to know
     that. */
  if (q.options && q.options[guess] !== undefined) return q.options[guess];
  if (q.type === "number") return Number(guess).toLocaleString();
  if (q.type === "percent") return guess + "%";
  if (q.type === "month") return monthLabel(S.meta.months[guess]);
  return String(guess);
}

/* ------------------------------------------------------- the presentation */

/* `format` is a rendering hint on every question, and for a long time nothing
   read it — `redacted`, `compare` and `thread` all came out as one plain
   bubble, which for the multi-message ones meant three messages run together
   into a single sentence. This is the one place that reads it. Unknown values
   fall back to a bubble, so a format the client has never heard of can never
   break a game (schema.QFormat says the same thing from the other side).

   `cls` is the page's own bubble class — the two screens size them very
   differently — and everything else is shape, not size. */

/* Every value schema.QFormat allows, so a seventh one added there and not
   here fails a test rather than silently rendering as a bubble on game night.
   `bubble` is the fallback and has no branch. `blank` and `redacted` have no
   branch either, on purpose: the marker is in the text and `inked()` runs on
   every format, so they are a bubble that happens to contain slots. */
const FORMATS = ["bubble", "blank", "redacted", "compare", "thread",
                 "timestamp", "photo"];

const INK = "\u2581";                 // curate.py's blank marker, BLANK

function inked(text, el) {
  /* Split on runs of the blank marker so they can be drawn as slots rather
     than as a row of low underscores nobody can see across a room. */
  for (const part of text.split(new RegExp("(" + INK + "+)"))) {
    if (!part) continue;
    if (part[0] === INK) el.append(h("i", "ink", part));
    else el.append(document.createTextNode(part));
  }
  return el;
}

/* "A: “three words”" -> {tag: "A", body: "three words"}. curate.py writes the
   labels into the text for `compare`; parsing them back out is what lets the
   two halves sit side by side with the label above each. */
const SIDE_RE = /^([A-Z])\s*:\s*(.*)$/;

function messageBlock(q, cls) {
  const text = q.text || "";
  const fmt = q.format || "bubble";
  if (fmt === "photo" && q.photo) return photoBlock(q, cls);
  if (!text) return null;
  const lines = text.split("\n").map(s => s.trim()).filter(Boolean);

  if (fmt === "compare" && lines.length > 1) {
    const box = h("div", "compare");
    lines.forEach((line, i) => {
      const m = SIDE_RE.exec(line);
      const side = h("div", "side");
      side.append(h("div", "tag", m ? m[1] : String.fromCharCode(65 + i)));
      const body = (m ? m[2] : line).replace(/^[“"']|[”"']$/g, "");
      side.append(inked(body, h("div", cls)));
      box.append(side);
    });
    return box;
  }

  if (fmt === "thread" && lines.length > 1) {
    /* One column, not two. The exchanges in this format are a mix — some are
       two people taking turns, some are one person sending three in a row —
       and `format` alone does not say which. Putting them on alternating
       sides would be a guess, and on the ones it got wrong it would give away
       or destroy the answer. So: a conversation, in order, unattributed. */
    const box = h("div", "convo");
    lines.forEach((line, i) => {
      const b = inked(line, h("div", cls + " cm"));
      b.style.animationDelay = (i * 0.12) + "s";
      box.append(b);
    });
    return box;
  }

  const one = inked(lines.join(" "), h("div", cls));
  if (fmt === "timestamp") {
    /* Left Hanging. The message is not the joke — the silence after it is, so
       the bubble gets a receipt and a clock that visibly runs on. It counts
       this round's own seconds, starting at zero when the question lands, so
       it can't be mistaken for the answer to "how long did it sit". */
    const box = h("div", "hanging");
    box.append(one);
    const foot = h("div", "receipt");
    foot.append(h("span", null, "Delivered"));
    const clock = h("span", "clock", "0:00");
    clock.dataset.clock = "1";
    foot.append(clock);
    box.append(foot);
    return box;
  }
  return one;
}

/* A photograph, and its caption if it had one.

   The bytes are not in the state snapshot — `q.photo` is a flag and the image
   comes from /photo/current, once, cached by the browser for the round. The
   `r=` is the round number: the next round's picture lives at the same URL,
   so without it the browser would helpfully show the last one. */
function photoBlock(q, cls) {
  const box = h("div", "photo");
  const img = document.createElement("img");
  img.src = "/photo/current?r=" + (typeof S !== "undefined" && S ? S.round : 0);
  img.alt = "A photo from the thread";
  img.decoding = "async";
  /* A picture that fails to load must not leave a round with nothing on the
     screen — the prompt and the options still work without it. */
  img.onerror = () => box.classList.add("gone");
  box.append(img);
  if (q.text) box.append(inked(q.text, h("div", cls + " cap")));
  return box;
}

/* One interval for every clock on the page. Per-element timers would leak on
   every re-render, and both screens re-render on every state message. */
setInterval(() => {
  const els = document.querySelectorAll("[data-clock]");
  /* `S` is a top-level `let` in each page, which does NOT put it on `window` —
     it is reachable by name through the shared global scope and nowhere else.
     Testing `window.S` here meant the clock never ticked once. */
  if (!els.length || typeof S === "undefined" || !S || !S.endsAt) return;
  const from = S.endsAt - S.seconds;
  const secs = Math.max(0, Math.floor(serverNow() - from));
  const txt = Math.floor(secs / 60) + ":" + String(secs % 60).padStart(2, "0");
  els.forEach(el => { el.textContent = txt; });
}, 1000);

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

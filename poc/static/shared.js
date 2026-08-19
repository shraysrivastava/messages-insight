/* Shared helpers for both screens. */

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

/* --------------------------------------------------------------- socket -- */

let sock = null, onState = null, myRole = "player", backoff = 500;

function send(msg) {
  if (sock && sock.readyState === 1) sock.send(JSON.stringify(msg));
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
    send({ t: "hello", role: myRole });
    if (typeof onOpenExtra === "function") onOpenExtra();
    setStatus(true);
  };
  sock.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.t === "state" && onState) onState(msg);
  };
  sock.onclose = () => {
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

/* sound.js — the whole soundtrack, synthesised.
 *
 * Sound is a disproportionate amount of the "fun" (DESIGN §6) and none of it
 * is worth a single network request. Every cue here is two oscillators and an
 * envelope, built at the moment it plays: no files to vendor, nothing to
 * cache, nothing that can 404 on a sofa at 9pm with the lights off.
 *
 * REWRITTEN 2026-09-24. The first version was deliberately ambient — sine
 * waves, a minor pentatonic, "furniture, not music", sparse enough to talk
 * over. It worked exactly as designed and the design was wrong: it made a
 * party game sound like a spa. This one is a game show. Major pentatonic,
 * plucked square waves through a lowpass, a real tempo, and a countdown that
 * climbs. Loud enough to be part of the room.
 *
 * Three rules from the design:
 *
 *   - **Host screen only.** Two devices playing the same cue at different
 *     network latencies sounds broken, not stereo.
 *   - **The gesture is START.** Browsers refuse to make noise before a click,
 *     so the audio context is built on the host's first one.
 *   - **Mute is visible.** Non-negotiable if she is on a call with you while
 *     playing.
 */

const Sound = (() => {
  let ctx = null;
  let muted = localStorage.getItem("rr_mute") === "1";

  function init() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    return ctx;
  }

  /* One voice: a frequency ramp under a gain envelope. Everything below is a
     couple of these stacked. `at` is an offset in seconds so a cue can be
     two notes without two timers. */
  function voice({ from, to = from, type = "sine", at = 0, dur = 0.12,
                   peak = 0.18, curve = "exp", out = null, cut = 0 }) {
    if (!ctx || muted) return;
    const t = ctx.currentTime + at;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(from, t);
    if (to !== from) {
      if (curve === "exp") osc.frequency.exponentialRampToValueAtTime(to, t + dur);
      else osc.frequency.linearRampToValueAtTime(to, t + dur);
    }
    /* Ramp from a hair above zero, not from zero: exponentialRamp refuses a
       zero endpoint, and a linear attack on a short blip clicks. */
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(peak, t + Math.min(0.02, dur / 3));
    gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);

    /* A square wave straight out is a buzzer. The same square under a lowpass
       that closes as the note decays is a marimba-ish pluck, which is the
       whole difference between "quiz show" and "smoke alarm". */
    let node = gain;
    if (cut) {
      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.setValueAtTime(cut, t);
      lp.frequency.exponentialRampToValueAtTime(Math.max(220, cut * 0.25),
                                                t + dur);
      lp.Q.setValueAtTime(6, t);
      gain.connect(lp);
      node = lp;
    }
    osc.connect(gain);
    node.connect(out || ctx.destination);
    osc.start(t);
    osc.stop(t + dur + 0.05);
  }

  /* The workhorse. A plucked note: square through a closing lowpass, short. */
  function pluck(f, at, dur = 0.22, peak = 0.13, out = null) {
    voice({ from: f, type: "square", at, dur, peak, out, cut: f * 7 });
  }

  /* Bass. Triangle keeps the low end round instead of farty. */
  function bass(f, at, dur = 0.26, peak = 0.16, out = null) {
    voice({ from: f, type: "triangle", at, dur, peak, out, cut: f * 9 });
  }


/* The note names the cues are built from. There used to be a bank of musical
 * BEDS under here — a lookahead scheduler, a bus to ramp down, loops for the
 * lobby, the question and the outro. All of it was cut on 2026-09-24: the game
 * wanted sound effects and not a soundtrack, and background music under two
 * people shouting at a television is something to turn off rather than
 * something to listen to. `git log static/sound.js` has it if it is ever
 * wanted back.
 *
 * Major pentatonic — C D E G A. No two of these can clash, so a cue built
 * from them never needs to resolve.
 */

  const C = 261.63, D = 293.66, E = 329.63, G = 392.00, A = 440.00;

  const api = {
    init,
    get muted() { return muted; },
    toggle() {
      muted = !muted;
      localStorage.setItem("rr_mute", muted ? "1" : "0");
      if (!muted) { init(); api.send(); }      // confirm you can hear it
      return muted;
    },

    /* An answer lands. A quick blip up — something leaving the phone. */
    send() {
      init();
      pluck(G * 2, 0, 0.09, 0.10);
      pluck(C * 4, 0.05, 0.10, 0.07);
    },

    /* The reveal, landing after the 450ms of silence. Deliberately neutral:
       who was right is `correct`/`wrong`, a beat later, once the tiles have
       resolved. */
    receive() {
      init();
      pluck(C * 2, 0, 0.12, 0.15);
      pluck(G * 2, 0.08, 0.26, 0.13);
    },

    /* Everybody got it. A rising major arpeggio, the most unsubtle happy noise
       five oscillators can make, which is the correct amount of subtlety. */
    correct() {
      init();
      [C * 2, E * 2, G * 2, C * 4].forEach((f, i) =>
        pluck(f, i * 0.075, i === 3 ? 0.5 : 0.16, i === 3 ? 0.16 : 0.12));
    },

    /* Nobody got it. Two notes down and flat, the pantomime "wrong" — this is
       a shared groan, not a punishment, so it is comic rather than harsh. */
    wrong() {
      init();
      voice({ from: 233, to: 220, type: "square", dur: 0.18, peak: 0.13, cut: 900 });
      voice({ from: 185, to: 138, type: "square", at: 0.15, dur: 0.34,
              peak: 0.14, cut: 700 });
    },

    /* Under the last few seconds, and it CLIMBS — `left` is how many whole
       seconds remain, so the pitch rises as the clock runs out and the last
       one is the highest and hardest. The old tick was a flat low thud, which
       told you the clock existed but never that it was nearly gone. */
    tick(left = 5) {
      init();
      const step = Math.max(0, Math.min(4, 5 - left));   // 0 at 5s, 4 at 1s
      const f = [D, E, G, A, C * 2][step];
      pluck(f, 0, 0.11, 0.09 + step * 0.015);
      if (left <= 1) pluck(f * 2, 0.04, 0.16, 0.09);
    },

    /* One award card dealt. */
    ping() {
      init();
      pluck(C * 4, 0, 0.1, 0.10);
      pluck(G * 4, 0.06, 0.16, 0.06);
    },

    /* The podium. A proper little fanfare: a rising triad, then the octave
       held over a bass root. */
    flourish() {
      init();
      [C * 2, E * 2, G * 2].forEach((f, i) => pluck(f, i * 0.1, 0.26, 0.14));
      pluck(C * 4, 0.3, 0.75, 0.17);
      bass(C / 2, 0.3, 0.9, 0.16);
    },

    /* Every cue in order, for judging them without playing a whole game.
       Open the host screen, click once so the browser allows audio, then run
       `Sound.audition()` in the console. */
    audition() {
      init();
      const seq = ["send", "receive", "correct", "wrong", "ping", "flourish"];
      seq.forEach((n, i) => setTimeout(() => { console.log(n); api[n](); },
                                       i * 1100));
      [5, 4, 3, 2, 1].forEach((n, i) =>
        setTimeout(() => api.tick(n), seq.length * 1100 + i * 450));
    },
  };
  return api;
})();

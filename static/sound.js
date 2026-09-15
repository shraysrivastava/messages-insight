/* sound.js — the whole soundtrack, synthesised.
 *
 * Sound is a disproportionate amount of the "fun" (DESIGN §6) and none of it
 * is worth a single network request. Every cue here is two oscillators and an
 * envelope, built at the moment it plays: no files to vendor, nothing to
 * cache, nothing that can 404 on a sofa at 9pm with the lights off.
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
                   peak = 0.18, curve = "exp" }) {
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
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + dur + 0.05);
  }

  const api = {
    init,
    get muted() { return muted; },
    toggle() {
      muted = !muted;
      localStorage.setItem("rr_mute", muted ? "1" : "0");
      if (!muted) { init(); api.send(); }      // confirm you can hear it
      return muted;
    },

    /* An answer lands. Short, high, upward — the sound of something leaving. */
    send() {
      init();
      voice({ from: 720, to: 1180, dur: 0.1, peak: 0.12 });
    },

    /* The reveal. Two notes, the second lower: something arriving. This is the
       one that has to land after the silence, because the pause is the joke. */
    receive() {
      init();
      voice({ from: 1320, to: 1320, dur: 0.09, peak: 0.16 });
      voice({ from: 880, to: 880, at: 0.1, dur: 0.22, peak: 0.16 });
    },

    /* Under the last few seconds. Low and short enough to sit beneath a room
       of two people shouting at a television. */
    tick() {
      init();
      voice({ from: 190, to: 150, type: "triangle", dur: 0.05, peak: 0.09 });
    },

    /* One award card dealt. */
    ping() {
      init();
      voice({ from: 1046, to: 1046, type: "triangle", dur: 0.1, peak: 0.1 });
      voice({ from: 1568, to: 1568, at: 0.06, dur: 0.14, peak: 0.07 });
    },

    /* The podium. One flourish, not a loop — a rising major triad and a fifth
       on top, which is as close to a fanfare as four oscillators get. */
    flourish() {
      init();
      [523, 659, 784, 1046].forEach((f, i) =>
        voice({ from: f, to: f, type: "triangle", at: i * 0.11,
                dur: i === 3 ? 0.55 : 0.2, peak: i === 3 ? 0.17 : 0.13 }));
    },
  };
  return api;
})();

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

  let bus = null;            // everything the beds play goes through this
  let bed = null;            // { name, timer, until, stop() }

  function init() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    bus = ctx.createGain();
    bus.gain.setValueAtTime(1, ctx.currentTime);
    bus.connect(ctx.destination);
    return ctx;
  }

  /* One voice: a frequency ramp under a gain envelope. Everything below is a
     couple of these stacked. `at` is an offset in seconds so a cue can be
     two notes without two timers. */
  function voice({ from, to = from, type = "sine", at = 0, dur = 0.12,
                   peak = 0.18, curve = "exp", out = null }) {
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
    osc.connect(gain).connect(out || ctx.destination);
    osc.start(t);
    osc.stop(t + dur + 0.05);
  }


/* ── the beds ───────────────────────────────────────────────────────────────
 *
 * The cues above are one-shots: fire and forget. A bed runs until something
 * stops it, which needs two things the cues don't have.
 *
 * **A lookahead scheduler.** `setInterval` is not accurate enough to place a
 * note on — it drifts and it stalls while the tab renders a reveal. So the
 * timer only ever *schedules*: every SCAN ms it queues whatever falls in the
 * next SCAN*2 window, at sample-accurate times taken from `ctx.currentTime`.
 * The audio clock keeps the beat; the JS timer just keeps the queue full.
 *
 * **A group to stop.** Notes already queued will play even after you stop the
 * timer, so every bed note goes through `bus` and stopping ramps the bus down
 * over 120ms. Ramped, not cut: an oscillator stopped at full amplitude clicks.
 *
 * The beds are deliberately sparse and low. This plays under two people
 * talking over each other, not in headphones, and the moment it asks to be
 * listened to it is wrong.
 */

  const SCAN = 250;                        // ms between scheduler wakeups

  /* A minor pentatonic, which is the scale that cannot sound wrong against
     itself — any two of these notes together are consonant, so the arpeggio
     never needs to resolve and the loop never sounds like it restarted. */
  const SCALE = [220.00, 261.63, 293.66, 349.23, 392.00, 440.00, 523.25, 587.33];

  const BEDS = {
    /* Lobby: warm, unhurried, no pulse. Two people are finding the remote and
       arguing about where to sit; this is furniture, not music. */
    lobby(step, at) {
      const n = SCALE[(step * 3) % SCALE.length];
      voice({ from: n, to: n, type: "sine", at, dur: 2.4, peak: 0.045, out: bus });
      if (step % 4 === 0) {
        voice({ from: 110, to: 110, type: "sine", at,
                dur: 4.0, peak: 0.05, out: bus });
      }
      return step % 2 === 0 ? 1.6 : 2.4;        // uneven, so it never marches
    },

    /* Under the question. One low note per beat and nothing else — it exists
       to make the silence when it stops feel like something happened. The
       countdown `tick` plays over the top of it in the last seconds. */
    question(step, at) {
      voice({ from: step % 4 === 0 ? 98 : 73.42, type: "triangle", at,
              dur: 0.5, peak: 0.05, out: bus });
      return 1.0;
    },

    /* After the podium flourish, while the awards deal. Major, slow, resolved
       — the only bed that is allowed to sound like it means it. */
    outro(step, at) {
      const maj = [261.63, 329.63, 392.00, 523.25];
      const n = maj[step % maj.length];
      voice({ from: n, to: n, type: "sine", at, dur: 3.2, peak: 0.05, out: bus });
      if (step % 4 === 0) {
        voice({ from: 130.81, to: 130.81, type: "sine", at,
                dur: 5.0, peak: 0.045, out: bus });
      }
      return 2.0;
    },
  };

  function stopBed() {
    if (!bed) return;
    clearInterval(bed.timer);
    /* Ramp rather than disconnect: notes already queued are still coming, and
       cutting the bus at full amplitude clicks. */
    if (bus && ctx) {
      const t = ctx.currentTime;
      bus.gain.cancelScheduledValues(t);
      bus.gain.setValueAtTime(bus.gain.value || 1, t);
      bus.gain.linearRampToValueAtTime(0.0001, t + 0.12);
      const dead = bus;
      setTimeout(() => { try { dead.disconnect(); } catch (e) {} }, 400);
      bus = ctx.createGain();
      bus.gain.setValueAtTime(1, ctx.currentTime);
      bus.connect(ctx.destination);
    }
    bed = null;
  }

  function startBed(name) {
    if (bed && bed.name === name) return;     // already running; don't restart
    stopBed();
    if (muted || !BEDS[name]) return;
    if (!init()) return;
    const play = BEDS[name];
    let step = 0;
    /* `until` is the audio-clock time the queue is filled to. The scheduler
       tops it up; it never plays anything itself. */
    const state = { name, until: ctx.currentTime, timer: null };
    const pump = () => {
      if (muted) return stopBed();
      /* A suspended context has a frozen `currentTime`, so scheduling against
         it queues notes at times that are all in the past by the moment it
         resumes — and they then fire as one chord. Hold the queue instead,
         and keep `until` pinned to now so it resumes in time rather than
         catching up. This is the state the lobby sits in until the first
         click, which is exactly when it matters. */
      if (ctx.state !== "running") { state.until = ctx.currentTime; return; }
      const horizon = ctx.currentTime + (SCAN * 2) / 1000;
      let guard = 0;
      while (state.until < horizon && guard++ < 16) {
        const wait = Math.max(0, state.until - ctx.currentTime);
        state.until += play(step++, wait);   // `wait` is the offset
      }
    };
    pump();
    state.timer = setInterval(pump, SCAN);
    bed = state;
  }

  const api = {
    init,
    get muted() { return muted; },
    toggle() {
      muted = !muted;
      localStorage.setItem("rr_mute", muted ? "1" : "0");
      if (muted) stopBed();
      else { init(); api.send(); }             // confirm you can hear it
      return muted;
    },

    /* The soundtrack under a phase. `Sound.bed(null)` for silence — which the
       reveal needs, because the 450ms of nothing before the answer is the
       joke and a bed playing through it steps on the punchline. */
    bed(name) {
      if (!name) stopBed();
      else startBed(name);
    },

    get playing() { return bed && bed.name; },

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

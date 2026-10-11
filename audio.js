// Procedural effects: no audio files, network requests or autoplay.
export class SoundEngine {
  constructor({ enabled = true, contextFactory } = {}) {
    this.enabled = enabled;
    this.contextFactory = contextFactory || (() => {
      const Audio = globalThis.AudioContext || globalThis.webkitAudioContext;
      return Audio ? new Audio() : null;
    });
    this.context = null;
    this.master = null;
    this.lastTick = -Infinity;
  }
  unlock() {
    if (!this.enabled) return;
    try {
      if (!this.context) {
        this.context = this.contextFactory();
        if (!this.context) return;
        this.master = this.context.createGain();
        this.master.gain.value = .22;
        this.master.connect(this.context.destination);
      }
      if (this.context.state === 'suspended') this.context.resume().catch(() => {});
    } catch { this.context = null; this.master = null; }
  }
  setEnabled(enabled) {
    this.enabled = enabled;
    if (this.master) this.master.gain.setValueAtTime(enabled ? .22 : 0, this.context.currentTime);
    if (enabled) this.unlock();
  }
  tone(frequency, duration, { offset = 0, volume = .3, type = 'sine', endFrequency = frequency } = {}) {
    const ctx = this.context;
    if (!this.enabled || !ctx || ctx.state !== 'running') return;
    const start = ctx.currentTime + offset;
    const oscillator = ctx.createOscillator(), envelope = ctx.createGain();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(frequency, start);
    oscillator.frequency.exponentialRampToValueAtTime(Math.max(1,endFrequency),start+duration);
    envelope.gain.setValueAtTime(.0001,start);
    envelope.gain.exponentialRampToValueAtTime(volume,start+.004);
    envelope.gain.exponentialRampToValueAtTime(.0001,start+duration);
    oscillator.connect(envelope); envelope.connect(this.master);
    oscillator.onended = () => { oscillator.disconnect(); envelope.disconnect(); };
    oscillator.start(start); oscillator.stop(start+duration+.01);
  }
  play(effect) {
    if (!this.enabled || !this.context || this.context.state !== 'running') return;
    try {
      if (effect === 'click') this.tone(620,.045,{volume:.18,type:'triangle',endFrequency:390});
      if (effect === 'tick') {
        if (this.context.currentTime-this.lastTick < .035) return;
        this.lastTick = this.context.currentTime;
        this.tone(1600,.026,{volume:.12,type:'triangle',endFrequency:850});
      }
      if (effect === 'win') {
        [523.25,659.25,783.99,1046.5].forEach((note,index) => this.tone(note,.22,{offset:index*.075,volume:.28,type:'triangle'}));
        this.tone(1567.98,.4,{offset:.23,volume:.08});
      }
      if (effect === 'lose') {
        this.tone(260,.35,{volume:.22,type:'triangle',endFrequency:110});
        this.tone(196,.28,{offset:.12,volume:.15,endFrequency:82});
      }
    } catch { /* Audio never interrupts game state. */ }
  }
}

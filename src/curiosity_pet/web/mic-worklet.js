// Microphone capture: downsample the device rate (usually 48kHz) to 16kHz and send a PCM16 frame once 512 samples have accumulated.
// A simple box low-pass filter (interval average) runs before downsampling, which is enough for speech recognition.
class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;        // position of the next output sample in the input stream
    this.acc = 0;        // running sum of the current interval
    this.count = 0;
    this.out = new Int16Array(512);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i];
      this.count++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const v = Math.max(-1, Math.min(1, this.acc / this.count));
        this.acc = 0;
        this.count = 0;
        this.out[this.n++] = v < 0 ? v * 32768 : v * 32767;
        if (this.n === this.out.length) {
          this.port.postMessage(this.out.buffer.slice(0));
          this.n = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("mic-processor", MicProcessor);

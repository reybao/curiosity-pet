// 麦克风采集:把设备采样率(通常 48kHz)降到 16kHz,攒够 512 个采样发一帧 PCM16。
// 降采样前先做简单的盒式低通(取区间平均),足够语音识别用。
class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;        // 下一个输出采样在输入流中的位置
    this.acc = 0;        // 当前区间的累加
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

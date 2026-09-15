import { AudioBuffer } from "./AudioBuffer";

export class AudioCapture {
  private readonly buffer = new AudioBuffer<number[]>(64);
  private active = false;

  async start() {
    this.active = true;
    return true;
  }

  stop() {
    this.active = false;
    this.buffer.clear();
  }

  pushChunk(samples: number[]) {
    if (!this.active) {
      return 0;
    }

    this.buffer.push(samples);
    return samples.length;
  }

  takeChunk() {
    return this.buffer.take();
  }

  isActive() {
    return this.active;
  }
}

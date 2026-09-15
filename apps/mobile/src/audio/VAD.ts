export type VADEvent = "speech_start" | "speech_continue" | "speech_end" | "silence";

export type VADOptions = {
  threshold: number;
  silenceTimeoutMs: number;
  minimumSpeechMs: number;
  preRollMs: number;
  postRollMs: number;
};

export class VAD {
  private speechSamples = 0;
  private silenceSamples = 0;

  constructor(
    private readonly options: VADOptions = {
      threshold: 0.38,
      silenceTimeoutMs: 260,
      minimumSpeechMs: 240,
      preRollMs: 120,
      postRollMs: 120
    }
  ) {}

  processChunk(rms: number): VADEvent {
    if (rms > this.options.threshold) {
      this.speechSamples += 1;
      this.silenceSamples = 0;

      if (this.speechSamples === 1) {
        return "speech_start";
      }

      return "speech_continue";
    }

    this.silenceSamples += 1;

    if (this.speechSamples > 0 && this.silenceSamples >= this.options.silenceTimeoutMs) {
      this.speechSamples = 0;
      this.silenceSamples = 0;
      return "speech_end";
    }

    return "silence";
  }
}

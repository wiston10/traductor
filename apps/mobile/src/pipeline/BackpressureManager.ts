export type QueueSizes = {
  audioQueueSize: number;
  translationQueueSize: number;
  ttsQueueSize: number;
};

export type BackpressureAssessment = {
  /** True once any queue is at/over its soft limit and needs attention. */
  underPressure: boolean;
  /** Human-readable warning to surface in the UI/logs (null when healthy). */
  warning: string | null;
  /**
   * Recommended segment capture duration (ms) for the *next* segment.
   * Shrinks toward `minSegmentDurationMs` while under pressure so the
   * pipeline processes smaller units faster instead of dropping any.
   * Grows back toward `maxSegmentDurationMs` once queues drain.
   */
  recommendedSegmentDurationMs: number;
};

export type BackpressureManagerOptions = {
  maxAudioQueue?: number;
  maxTranslationQueue?: number;
  maxTtsQueue?: number;
  minSegmentDurationMs?: number;
  maxSegmentDurationMs?: number;
  /** Queue wait time (ms) considered a warning-worthy lag. */
  queueLagWarningMs?: number;
};

/**
 * Replaces the old "drop oldest segment" backpressure policy.
 *
 * Policy (per product requirement — a sermon transcript must never
 * silently lose sentences):
 *   1. Keep capturing audio regardless of downstream queue pressure.
 *   2. Process the translation/tts queues concurrently (handled by the
 *      pipeline, not here).
 *   3. Optimize processing by shrinking future segment size when queues
 *      are under pressure (`recommendedSegmentDurationMs`).
 *   4. Measure queue lag (see `PipelineQueue.oldestLagMs()`).
 *   5. Surface a warning — never drop automatically.
 *
 * Dropping is only ever performed via `PipelineQueue.dropOldest(true)`,
 * which requires the caller to prove the user explicitly enabled a
 * recovery policy. This manager itself never triggers a drop.
 */
export class BackpressureManager {
  private readonly maxAudioQueue: number;
  private readonly maxTranslationQueue: number;
  private readonly maxTtsQueue: number;
  private readonly minSegmentDurationMs: number;
  private readonly maxSegmentDurationMs: number;
  private readonly queueLagWarningMs: number;
  private currentSegmentDurationMs: number;

  constructor(options: BackpressureManagerOptions = {}) {
    this.maxAudioQueue = options.maxAudioQueue ?? 32;
    this.maxTranslationQueue = options.maxTranslationQueue ?? 16;
    this.maxTtsQueue = options.maxTtsQueue ?? 8;
    this.minSegmentDurationMs = options.minSegmentDurationMs ?? 1500;
    this.maxSegmentDurationMs = options.maxSegmentDurationMs ?? 6000;
    this.queueLagWarningMs = options.queueLagWarningMs ?? 4000;
    this.currentSegmentDurationMs = this.maxSegmentDurationMs;
  }

  /** @deprecated kept only for backward-compat call sites; never causes a drop. */
  shouldDrop(): boolean {
    return false;
  }

  assess(sizes: QueueSizes, oldestLagMs: number | null = null): BackpressureAssessment {
    const overAudio = sizes.audioQueueSize >= this.maxAudioQueue;
    const overTranslation = sizes.translationQueueSize >= this.maxTranslationQueue;
    const overTts = sizes.ttsQueueSize >= this.maxTtsQueue;
    const laggingOut = oldestLagMs !== null && oldestLagMs >= this.queueLagWarningMs;
    const underPressure = overAudio || overTranslation || overTts || laggingOut;

    if (underPressure) {
      // Shrink toward the floor, never below it, so segments stay
      // translatable/speakable instead of vanishing.
      const step = (this.maxSegmentDurationMs - this.minSegmentDurationMs) * 0.25;
      this.currentSegmentDurationMs = Math.max(this.minSegmentDurationMs, this.currentSegmentDurationMs - step);
    } else {
      const step = (this.maxSegmentDurationMs - this.minSegmentDurationMs) * 0.1;
      this.currentSegmentDurationMs = Math.min(this.maxSegmentDurationMs, this.currentSegmentDurationMs + step);
    }

    let warning: string | null = null;
    if (underPressure) {
      const parts: string[] = [];
      if (overAudio) parts.push(`audio queue ${sizes.audioQueueSize}/${this.maxAudioQueue}`);
      if (overTranslation) parts.push(`translation queue ${sizes.translationQueueSize}/${this.maxTranslationQueue}`);
      if (overTts) parts.push(`tts queue ${sizes.ttsQueueSize}/${this.maxTtsQueue}`);
      if (laggingOut) parts.push(`oldest segment lag ${Math.round(oldestLagMs ?? 0)}ms`);
      warning = `Backpressure: ${parts.join(", ")}. Shrinking next segment to ${Math.round(this.currentSegmentDurationMs)}ms. No segments were dropped.`;
    }

    return {
      underPressure,
      warning,
      recommendedSegmentDurationMs: Math.round(this.currentSegmentDurationMs)
    };
  }

  summary() {
    return {
      maxAudioQueue: this.maxAudioQueue,
      maxTranslationQueue: this.maxTranslationQueue,
      maxTtsQueue: this.maxTtsQueue,
      minSegmentDurationMs: this.minSegmentDurationMs,
      maxSegmentDurationMs: this.maxSegmentDurationMs
    };
  }
}

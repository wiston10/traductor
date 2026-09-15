import { monotonicNowMs } from "./MonotonicClock";

/**
 * The full set of marks a single pipeline segment can record, in the order
 * they occur for a healthy segment. Not every mark is guaranteed to be
 * present (e.g. a segment that errors out before TTS will never get
 * `ttsStart`/`firstAudio`) — callers must treat missing marks as `null`,
 * never invent a value.
 */
export type TimelineMarkName =
  | "captureStart"
  | "speechStart"
  | "speechEnd"
  | "chunkReady"
  | "sttStart"
  | "sttFinal"
  | "translationStart"
  | "translationComplete"
  | "ttsStart"
  | "firstAudio";

export type SegmentLatencyMetrics = {
  sttLatencyMs: number | null;
  translationLatencyMs: number | null;
  ttsLatencyMs: number | null;
  endToEndLatencyMs: number | null;
};

/**
 * Per-segment timeline of monotonic marks. Every pipeline segment must own
 * its own instance — marks must never be shared/global, otherwise
 * concurrent segments corrupt each other's latency measurements.
 */
export class PerformanceTimeline {
  private readonly marks = new Map<TimelineMarkName, number>();

  /** Records `name` at the current monotonic time. Returns the recorded value. */
  mark(name: TimelineMarkName): number {
    const value = monotonicNowMs();
    this.marks.set(name, value);
    return value;
  }

  /** Returns the recorded monotonic time for `name`, or null if it was never marked. */
  get(name: TimelineMarkName): number | null {
    return this.marks.has(name) ? (this.marks.get(name) as number) : null;
  }

  has(name: TimelineMarkName): boolean {
    return this.marks.has(name);
  }

  /**
   * Duration between two marks. Returns null (never a fabricated number)
   * when either mark is missing or when the computed duration would be
   * negative (which would indicate the marks were recorded out of order,
   * e.g. because a stage never actually ran).
   */
  duration(fromMark: TimelineMarkName, toMark: TimelineMarkName): number | null {
    const from = this.marks.get(fromMark);
    const to = this.marks.get(toMark);

    if (from === undefined || to === undefined) {
      return null;
    }

    const delta = to - from;
    return delta >= 0 ? delta : null;
  }

  metrics(): SegmentLatencyMetrics {
    return {
      sttLatencyMs: this.duration("chunkReady", "sttFinal"),
      translationLatencyMs: this.duration("translationStart", "translationComplete"),
      ttsLatencyMs: this.duration("ttsStart", "firstAudio"),
      endToEndLatencyMs: this.duration("speechStart", "firstAudio")
    };
  }

  toJSON() {
    return Object.fromEntries(this.marks.entries());
  }
}

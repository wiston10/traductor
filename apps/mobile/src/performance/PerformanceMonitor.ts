import type { Logger } from "../logging/Logger";
import type { LatencyMetrics } from "../types/pipeline";
import { monotonicNowMs } from "./MonotonicClock";

/**
 * @deprecated Superseded by per-segment `PerformanceTimeline`, which
 * avoids cross-segment mark collisions entirely. Kept only for any
 * legacy call sites; marks are now recorded with the same monotonic
 * clock (never `Date.now()`) so at least this class can no longer
 * produce negative latencies.
 */
export class PerformanceMonitor {
  private readonly markTimes = new Map<string, number>();

  constructor(private readonly logger: Logger) {}

  mark(label: string) {
    const at = monotonicNowMs();
    this.markTimes.set(label, at);
    this.logger.log("info", "[PERFORMANCE] mark", { label, at });
  }

  measure(from: string, to: string): number | null {
    const start = this.markTimes.get(from);
    const end = this.markTimes.get(to);

    if (start === undefined || end === undefined) {
      return null;
    }

    const delta = end - start;
    return delta >= 0 ? delta : null;
  }

  snapshot(): LatencyMetrics {
    return {
      sttLatencyMs: this.measure("chunkReady", "sttFinal"),
      translationLatencyMs: this.measure("translationStart", "translationComplete"),
      ttsLatencyMs: this.measure("ttsStart", "firstAudio"),
      endToEndLatencyMs: this.measure("speechStart", "firstAudio")
    };
  }
}

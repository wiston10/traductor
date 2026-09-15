import type { Logger } from "../logging/Logger";
import { TranscriptStore } from "../transcript/TranscriptStore";
import { SegmentIdGenerator } from "./SegmentIdGenerator";
import { PerformanceTimeline } from "../performance/PerformanceTimeline";
import { monotonicNowMs } from "../performance/MonotonicClock";
import type { PipelineSegment, TranslationRequest } from "../types/pipeline";

const DEMO_SAMPLE_SEGMENTS: Array<{ original: string; translated: string }> = [
  { original: "Hoy vamos a estudiar la palabra de Dios. [DEMO]", translated: "Heute werden wir das Wort Gottes studieren. [DEMO]" },
  { original: "La Biblia nos enseña esperanza y verdad. [DEMO]", translated: "Die Bibel lehrt uns Hoffnung und Wahrheit. [DEMO]" },
  { original: "Gracias por escuchar esta predicación. [DEMO]", translated: "Danke, dass ihr dieser Predigt zugehört habt. [DEMO]" }
];

/**
 * Demo-only pipeline: plays back fixed sample text so the UI can be
 * exercised without a microphone/on-device models. This is intentionally
 * a completely separate class from `TranslationPipeline` (the real,
 * `offline-real` pipeline) so demo data can never leak into a real
 * session — every demo segment is also visibly tagged `[DEMO]` in its
 * text and carries `mode: "demo"`.
 */
export class DemoPipeline {
  readonly mode = "demo" as const;

  private readonly listeners = new Set<(segment: PipelineSegment) => void>();
  private readonly segmentIdGenerator = new SegmentIdGenerator();
  private readonly transcriptStore: TranscriptStore;
  private readonly logger: Logger;
  private latestMetrics: PipelineSegment["metrics"] | null = null;
  private stopped = false;

  constructor(options: { logger: Logger; transcriptStore: TranscriptStore }) {
    this.logger = options.logger;
    this.transcriptStore = options.transcriptStore;
  }

  async initialize(_request: TranslationRequest) {
    this.logger.log("info", "[DEMO PIPELINE] initialized (demo mode — not real transcription/translation/TTS)");
  }

  subscribe(listener: (segment: PipelineSegment) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async start() {
    this.stopped = false;
    this.logger.log("warn", "[DEMO PIPELINE] playing back fixed demo segments; this is not real speech processing");

    for (const sample of DEMO_SAMPLE_SEGMENTS) {
      if (this.stopped) {
        break;
      }

      const timeline = new PerformanceTimeline();
      timeline.mark("captureStart");
      timeline.mark("speechStart");
      // Demo playback has no real audio/model latency to measure, so we
      // do not fabricate STT/translation/TTS marks — only capture/end
      // marks are set, and per-stage metrics report null rather than an
      // invented number.
      timeline.mark("speechEnd");

      const id = this.segmentIdGenerator.next();
      const now = monotonicNowMs();
      const segment: PipelineSegment = {
        id,
        sequenceNumber: this.segmentIdGenerator.peekCount(),
        timestampStart: now,
        timestampEnd: now,
        originalText: sample.original,
        translatedText: sample.translated,
        status: "played",
        metrics: timeline.metrics()
      };

      this.latestMetrics = segment.metrics ?? null;
      this.transcriptStore.appendSegment({
        id: segment.id,
        timestamp: Date.now(),
        original: segment.originalText,
        translation: segment.translatedText
      });

      this.listeners.forEach((listener) => listener(segment));
    }
  }

  stop() {
    this.stopped = true;
    this.logger.log("info", "[DEMO PIPELINE] stopped");
  }

  getLatestLatencyMs() {
    return this.latestMetrics?.endToEndLatencyMs ?? null;
  }
}

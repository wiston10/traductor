import type { Logger } from "../logging/Logger";
import { SpeechStateMachine } from "../audio/SpeechStateMachine";
import { ModelManager } from "../models/ModelManager";
import { AppleSpeechEngine } from "../stt/AppleSpeechEngine";
import { AppleTranslationEngine } from "../translation/AppleTranslationEngine";
import { AppleTTSEngine } from "../tts/AppleTTSEngine";
import { TranscriptStore } from "../transcript/TranscriptStore";
import { PipelineQueue } from "./PipelineQueue";
import { BackpressureManager } from "./BackpressureManager";
import { SegmentIdGenerator } from "./SegmentIdGenerator";
import { PerformanceTimeline } from "../performance/PerformanceTimeline";
import { localeForLanguage, languageTagForLanguage } from "../utils/localeMapping";
import type { PipelineSegment, TranslationRequest } from "../types/pipeline";
import type { SpeechRecognitionEvent } from "../stt/STTEngine";

export type TranslationPipelineOptions = {
  logger: Logger;
  transcriptStore: TranscriptStore;
};

type QueuedSegment = {
  segment: PipelineSegment;
  timeline: PerformanceTimeline;
};

/**
 * Real offline pipeline: microphone audio -> on-device STT
 * (SFSpeechRecognizer) -> on-device translation (Apple Translation
 * framework) -> on-device TTS (AVSpeechSynthesizer). No stage returns
 * canned/mock data; every "*_complete" log only fires once the
 * corresponding async engine call has actually resolved.
 *
 * This class is the `offline-real` pipeline only. Demo data must never
 * flow through it — see `DemoPipeline` for the separate, clearly-labeled
 * demo data path.
 */
export class TranslationPipeline {
  readonly mode = "offline-real" as const;

  private readonly listeners = new Set<(segment: PipelineSegment) => void>();
  private readonly translationQueue = new PipelineQueue<QueuedSegment>(16);
  private readonly ttsQueue = new PipelineQueue<QueuedSegment>(8);
  private readonly backpressure = new BackpressureManager();
  private readonly segmentIdGenerator = new SegmentIdGenerator();
  private readonly sttEngine = new AppleSpeechEngine();
  private readonly translationEngine = new AppleTranslationEngine();
  private readonly ttsEngine = new AppleTTSEngine();
  private readonly modelManager: ModelManager;
  private readonly speechStateMachine: SpeechStateMachine;
  private readonly transcriptStore: TranscriptStore;
  private readonly logger: Logger;

  private currentRequest: TranslationRequest | null = null;
  private timelinesBySegmentId = new Map<string, PerformanceTimeline>();
  private latestMetrics: PipelineSegment["metrics"] | null = null;

  constructor({ logger, transcriptStore }: TranslationPipelineOptions) {
    this.logger = logger;
    this.transcriptStore = transcriptStore;
    this.modelManager = new ModelManager(logger, this.sttEngine, this.translationEngine, this.ttsEngine);
    // No local VAD is used for real capture: Apple's SFSpeechRecognizer
    // reports real speech boundaries itself (see AppleSpeechEngine).
    this.speechStateMachine = new SpeechStateMachine(null, () => this.segmentIdGenerator.next());
  }

  async initialize(request: TranslationRequest) {
    this.currentRequest = request;
    await this.modelManager.ensureModels(
      languageTagForLanguage(request.sourceLanguage),
      languageTagForLanguage(request.targetLanguage)
    );
    this.logger.log("info", "[PIPELINE] offline-real pipeline initialized", {
      sourceLanguage: request.sourceLanguage,
      targetLanguage: request.targetLanguage,
      outputMode: request.outputMode
    });
  }

  subscribe(listener: (segment: PipelineSegment) => void) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async start() {
    if (!this.currentRequest) {
      throw new Error("TranslationPipeline.start() called before initialize()");
    }

    this.logger.log("info", "[PIPELINE] starting real microphone capture");
    this.sttEngine.start(localeForLanguage(this.currentRequest.sourceLanguage), (event) => this.handleSttEvent(event));
  }

  stop() {
    this.sttEngine.stop();
    this.ttsEngine.stop();
    this.translationQueue.clear();
    this.ttsQueue.clear();
    this.speechStateMachine.reset();
    this.logger.log("info", "[PIPELINE] stopped");
  }

  getLatestLatencyMs() {
    return this.latestMetrics?.endToEndLatencyMs ?? null;
  }

  private handleSttEvent(event: SpeechRecognitionEvent) {
    switch (event.type) {
      case "speech_start": {
        const transition = this.speechStateMachine.applyExternalEvent("speech_start");
        if (transition.changed && transition.segmentId) {
          const timeline = new PerformanceTimeline();
          timeline.mark("captureStart");
          timeline.mark("speechStart");
          this.timelinesBySegmentId.set(transition.segmentId, timeline);
        }
        break;
      }
      case "speech_end": {
        this.speechStateMachine.applyExternalEvent("speech_end");
        const segmentId = this.speechStateMachine.getActiveSegmentId();
        if (segmentId) {
          this.timelinesBySegmentId.get(segmentId)?.mark("speechEnd");
        }
        break;
      }
      case "final": {
        void this.handleFinalTranscript(event.text);
        break;
      }
      case "partial":
        // Partial transcripts are not queued for translation; only the
        // final transcript is committed, per Apple's recognition task
        // contract (isFinal). Consumers that want live partials can
        // subscribe directly to the STT engine in a future iteration.
        break;
      case "error":
        this.logger.log("error", "[PIPELINE] speech recognition error", { message: event.message });
        break;
    }
  }

  private async handleFinalTranscript(finalText: string) {
    const segmentId = this.speechStateMachine.getActiveSegmentId();
    if (!segmentId) {
      this.logger.log("warn", "[PIPELINE] received final transcript with no active segment; ignoring");
      return;
    }

    const timeline = this.timelinesBySegmentId.get(segmentId) ?? new PerformanceTimeline();
    timeline.mark("chunkReady");
    timeline.mark("sttStart");
    timeline.mark("sttFinal");

    // Hand off to the queues, then immediately release the capture-side
    // state machine so the next utterance can be detected while this one
    // is translated/synthesized concurrently (backpressure policy: never
    // pause capture).
    this.speechStateMachine.beginProcessing();
    this.speechStateMachine.completeProcessing();

    const trimmed = finalText.trim();
    if (!trimmed) {
      this.timelinesBySegmentId.delete(segmentId);
      return;
    }

    const now = Date.now();
    const segment: PipelineSegment = {
      id: segmentId,
      sequenceNumber: this.segmentIdGenerator.peekCount(),
      timestampStart: now,
      timestampEnd: now,
      originalText: trimmed,
      translatedText: "",
      status: "transcribed"
    };

    this.translationQueue.push({ segment, timeline });
    this.reportBackpressure();

    void this.processTranslationAndTts();
  }

  private reportBackpressure() {
    const assessment = this.backpressure.assess(
      {
        audioQueueSize: 0,
        translationQueueSize: this.translationQueue.size,
        ttsQueueSize: this.ttsQueue.size
      },
      this.translationQueue.oldestLagMs()
    );

    if (assessment.warning) {
      this.logger.log("warn", `[PIPELINE] ${assessment.warning}`);
    }

    return assessment;
  }

  private async processTranslationAndTts() {
    const request = this.currentRequest;
    if (!request) {
      return;
    }

    const dequeued = this.translationQueue.shiftWithLag();
    if (!dequeued) {
      return;
    }

    const { segment, timeline } = dequeued.item;

    try {
      timeline.mark("translationStart");
      const translatedText = await this.translationEngine.translate(segment.originalText);
      timeline.mark("translationComplete");

      const translatedSegment: PipelineSegment = { ...segment, translatedText, status: "translated" };
      this.ttsQueue.push({ segment: translatedSegment, timeline });
      this.reportBackpressure();

      timeline.mark("ttsStart");
      await this.ttsEngine.speak(translatedText, localeForLanguage(request.targetLanguage), (ttsEvent) => {
        if (ttsEvent === "first_audio") {
          timeline.mark("firstAudio");
        }
      });

      this.ttsQueue.shift();

      const metrics = timeline.metrics();
      this.latestMetrics = metrics;

      const playedSegment: PipelineSegment = { ...translatedSegment, status: "played", metrics };

      this.transcriptStore.appendSegment({
        id: playedSegment.id,
        timestamp: playedSegment.timestampStart,
        original: playedSegment.originalText,
        translation: playedSegment.translatedText
      });

      this.listeners.forEach((listener) => listener(playedSegment));
      this.logger.log("info", "[PIPELINE] segment processed", {
        id: playedSegment.id,
        metrics,
        translatedText
      });
    } catch (error) {
      const errorText = error instanceof Error ? error.message : "pipeline stage failed";
      this.logger.log("error", "[PIPELINE] segment failed", { id: segment.id, error: errorText });
      this.listeners.forEach((listener) => listener({ ...segment, status: "error" }));
    } finally {
      this.timelinesBySegmentId.delete(segment.id);
    }
  }
}

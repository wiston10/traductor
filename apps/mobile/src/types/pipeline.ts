import type { LanguageCode, OutputMode, TranslatorVoice } from "@traductor/shared";
import type { SegmentLatencyMetrics } from "../performance/PerformanceTimeline";

export type PipelineStage = "audio" | "vad" | "stt" | "translation" | "tts" | "playback";
export type PipelineSegmentStatus = "queued" | "transcribed" | "translated" | "tts_ready" | "played" | "error";
export type PipelineMode = "demo" | "offline-real";

export type PipelineSegment = {
  id: string;
  sequenceNumber: number;
  timestampStart: number;
  timestampEnd: number;
  originalText: string;
  translatedText: string;
  status: PipelineSegmentStatus;
  /** Present once the segment's timeline has recorded enough marks to compute it. */
  metrics?: SegmentLatencyMetrics;
};

export type TranslationRequest = {
  sourceLanguage: LanguageCode;
  targetLanguage: LanguageCode;
  outputMode: OutputMode;
  voice: TranslatorVoice;
};

export type LatencyMetrics = SegmentLatencyMetrics;

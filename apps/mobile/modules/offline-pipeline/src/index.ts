import { requireNativeModule, EventEmitter } from "expo-modules-core";

export type TranslationAvailability = "installed" | "supported" | "unsupported";

type NativeOfflinePipelineModule = {
  requestSpeechAuthorization(): Promise<boolean>;
  supportsOnDeviceRecognition(localeIdentifier: string): boolean;
  startRecognition(localeIdentifier: string): void;
  stopRecognition(): void;
  checkTranslationAvailability(from: string, to: string): Promise<TranslationAvailability>;
  prepareTranslationLanguages(from: string, to: string): Promise<void>;
  translate(text: string, from: string, to: string): Promise<string>;
  speak(text: string, languageIdentifier: string): void;
  stopSpeaking(): void;
};

export type OfflinePipelineEvents = {
  onSpeechStart: () => void;
  onPartialTranscript: (payload: { text: string }) => void;
  onFinalTranscript: (payload: { text: string }) => void;
  onSpeechEnd: () => void;
  onSttError: (payload: { message: string }) => void;
  onTtsStart: () => void;
  onFirstAudio: () => void;
  onTtsFinished: () => void;
  onTtsError: (payload: { message: string }) => void;
};

/**
 * Native bridge into `SFSpeechRecognizer` (on-device STT), Apple's
 * `Translation` framework (real on-device MT) and `AVSpeechSynthesizer`
 * (real TTS). There is no JS-side fallback that fabricates results — if
 * the native module is unavailable (e.g. non-iOS platform, simulator
 * without the entitlement, or OS below the minimum version) calls throw
 * explicit errors instead of returning canned text.
 */
const NativeOfflinePipeline = requireNativeModule<NativeOfflinePipelineModule>("OfflinePipeline");

export const offlinePipelineEvents = new EventEmitter<OfflinePipelineEvents>(
  NativeOfflinePipeline as unknown as InstanceType<typeof EventEmitter>
);

export default NativeOfflinePipeline;

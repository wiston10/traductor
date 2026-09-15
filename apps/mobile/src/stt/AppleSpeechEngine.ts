import { Platform } from "react-native";
import NativeOfflinePipeline, { offlinePipelineEvents } from "offline-pipeline";
import { STTEngine, type SpeechRecognitionEvent } from "./STTEngine";

/**
 * Real on-device speech recognition backed by Apple's `SFSpeechRecognizer`
 * with `requiresOnDeviceRecognition = true` (see
 * modules/offline-pipeline/ios/SpeechRecognitionManager.swift). Every
 * event here is produced by the native module from live microphone audio
 * — nothing is fabricated in JS.
 */
export class AppleSpeechEngine extends STTEngine {
  private subscriptions: { remove(): void }[] = [];
  private authorized = false;

  async initialize(): Promise<void> {
    if (Platform.OS !== "ios") {
      throw new Error("AppleSpeechEngine requires iOS (SFSpeechRecognizer is not available on this platform)");
    }

    this.authorized = await NativeOfflinePipeline.requestSpeechAuthorization();
    if (!this.authorized) {
      throw new Error("Speech recognition / microphone authorization was denied");
    }
  }

  isOnDeviceRecognitionAvailable(localeIdentifier: string): boolean {
    return NativeOfflinePipeline.supportsOnDeviceRecognition(localeIdentifier);
  }

  start(localeIdentifier: string, onEvent: (event: SpeechRecognitionEvent) => void): void {
    if (!this.authorized) {
      throw new Error("Cannot start recognition before initialize() has granted authorization");
    }

    if (!this.isOnDeviceRecognitionAvailable(localeIdentifier)) {
      throw new Error(`On-device speech recognition is not available for locale "${localeIdentifier}" on this device`);
    }

    this.teardownSubscriptions();

    this.subscriptions = [
      offlinePipelineEvents.addListener("onSpeechStart", () => onEvent({ type: "speech_start" })),
      offlinePipelineEvents.addListener("onPartialTranscript", (payload: { text: string }) =>
        onEvent({ type: "partial", text: payload.text })
      ),
      offlinePipelineEvents.addListener("onFinalTranscript", (payload: { text: string }) =>
        onEvent({ type: "final", text: payload.text })
      ),
      offlinePipelineEvents.addListener("onSpeechEnd", () => onEvent({ type: "speech_end" })),
      offlinePipelineEvents.addListener("onSttError", (payload: { message: string }) =>
        onEvent({ type: "error", message: payload.message })
      )
    ];

    NativeOfflinePipeline.startRecognition(localeIdentifier);
  }

  stop(): void {
    NativeOfflinePipeline.stopRecognition();
    this.teardownSubscriptions();
  }

  async dispose(): Promise<void> {
    this.stop();
  }

  private teardownSubscriptions() {
    this.subscriptions.forEach((subscription) => subscription.remove());
    this.subscriptions = [];
  }
}

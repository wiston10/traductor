import { Platform } from "react-native";
import NativeOfflinePipeline, { offlinePipelineEvents } from "offline-pipeline";
import { TTSEngine, type SpeechArtifact, type TTSEvent } from "./TTSEngine";

let speechIdCounter = 0;

/**
 * Real speech synthesis via `AVSpeechSynthesizer` (see
 * modules/offline-pipeline/ios/SpeechSynthesisManager.swift).
 * `first_audio` is forwarded only once the native
 * `AVSpeechSynthesizerDelegate.didStart` callback fires, i.e. once audio
 * playback has actually begun — never simulated with a delay.
 */
export class AppleTTSEngine extends TTSEngine {
  async initialize(): Promise<void> {
    if (Platform.OS !== "ios") {
      throw new Error("AppleTTSEngine requires iOS (AVSpeechSynthesizer is not available on this platform)");
    }
  }

  speak(text: string, languageIdentifier: string, onEvent?: (event: TTSEvent) => void): Promise<SpeechArtifact> {
    const trimmed = text.trim();
    if (!trimmed) {
      return Promise.reject(new Error("Cannot synthesize empty text"));
    }

    speechIdCounter += 1;
    const id = `speech-${speechIdCounter}`;

    return new Promise<SpeechArtifact>((resolve, reject) => {
      const subscriptions = [
        offlinePipelineEvents.addListener("onTtsStart", () => onEvent?.("tts_start")),
        offlinePipelineEvents.addListener("onFirstAudio", () => onEvent?.("first_audio")),
        offlinePipelineEvents.addListener("onTtsFinished", () => {
          onEvent?.("finished");
          teardown();
          resolve({ id, text: trimmed });
        }),
        offlinePipelineEvents.addListener("onTtsError", (payload: { message: string }) => {
          onEvent?.({ error: payload.message });
          teardown();
          reject(new Error(payload.message));
        })
      ];

      function teardown() {
        subscriptions.forEach((subscription) => subscription.remove());
      }

      NativeOfflinePipeline.speak(trimmed, languageIdentifier);
    });
  }

  stop(): void {
    NativeOfflinePipeline.stopSpeaking();
  }

  async dispose(): Promise<void> {
    this.stop();
  }
}

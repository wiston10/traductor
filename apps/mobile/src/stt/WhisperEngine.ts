import { STTEngine, type SpeechRecognitionEvent } from "./STTEngine";

/**
 * Fallback local STT engine (priority #2 behind Apple's on-device
 * SFSpeechRecognizer). A real implementation requires bundling a
 * whisper.cpp build plus a quantized ggml model asset and a native
 * bridge to feed it live PCM buffers — that native bridge has not been
 * built yet. This class intentionally throws instead of returning any
 * placeholder/mock transcript, so callers can never mistake "not
 * implemented" for a working offline transcription path.
 */
export class WhisperEngine extends STTEngine {
  async initialize(): Promise<void> {
    throw new Error(
      "WhisperEngine is not implemented yet: whisper.cpp is not bundled/bridged in this build. Use AppleSpeechEngine (on-device SFSpeechRecognizer) instead."
    );
  }

  isOnDeviceRecognitionAvailable(): boolean {
    return false;
  }

  start(_localeIdentifier: string, _onEvent: (event: SpeechRecognitionEvent) => void): void {
    throw new Error("WhisperEngine is not implemented yet");
  }

  stop(): void {
    // no-op: nothing was ever started
  }

  async dispose(): Promise<void> {
    // no-op
  }
}

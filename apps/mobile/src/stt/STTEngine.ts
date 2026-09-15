export type SpeechRecognitionEvent =
  | { type: "speech_start" }
  | { type: "partial"; text: string }
  | { type: "final"; text: string }
  | { type: "speech_end" }
  | { type: "error"; message: string };

/**
 * Real streaming speech-to-text. Implementations must transcribe actual
 * captured microphone audio — there is no `transcribeSegment(text)` shape
 * here anymore, because a real STT engine never takes text as input.
 */
export abstract class STTEngine {
  abstract initialize(): Promise<void>;
  abstract isOnDeviceRecognitionAvailable(localeIdentifier: string): boolean;
  abstract start(localeIdentifier: string, onEvent: (event: SpeechRecognitionEvent) => void): void;
  abstract stop(): void;
  abstract dispose(): Promise<void>;
}

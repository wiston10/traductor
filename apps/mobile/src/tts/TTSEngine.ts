export type SpeechArtifact = {
  id: string;
  text: string;
};

export type TTSEvent = "tts_start" | "first_audio" | "finished" | { error: string };

/**
 * Real speech synthesis contract. `speak` must trigger actual audio
 * playback — `onEvent("first_audio")` may only fire once the audio
 * engine confirms playback has begun (never on a timer/estimate).
 */
export abstract class TTSEngine {
  abstract initialize(): Promise<void>;
  abstract speak(text: string, languageIdentifier: string, onEvent?: (event: TTSEvent) => void): Promise<SpeechArtifact>;
  abstract stop(): void;
  abstract dispose(): Promise<void>;
}

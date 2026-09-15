export type TranslationAvailability = "installed" | "supported" | "unsupported";

/**
 * Real machine translation engine contract. `translate` must run actual
 * on-device inference — never a dictionary lookup, never the input text
 * returned unchanged, never a suffix appended to fake a translation.
 */
export abstract class TranslationEngine {
  abstract initialize(sourceLanguage: string, targetLanguage: string): Promise<void>;
  abstract translate(text: string): Promise<string>;
  abstract dispose(): Promise<void>;
}

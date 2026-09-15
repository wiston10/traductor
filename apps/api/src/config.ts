import type { LanguageCode, OutputMode, TranslatorVoice } from "@traductor/shared";

export type RuntimeConfig = {
  sttModelPath: string;
  translationModelPath: string;
  ttsModelPath: string;
  offlineMode: boolean;
  host: string;
  port: number;
};

export type RealtimeRequestOptions = {
  sourceLanguage: LanguageCode;
  targetLanguage: LanguageCode;
  outputMode: OutputMode;
  voice: TranslatorVoice;
};

export const supportedVoices = new Set<TranslatorVoice>(["marin", "cedar", "verse", "alloy", "ash"]);
export const supportedOutputModes = new Set<OutputMode>(["audio", "text"]);
export const supportedLanguageCodes = new Set<LanguageCode>([
  "auto",
  "es",
  "en",
  "fr",
  "de",
  "it",
  "pt",
  "ja",
  "ko",
  "zh",
  "ar"
]);

export function loadConfig(): RuntimeConfig {
  return {
    sttModelPath: process.env.STT_MODEL_PATH ?? "/models/es-de-whisper.bin",
    translationModelPath: process.env.TRANSLATION_MODEL_PATH ?? "/models/nllb-es-de.onnx",
    ttsModelPath: process.env.TTS_MODEL_PATH ?? "/models/es-de-tts.bin",
    offlineMode: (process.env.OFFLINE_MODE ?? "true").toLowerCase() === "true",
    host: process.env.HOST ?? "0.0.0.0",
    port: Number(process.env.PORT ?? 3000)
  };
}

export function parseRealtimeHeaders(headers: Record<string, string | string[] | undefined>): RealtimeRequestOptions {
  const sourceLanguage = firstHeader(headers["x-source-language"]) as LanguageCode | undefined;
  const targetLanguage = firstHeader(headers["x-target-language"]) as LanguageCode | undefined;
  const outputMode = firstHeader(headers["x-output-mode"]) as OutputMode | undefined;
  const voice = firstHeader(headers["x-voice"]) as TranslatorVoice | undefined;

  return {
    sourceLanguage: supportedLanguageCodes.has(sourceLanguage ?? "auto") ? sourceLanguage ?? "auto" : "auto",
    targetLanguage: supportedLanguageCodes.has(targetLanguage ?? "de") && targetLanguage !== "auto" ? targetLanguage ?? "de" : "de",
    outputMode: supportedOutputModes.has(outputMode ?? "audio") ? outputMode ?? "audio" : "audio",
    voice: supportedVoices.has(voice ?? "marin") ? voice ?? "marin" : "marin"
  };
}

function firstHeader(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

import type { LanguageCode } from "@traductor/shared";

const LOCALE_BY_LANGUAGE: Partial<Record<LanguageCode, string>> = {
  es: "es-ES",
  en: "en-US",
  fr: "fr-FR",
  de: "de-DE",
  it: "it-IT",
  pt: "pt-PT",
  ja: "ja-JP",
  ko: "ko-KR",
  zh: "zh-CN",
  ar: "ar-SA"
};

/** BCP-47 locale identifier for Apple's Speech/TTS frameworks. */
export function localeForLanguage(code: LanguageCode): string {
  const locale = LOCALE_BY_LANGUAGE[code];
  if (!locale) {
    throw new Error(`No concrete on-device locale is configured for language code "${code}" (auto-detect is not supported by on-device STT/TTS)`);
  }
  return locale;
}

/** Bare language subtag (e.g. "es") accepted by Apple's Translation framework's `Locale.Language`. */
export function languageTagForLanguage(code: LanguageCode): string {
  if (code === "auto") {
    throw new Error('Translation requires a concrete source language; "auto" is not supported');
  }
  return code;
}

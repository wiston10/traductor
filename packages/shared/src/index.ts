export type LanguageCode = "auto" | "es" | "en" | "fr" | "de" | "it" | "pt" | "ja" | "ko" | "zh" | "ar";

export type OutputMode = "audio" | "text";

export type TranslatorVoice = "marin" | "cedar" | "verse" | "alloy" | "ash";

export type RealtimeTranslatorSettings = {
  sourceLanguage: LanguageCode;
  targetLanguage: LanguageCode;
  outputMode: OutputMode;
  voice: TranslatorVoice;
};

export type LanguageOption = {
  code: LanguageCode;
  label: string;
  nativeLabel: string;
};

export const languageOptions: LanguageOption[] = [
  { code: "auto", label: "Auto", nativeLabel: "Auto" },
  { code: "es", label: "Spanish", nativeLabel: "Español" },
  { code: "en", label: "English", nativeLabel: "English" },
  { code: "fr", label: "French", nativeLabel: "Français" },
  { code: "de", label: "German", nativeLabel: "Deutsch" },
  { code: "it", label: "Italian", nativeLabel: "Italiano" },
  { code: "pt", label: "Portuguese", nativeLabel: "Português" },
  { code: "ja", label: "Japanese", nativeLabel: "日本語" },
  { code: "ko", label: "Korean", nativeLabel: "한국어" },
  { code: "zh", label: "Chinese", nativeLabel: "中文" },
  { code: "ar", label: "Arabic", nativeLabel: "العربية" }
];

export const targetLanguageOptions = languageOptions.filter((language) => language.code !== "auto");

export const voiceOptions: Array<{ value: TranslatorVoice; label: string }> = [
  { value: "marin", label: "Marin" },
  { value: "cedar", label: "Cedar" },
  { value: "verse", label: "Verse" },
  { value: "alloy", label: "Alloy" },
  { value: "ash", label: "Ash" }
];

export const defaultTranslatorSettings: RealtimeTranslatorSettings = {
  sourceLanguage: "es",
  targetLanguage: "de",
  outputMode: "audio",
  voice: "marin"
};

export function getLanguageLabel(code: LanguageCode) {
  return languageOptions.find((language) => language.code === code)?.nativeLabel ?? code;
}

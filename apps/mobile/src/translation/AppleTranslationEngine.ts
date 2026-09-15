import { Platform } from "react-native";
import NativeOfflinePipeline from "offline-pipeline";
import { TranslationEngine } from "./TranslationEngine";

/**
 * Real on-device translation using Apple's `Translation` framework
 * (`TranslationSession`, see
 * modules/offline-pipeline/ios/TranslationManager.swift). This runs
 * actual on-device MT inference shipped by Apple for the requested
 * language pair — no dictionaries, no static strings, no network calls,
 * no OpenAI/paid APIs.
 *
 * NLLB / MarianMT were evaluated as alternatives but were rejected for
 * this build: shipping either requires converting multi-hundred-MB model
 * weights to CoreML/ONNX and writing a custom on-device inference bridge,
 * which is a much larger undertaking than using Apple's first-party,
 * already-on-device Translation framework, and would still need to bundle
 * large model assets with the app. If a fully open-weights model is
 * required in the future, MarianMT (small, per-language-pair models) is
 * the more tractable starting point of the two.
 */
export class AppleTranslationEngine extends TranslationEngine {
  private sourceLanguage = "";
  private targetLanguage = "";

  async initialize(sourceLanguage: string, targetLanguage: string): Promise<void> {
    if (Platform.OS !== "ios") {
      throw new Error("AppleTranslationEngine requires iOS (Apple Translation framework is not available on this platform)");
    }

    this.sourceLanguage = sourceLanguage;
    this.targetLanguage = targetLanguage;

    const availability = await NativeOfflinePipeline.checkTranslationAvailability(sourceLanguage, targetLanguage);

    if (availability === "unsupported") {
      throw new Error(`Apple's Translation framework does not support ${sourceLanguage} -> ${targetLanguage} on this device`);
    }

    if (availability === "supported") {
      // First use of this language pair: this presents Apple's own
      // download/consent UI once, then installs the on-device model.
      await NativeOfflinePipeline.prepareTranslationLanguages(sourceLanguage, targetLanguage);
    }
  }

  async translate(text: string): Promise<string> {
    if (!this.sourceLanguage || !this.targetLanguage) {
      throw new Error("AppleTranslationEngine.translate called before initialize()");
    }

    const trimmed = text.trim();
    if (!trimmed) {
      return "";
    }

    return NativeOfflinePipeline.translate(trimmed, this.sourceLanguage, this.targetLanguage);
  }

  async dispose(): Promise<void> {
    // Nothing to release: the native TranslationSession is owned and
    // cached inside the native module for reuse across segments.
  }
}

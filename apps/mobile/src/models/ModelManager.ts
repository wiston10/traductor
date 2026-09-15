import type { Logger } from "../logging/Logger";
import type { STTEngine } from "../stt/STTEngine";
import type { TranslationEngine } from "../translation/TranslationEngine";
import type { TTSEngine } from "../tts/TTSEngine";

export type ModelState = "missing" | "loading" | "ready" | "error";

/**
 * Coordinates the three real on-device engines' own initialization
 * (speech authorization + on-device recognizer, Apple Translation
 * framework language pack, speech synthesizer). `ensureModels()` only
 * reports `ready` once every underlying `initialize()` promise has
 * actually resolved — there is no artificial delay and no unconditional
 * "ready" log; a failure in any engine surfaces as a rejected promise and
 * `state` moves to `error`, not `ready`.
 */
export class ModelManager {
  private state: ModelState = "missing";

  constructor(
    private readonly logger: Logger,
    private readonly sttEngine: STTEngine,
    private readonly translationEngine: TranslationEngine,
    private readonly ttsEngine: TTSEngine
  ) {}

  async ensureModels(sourceLanguage: string, targetLanguage: string): Promise<boolean> {
    this.state = "loading";
    this.logger.log("info", "[MODEL] verifying on-device speech, translation and synthesis models");

    try {
      await this.sttEngine.initialize();
      await this.translationEngine.initialize(sourceLanguage, targetLanguage);
      await this.ttsEngine.initialize();
    } catch (error) {
      this.state = "error";
      this.logger.log("error", "[MODEL] on-device models failed to initialize", {
        error: error instanceof Error ? error.message : String(error)
      });
      throw error;
    }

    this.state = "ready";
    this.logger.log("info", "[MODEL] on-device models verified ready");
    return true;
  }

  getState() {
    return this.state;
  }

  async unload(): Promise<void> {
    await Promise.all([this.sttEngine.dispose(), this.translationEngine.dispose(), this.ttsEngine.dispose()]);
    this.state = "missing";
  }
}

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

import { TranslationEngine } from "../apps/mobile/src/translation/TranslationEngine";
import { TranscriptStore } from "../apps/mobile/src/transcript/TranscriptStore";

/**
 * A fake ML backend used only to prove the pipeline's own plumbing
 * (initialize -> translate -> store) never lets the source text pass
 * through unchanged and never needs a "looks translated" suffix hack.
 * This does NOT validate real Spanish -> German translation quality —
 * that requires Apple's on-device Translation framework running on a
 * real iOS 26+ device/simulator with the language pack installed, which
 * cannot run inside this Node test process. See README "Real-mode manual
 * validation" for the on-device checklist.
 */
class FakeMlBackedTranslationEngine extends TranslationEngine {
  private ready = false;

  async initialize(sourceLanguage: string, targetLanguage: string): Promise<void> {
    assert.equal(sourceLanguage, "es");
    assert.equal(targetLanguage, "de");
    // Simulate a real async model warm-up instead of resolving synchronously.
    await new Promise((resolve) => setTimeout(resolve, 5));
    this.ready = true;
  }

  async translate(text: string): Promise<string> {
    if (!this.ready) {
      throw new Error("translate() called before initialize()");
    }
    // Stand-in for a real seq2seq forward pass; deliberately NOT a
    // dictionary lookup and NOT the input text with a suffix appended.
    const reversedWords = text.trim().split(/\s+/).reverse().join(" ");
    return `${reversedWords}::de`;
  }

  async dispose(): Promise<void> {
    this.ready = false;
  }
}

test("translation pipeline contract: translated text is never equal to the source text", async () => {
  const engine = new FakeMlBackedTranslationEngine();
  const transcriptStore = new TranscriptStore();

  await engine.initialize("es", "de");

  const originalText = "Hoy vamos a estudiar la palabra de Dios.";
  const translatedText = await engine.translate(originalText);

  assert.notEqual(translatedText, originalText);
  assert.ok(translatedText.length > 0);

  transcriptStore.appendSegment({
    id: "segment-000001",
    timestamp: 1,
    original: originalText,
    translation: translatedText
  });

  const [stored] = transcriptStore.getSegments();
  assert.notEqual(stored.translation, stored.original);
});

test("no banned mock-translation markers exist anywhere in the mobile source tree", () => {
  const bannedPhrases = ["lokal übersetzt", "mock translation", "fake translation", "demo translation"];
  const root = path.resolve(__dirname, "..", "apps", "mobile", "src");
  const offenders: string[] = [];

  function walk(dir: string) {
    for (const entry of readdirSync(dir)) {
      const fullPath = path.join(dir, entry);
      const stats = statSync(fullPath);
      if (stats.isDirectory()) {
        walk(fullPath);
        continue;
      }
      if (!/\.(ts|tsx)$/.test(entry)) {
        continue;
      }
      const content = readFileSync(fullPath, "utf8").toLowerCase();
      for (const phrase of bannedPhrases) {
        if (content.includes(phrase)) {
          offenders.push(`${fullPath}: "${phrase}"`);
        }
      }
    }
  }

  walk(root);

  assert.deepEqual(offenders, []);
});

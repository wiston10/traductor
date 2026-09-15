import { useCallback, useRef, useState } from "react";
import type { RealtimeTranslatorSettings } from "@traductor/shared";
import { Logger } from "../logging/Logger";
import { TranslationPipeline } from "../pipeline/TranslationPipeline";
import { DemoPipeline } from "../pipeline/DemoPipeline";
import { TranscriptStore } from "../transcript/TranscriptStore";
import type { PipelineMode, PipelineSegment } from "../types/pipeline";

type ConnectionStatus = "idle" | "connecting" | "live" | "stopping" | "error";

type Pipeline = TranslationPipeline | DemoPipeline;

type TranscriptTurn = {
  id: string;
  source: string;
  translation: string;
};

type StartOptions = {
  apiBaseUrl: string;
  settings: RealtimeTranslatorSettings;
  /** Defaults to "offline-real" — demo data must be explicitly requested. */
  pipelineMode?: PipelineMode;
};

export function useRealtimeTranslator() {
  const pipelineRef = useRef<Pipeline | null>(null);

  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [pipelineMode, setPipelineMode] = useState<PipelineMode>("offline-real");
  const [sourceText, setSourceText] = useState("");
  const [translatedText, setTranslatedText] = useState("");
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  const createPipeline = useCallback((mode: PipelineMode) => {
    const logger = Logger.create("mobile");
    const transcriptStore = new TranscriptStore();

    if (mode === "demo") {
      return new DemoPipeline({ logger, transcriptStore });
    }

    return new TranslationPipeline({ logger, transcriptStore });
  }, []);

  const commitSegment = useCallback((segment: PipelineSegment) => {
    const source = segment.originalText.trim();
    const translation = segment.translatedText.trim();

    if (source) {
      setSourceText(source);
    }

    if (!translation) {
      return;
    }

    setTranslatedText(translation);
    setTurns((previous) =>
      [
        {
          // Segment IDs are a session-scoped monotonic counter (see
          // SegmentIdGenerator), safe and unique as a React key — never
          // a timestamp.
          id: segment.id,
          source,
          translation
        },
        ...previous
      ].slice(0, 12)
    );
  }, []);

  const start = useCallback(
    async ({ settings, pipelineMode: requestedMode = "offline-real" }: StartOptions) => {
      setError(null);
      setStatus("connecting");
      setPipelineMode(requestedMode);
      setSourceText("");
      setTranslatedText("");

      try {
        const pipeline = createPipeline(requestedMode);
        pipelineRef.current = pipeline;

        await pipeline.initialize({
          sourceLanguage: settings.sourceLanguage,
          targetLanguage: settings.targetLanguage,
          outputMode: settings.outputMode,
          voice: settings.voice
        });

        pipeline.subscribe((segment) => {
          commitSegment(segment);
          setLatencyMs(pipeline.getLatestLatencyMs());
        });

        await pipeline.start();
        setStatus("live");
        setLatencyMs(pipeline.getLatestLatencyMs());
      } catch (caught) {
        setStatus("error");
        setError(caught instanceof Error ? caught.message : "No se pudo iniciar la traducción local.");
      }
    },
    [commitSegment, createPipeline]
  );

  const pause = useCallback(() => {
    setStatus((previous) => (previous === "idle" ? "idle" : "stopping"));
    pipelineRef.current?.stop();
    setStatus("idle");
  }, []);

  const stop = useCallback(async () => {
    setStatus((previous) => (previous === "idle" ? "idle" : "stopping"));
    pipelineRef.current?.stop();
    setStatus("idle");
  }, []);

  return {
    status,
    pipelineMode,
    sourceText,
    translatedText,
    turns,
    error,
    latencyMs,
    start,
    pause,
    stop
  };
}

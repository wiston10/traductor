import type { RuntimeConfig, RealtimeRequestOptions } from "./config.js";

export type OfflineSessionConfig = {
  mode: "offline";
  sourceLanguage: RealtimeRequestOptions["sourceLanguage"];
  targetLanguage: RealtimeRequestOptions["targetLanguage"];
  outputMode: RealtimeRequestOptions["outputMode"];
  voice: RealtimeRequestOptions["voice"];
  sttModelPath: string;
  translationModelPath: string;
  ttsModelPath: string;
};

export function buildRealtimeSessionConfig(config: RuntimeConfig, options: RealtimeRequestOptions): OfflineSessionConfig {
  return {
    mode: "offline",
    sourceLanguage: options.sourceLanguage,
    targetLanguage: options.targetLanguage,
    outputMode: options.outputMode,
    voice: options.voice,
    sttModelPath: config.sttModelPath,
    translationModelPath: config.translationModelPath,
    ttsModelPath: config.ttsModelPath
  };
}

export async function createRealtimeCallAnswer(_sdpOffer: string, config: RuntimeConfig, options: RealtimeRequestOptions) {
  return JSON.stringify(buildRealtimeSessionConfig(config, options));
}

export async function createClientSecret(config: RuntimeConfig, options: RealtimeRequestOptions) {
  return buildRealtimeSessionConfig(config, options);
}

export class OfflinePipelineError extends Error {
  constructor(
    readonly statusCode: number,
    readonly responseBody: string
  ) {
    super(`Offline pipeline request failed with ${statusCode}`);
  }
}

import "dotenv/config";

import cors from "@fastify/cors";
import Fastify from "fastify";
import { languageOptions, targetLanguageOptions, voiceOptions } from "@traductor/shared";
import { loadConfig, parseRealtimeHeaders } from "./config.js";
import { createClientSecret, createRealtimeCallAnswer, OfflinePipelineError } from "./offlinePipeline.js";

const config = loadConfig();
const app = Fastify({
  logger: true,
  bodyLimit: 1024 * 1024
});

app.register(cors, {
  origin: true,
  methods: ["GET", "POST", "OPTIONS"],
  allowedHeaders: ["Content-Type", "X-Source-Language", "X-Target-Language", "X-Output-Mode", "X-Voice"]
});

app.get("/health", async () => ({
  ok: true,
  service: "traductor-local-api",
  offlineMode: config.offlineMode,
  sttModelPath: config.sttModelPath,
  translationModelPath: config.translationModelPath,
  ttsModelPath: config.ttsModelPath
}));

app.get("/v1/config", async () => ({
  languages: languageOptions,
  targetLanguages: targetLanguageOptions,
  voices: voiceOptions,
  defaults: {
    sourceLanguage: "es",
    targetLanguage: "de",
    outputMode: "audio",
    voice: "marin"
  },
  offline: true
}));

app.post("/v1/realtime/sdp", async (request, reply) => {
  const sdpOffer = typeof request.body === "string" ? request.body : "";

  if (!sdpOffer.includes("v=0")) {
    return reply.status(400).send({
      error: "invalid_sdp_offer",
      message: "Request body must be a valid SDP payload. In offline mode this is only a compatibility stub."
    });
  }

  try {
    const answer = await createRealtimeCallAnswer(sdpOffer, config, parseRealtimeHeaders(request.headers));
    return reply.type("application/json").send({ status: "offline-ready", session: JSON.parse(answer) });
  } catch (error) {
    request.log.error(error);

    if (error instanceof OfflinePipelineError) {
      return reply.status(error.statusCode).send({
        error: "offline_pipeline_error",
        detail: safeErrorDetail(error.responseBody)
      });
    }

    return reply.status(500).send({ error: "realtime_session_failed" });
  }
});

app.post("/v1/realtime/client-secret", async (request, reply) => {
  try {
    const body = (request.body ?? {}) as Record<string, string | undefined>;
    const secret = await createClientSecret(config, {
      sourceLanguage: (body.sourceLanguage as never) ?? "es",
      targetLanguage: (body.targetLanguage as never) ?? "de",
      outputMode: (body.outputMode as never) ?? "audio",
      voice: (body.voice as never) ?? "marin"
    });

    return reply.send({
      status: "offline-ready",
      session: secret
    });
  } catch (error) {
    request.log.error(error);

    if (error instanceof OfflinePipelineError) {
      return reply.status(error.statusCode).send({
        error: "offline_pipeline_error",
        detail: safeErrorDetail(error.responseBody)
      });
    }

    return reply.status(500).send({ error: "client_secret_failed" });
  }
});

app.listen({ host: config.host, port: config.port }).catch((error) => {
  app.log.error(error);
  process.exit(1);
});

function safeErrorDetail(detail: string) {
  if (detail.length <= 1200) {
    return detail;
  }

  return `${detail.slice(0, 1200)}...`;
}

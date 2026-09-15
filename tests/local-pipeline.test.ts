import assert from "node:assert/strict";
import { test } from "node:test";

import { VAD } from "../apps/mobile/src/audio/VAD";
import { SpeechStateMachine } from "../apps/mobile/src/audio/SpeechStateMachine";
import { PipelineQueue } from "../apps/mobile/src/pipeline/PipelineQueue";
import { BackpressureManager } from "../apps/mobile/src/pipeline/BackpressureManager";
import { SegmentIdGenerator } from "../apps/mobile/src/pipeline/SegmentIdGenerator";
import { TranscriptStore } from "../apps/mobile/src/transcript/TranscriptStore";
import { PerformanceTimeline } from "../apps/mobile/src/performance/PerformanceTimeline";
import { monotonicNowMs } from "../apps/mobile/src/performance/MonotonicClock";

test("VAD detects speech start and end", () => {
  const vad = new VAD({ threshold: 0.3, silenceTimeoutMs: 2, minimumSpeechMs: 1, preRollMs: 0, postRollMs: 0 });

  assert.equal(vad.processChunk(0.45), "speech_start");
  assert.equal(vad.processChunk(0.5), "speech_continue");
  assert.equal(vad.processChunk(0.1), "silence");
  assert.equal(vad.processChunk(0.1), "speech_end");
});

test("SegmentIdGenerator produces zero-padded monotonic ids, never timestamps", () => {
  const generator = new SegmentIdGenerator();
  assert.equal(generator.next(), "segment-000001");
  assert.equal(generator.next(), "segment-000002");
  assert.equal(generator.next(), "segment-000003");
  assert.equal(generator.peekCount(), 3);
});

test("SpeechStateMachine never emits duplicate SPEECH_START for the same utterance", () => {
  const generator = new SegmentIdGenerator();
  const machine = new SpeechStateMachine(new VAD({ threshold: 0.3, silenceTimeoutMs: 2, minimumSpeechMs: 1, preRollMs: 0, postRollMs: 0 }), () =>
    generator.next()
  );

  const first = machine.processSample(0.9); // speech_start -> SPEECH_START
  assert.equal(first.state, "SPEECH_START");
  assert.equal(first.segmentId, "segment-000001");

  // Repeated above-threshold samples must not re-enter SPEECH_START.
  const second = machine.processSample(0.9); // speech_continue -> SPEAKING
  assert.equal(second.state, "SPEAKING");
  assert.equal(second.segmentId, "segment-000001");

  const third = machine.processSample(0.9); // still speaking, same segment
  assert.equal(third.state, "SPEAKING");
  assert.equal(third.segmentId, "segment-000001");

  const silence = machine.processSample(0.05); // below threshold -> silence
  assert.equal(silence.state, "SPEAKING");

  const ended = machine.processSample(0.05); // silence timeout reached -> speech_end
  assert.equal(ended.state, "SPEECH_END");

  const begun = machine.beginProcessing();
  assert.equal(begun.state, "PROCESSING");
  const completed = machine.completeProcessing();
  assert.equal(completed.state, "IDLE");
  assert.equal(completed.segmentId, null);

  // A brand-new utterance now gets a new segment id and a fresh SPEECH_START.
  const next = machine.processSample(0.9);
  assert.equal(next.state, "SPEECH_START");
  assert.equal(next.segmentId, "segment-000002");
});

test("PipelineQueue never drops on push and reports real per-item wait (queue lag)", () => {
  const queue = new PipelineQueue<number>(3);
  queue.push(10);
  queue.push(20);
  queue.push(30);
  queue.push(40); // exceeds softLimit of 3, but must NOT be dropped

  assert.deepEqual(queue.values(), [10, 20, 30, 40]);
  assert.equal(queue.size, 4);
  assert.ok(queue.isOverSoftLimit());

  const dequeued = queue.shiftWithLag();
  assert.ok(dequeued);
  assert.equal(dequeued?.item, 10);
  assert.ok((dequeued?.lagMs ?? -1) >= 0);

  assert.deepEqual(queue.values(), [20, 30, 40]);
});

test("PipelineQueue.dropOldest only drops when the user has explicitly enabled recovery", () => {
  const queue = new PipelineQueue<number>(1);
  queue.push(1);
  queue.push(2);

  assert.equal(queue.dropOldest(false), undefined);
  assert.deepEqual(queue.values(), [1, 2]);

  assert.equal(queue.dropOldest(true), 1);
  assert.deepEqual(queue.values(), [2]);
});

test("BackpressureManager never drops and instead shrinks segment size + warns", () => {
  const manager = new BackpressureManager({ maxAudioQueue: 1, maxTranslationQueue: 1, maxTtsQueue: 1, minSegmentDurationMs: 1000, maxSegmentDurationMs: 4000 });

  // shouldDrop is deprecated and must always report false now.
  assert.equal(manager.shouldDrop(), false);

  const healthy = manager.assess({ audioQueueSize: 0, translationQueueSize: 0, ttsQueueSize: 0 });
  assert.equal(healthy.underPressure, false);
  assert.equal(healthy.warning, null);

  const underPressure = manager.assess({ audioQueueSize: 1, translationQueueSize: 0, ttsQueueSize: 0 });
  assert.equal(underPressure.underPressure, true);
  assert.ok(underPressure.warning);
  assert.ok(underPressure.recommendedSegmentDurationMs < 4000);
  assert.ok(underPressure.recommendedSegmentDurationMs >= 1000);
});

test("PerformanceTimeline only returns durations for present, correctly ordered marks", () => {
  const timeline = new PerformanceTimeline();

  timeline.mark("speechStart");
  timeline.mark("chunkReady");
  timeline.mark("sttFinal");
  timeline.mark("translationStart");
  timeline.mark("translationComplete");
  timeline.mark("ttsStart");
  timeline.mark("firstAudio");

  const metrics = timeline.metrics();

  assert.ok(metrics.sttLatencyMs !== null && metrics.sttLatencyMs >= 0);
  assert.ok(metrics.translationLatencyMs !== null && metrics.translationLatencyMs >= 0);
  assert.ok(metrics.ttsLatencyMs !== null && metrics.ttsLatencyMs >= 0);
  assert.ok(metrics.endToEndLatencyMs !== null && metrics.endToEndLatencyMs >= 0);
});

test("PerformanceTimeline returns null instead of a fabricated number for missing marks", () => {
  const timeline = new PerformanceTimeline();
  timeline.mark("speechStart");
  // firstAudio never marked (e.g. TTS failed) — must be null, not -something.

  const metrics = timeline.metrics();
  assert.equal(metrics.endToEndLatencyMs, null);
  assert.equal(metrics.ttsLatencyMs, null);
  assert.equal(metrics.translationLatencyMs, null);
  assert.equal(metrics.sttLatencyMs, null);
});

test("monotonicNowMs never decreases across successive calls", () => {
  const samples = Array.from({ length: 20 }, () => monotonicNowMs());
  for (let i = 1; i < samples.length; i += 1) {
    assert.ok(samples[i] >= samples[i - 1], "monotonic clock must never go backwards");
  }
});

test("TranscriptStore appends and exports transcript", () => {
  const store = new TranscriptStore();
  store.appendSegment({ id: "segment-000001", timestamp: 1234, original: "Hoy vamos a estudiar", translation: "Heute werden wir studieren" });
  store.appendSegment({ id: "segment-000002", timestamp: 2234, original: "Gracias por escuchar", translation: "Danke für das Zuhören" });

  const json = store.exportTranscript("json");
  assert.match(json, /"original": "Hoy vamos a estudiar"/);
  assert.equal(store.getSegments().length, 2);

  const txt = store.exportTranscript("txt");
  assert.match(txt, /Gracias por escuchar/);
});

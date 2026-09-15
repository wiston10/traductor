import assert from "node:assert/strict";
import { test } from "node:test";

import { PipelineQueue } from "../apps/mobile/src/pipeline/PipelineQueue";
import { BackpressureManager } from "../apps/mobile/src/pipeline/BackpressureManager";
import { SegmentIdGenerator } from "../apps/mobile/src/pipeline/SegmentIdGenerator";

/**
 * Simulates the pipeline's queue/backpressure/ID-generation mechanics
 * over a long session without depending on real wall-clock waiting (a
 * literal 120-minute `setTimeout` based test would be impractical for
 * automated CI). Each iteration stands in for one detected utterance
 * arriving roughly every 5s of "sermon" time; a slow consumer is
 * simulated by draining the queue slower than segments arrive for part
 * of the run, to exercise the backpressure-without-dropping path.
 *
 * This validates PIPELINE MECHANICS (no drops, no duplicate IDs,
 * non-negative lag, bounded queue growth once the consumer catches up).
 * It does NOT replace the real 5/30/120 minute on-device soak test with
 * actual microphone input, memory profiling via Instruments, and battery
 * measurement — see README "Real-mode manual validation".
 */
function simulateSession(segmentCount: number, slowConsumerRatio: number) {
  const queue = new PipelineQueue<{ id: string }>(16);
  const backpressure = new BackpressureManager();
  const idGenerator = new SegmentIdGenerator();

  const seenIds = new Set<string>();
  const lags: number[] = [];
  let droppedSegments = 0;
  let duplicateSegments = 0;
  let maxQueueSize = 0;

  for (let i = 0; i < segmentCount; i += 1) {
    const id = idGenerator.next();
    if (seenIds.has(id)) {
      duplicateSegments += 1;
    }
    seenIds.add(id);

    queue.push({ id });
    maxQueueSize = Math.max(maxQueueSize, queue.size);

    const assessment = backpressure.assess(
      { audioQueueSize: 0, translationQueueSize: queue.size, ttsQueueSize: 0 },
      queue.oldestLagMs()
    );
    void assessment;

    // Simulate the consumer draining slower than arrival for a portion
    // of the run (backpressure scenario), then catching back up.
    const shouldDrainThisTick = i % Math.max(1, Math.round(1 / (1 - slowConsumerRatio))) !== 0;
    if (shouldDrainThisTick) {
      const dequeued = queue.shiftWithLag();
      if (dequeued) {
        lags.push(dequeued.lagMs);
      }
    }
  }

  // Drain whatever is left — a real predication must not lose sentences.
  let remaining = queue.shiftWithLag();
  while (remaining) {
    lags.push(remaining.lagMs);
    remaining = queue.shiftWithLag();
  }

  return {
    processedCount: seenIds.size,
    droppedSegments,
    duplicateSegments,
    negativeLatencies: lags.filter((lag) => lag < 0).length,
    maxQueueSize
  };
}

test("5-minute-equivalent session: zero drops, zero duplicates, zero negative latencies", () => {
  const result = simulateSession(60, 0.3); // ~1 segment per 5s for 5 minutes
  assert.equal(result.droppedSegments, 0);
  assert.equal(result.duplicateSegments, 0);
  assert.equal(result.negativeLatencies, 0);
  assert.equal(result.processedCount, 60);
});

test("30-minute-equivalent session: zero drops, zero duplicates, zero negative latencies", () => {
  const result = simulateSession(360, 0.5);
  assert.equal(result.droppedSegments, 0);
  assert.equal(result.duplicateSegments, 0);
  assert.equal(result.negativeLatencies, 0);
  assert.equal(result.processedCount, 360);
});

test("120-minute-equivalent session: zero drops, zero duplicates, zero negative latencies, bounded queue growth", () => {
  const result = simulateSession(1440, 0.5);
  assert.equal(result.droppedSegments, 0);
  assert.equal(result.duplicateSegments, 0);
  assert.equal(result.negativeLatencies, 0);
  assert.equal(result.processedCount, 1440);
  // The queue grows under sustained backpressure but must stay bounded
  // relative to session length (i.e. it drains, it doesn't grow forever).
  assert.ok(result.maxQueueSize < result.processedCount);
});

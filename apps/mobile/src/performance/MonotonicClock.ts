/**
 * Monotonic time source.
 *
 * `Date.now()` reads the wall clock, which can jump backwards or forwards
 * (NTP sync, manual clock changes, timezone updates). That is what produced
 * invalid negative latencies in this project. `performance.now()` in
 * React Native/Hermes is backed by a monotonic, high-resolution timer
 * (never the wall clock), so elapsed-time subtraction is always >= 0 as
 * long as the "end" mark was captured after the "start" mark.
 *
 * Never use Date.now() to measure a duration. Use `monotonicNowMs()`.
 */
export function monotonicNowMs(): number {
  const perf = (globalThis as { performance?: { now(): number } }).performance;

  if (perf && typeof perf.now === "function") {
    return perf.now();
  }

  // Fallback for environments without a `performance` global (should not
  // happen on Hermes/RN or Node >= 16, but guarded defensively). This still
  // avoids Date.now() by using the hrtime monotonic clock when present.
  const nodeProcess = (globalThis as { process?: { hrtime?: { bigint(): bigint } } }).process;
  if (nodeProcess?.hrtime?.bigint) {
    return Number(nodeProcess.hrtime.bigint()) / 1_000_000;
  }

  throw new Error("No monotonic clock source available on this runtime");
}

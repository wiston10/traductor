import { monotonicNowMs } from "../performance/MonotonicClock";

type QueueEntry<T> = {
  item: T;
  enqueuedAt: number;
};

/**
 * FIFO queue used by the pipeline stages (audio -> translation -> tts).
 *
 * Unlike the previous implementation, this queue NEVER silently drops the
 * oldest item when it grows past its soft limit. A sermon/predication must
 * not lose sentences silently. Growth past the soft limit is only ever
 * reported (via `isOverSoftLimit()` / `size`) so a `BackpressureManager`
 * can react (e.g. shrink future segment size, surface a warning). Actual
 * dropping only happens if `dropOldest()` is called explicitly by a caller
 * that has confirmed the user opted into an explicit recovery policy.
 */
export class PipelineQueue<T> {
  private readonly items: QueueEntry<T>[] = [];

  constructor(private readonly softLimit = 32) {}

  push(item: T): T {
    this.items.push({ item, enqueuedAt: monotonicNowMs() });
    return item;
  }

  shift(): T | undefined {
    return this.items.shift()?.item;
  }

  /** Removes and returns the oldest item along with how long it waited (ms). */
  shiftWithLag(): { item: T; lagMs: number } | undefined {
    const entry = this.items.shift();
    if (!entry) {
      return undefined;
    }
    return { item: entry.item, lagMs: Math.max(0, monotonicNowMs() - entry.enqueuedAt) };
  }

  /**
   * Explicit, opt-in recovery action: drops the oldest queued item.
   * Must only be invoked when the caller has verified the user enabled an
   * explicit recovery policy — never as a default backpressure response.
   */
  dropOldest(userEnabledRecoveryPolicy: boolean): T | undefined {
    if (!userEnabledRecoveryPolicy) {
      return undefined;
    }
    return this.items.shift()?.item;
  }

  /** How long (ms) the oldest still-queued item has been waiting. */
  oldestLagMs(): number | null {
    const oldest = this.items[0];
    if (!oldest) {
      return null;
    }
    return Math.max(0, monotonicNowMs() - oldest.enqueuedAt);
  }

  clear() {
    this.items.length = 0;
  }

  get size() {
    return this.items.length;
  }

  isOverSoftLimit() {
    return this.items.length >= this.softLimit;
  }

  values() {
    return this.items.map((entry) => entry.item);
  }
}

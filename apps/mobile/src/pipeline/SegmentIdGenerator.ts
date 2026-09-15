/**
 * Session-scoped monotonic ID generator for pipeline segments.
 *
 * Segment IDs must never be derived from timestamps (they collide when
 * multiple segments are created within the same millisecond, and they are
 * unsuitable as React keys because they are not guaranteed unique or
 * ordered under clock adjustments). A simple incrementing counter is
 * unique for the lifetime of the process and stable to use as a React key.
 */
export class SegmentIdGenerator {
  private counter = 0;

  next(): string {
    this.counter += 1;
    return `segment-${String(this.counter).padStart(6, "0")}`;
  }

  peekCount(): number {
    return this.counter;
  }

  reset() {
    this.counter = 0;
  }
}

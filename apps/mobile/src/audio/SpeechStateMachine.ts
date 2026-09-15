import type { VAD, VADEvent } from "./VAD";

export type SpeechState = "IDLE" | "SPEECH_START" | "SPEAKING" | "SPEECH_END" | "PROCESSING";

export type SpeechStateTransition = {
  state: SpeechState;
  previousState: SpeechState;
  /** Non-null only while a single utterance/segment is in flight. */
  segmentId: string | null;
  changed: boolean;
};

/**
 * Wraps low-level VAD sample events into an explicit state machine so a
 * single utterance can never emit `SPEECH_START` more than once. The VAD
 * itself only tells us "speech_start / speech_continue / silence /
 * speech_end" per audio chunk; without an explicit machine on top, a
 * caller processing chunk-by-chunk can easily re-emit `speech_start`
 * events (e.g. once per queued chunk) for what is really the same
 * utterance. This class is the single source of truth for "are we
 * currently inside an utterance" and only allows the legal transitions:
 *
 *   IDLE -> SPEECH_START -> SPEAKING -> SPEECH_END -> PROCESSING -> IDLE
 *
 * `SPEECH_START` cannot be re-entered for the same segment until the
 * machine has returned to `IDLE` (i.e. the previous segment finished
 * `PROCESSING`).
 */
export class SpeechStateMachine {
  private state: SpeechState = "IDLE";
  private activeSegmentId: string | null = null;

  constructor(
    private readonly vad: VAD | null,
    private readonly nextSegmentId: () => string
  ) {}

  getState(): SpeechState {
    return this.state;
  }

  getActiveSegmentId(): string | null {
    return this.activeSegmentId;
  }

  /** Feed one audio-energy sample (RMS) into the machine (used when a local VAD drives detection). */
  processSample(rms: number): SpeechStateTransition {
    if (!this.vad) {
      throw new Error("SpeechStateMachine has no VAD configured; use applyExternalEvent instead");
    }
    const event = this.vad.processChunk(rms);
    return this.applyVadEvent(event);
  }

  /**
   * Feed a high-level speech boundary event reported directly by a real
   * upstream detector (e.g. Apple's `SFSpeechRecognizer`, which does its
   * own endpointing) instead of raw energy samples.
   */
  applyExternalEvent(event: VADEvent): SpeechStateTransition {
    return this.applyVadEvent(event);
  }

  private applyVadEvent(event: VADEvent): SpeechStateTransition {
    const previousState = this.state;

    switch (event) {
      case "speech_start": {
        if (this.state === "IDLE") {
          this.activeSegmentId = this.nextSegmentId();
          this.state = "SPEECH_START";
        }
        // If we are not IDLE, this is a duplicate speech_start for an
        // utterance already in progress: ignored, not re-emitted.
        break;
      }
      case "speech_continue": {
        if (this.state === "SPEECH_START" || this.state === "SPEAKING") {
          this.state = "SPEAKING";
        }
        break;
      }
      case "speech_end": {
        if (this.state === "SPEECH_START" || this.state === "SPEAKING") {
          this.state = "SPEECH_END";
        }
        break;
      }
      case "silence": {
        // No active utterance; nothing to transition.
        break;
      }
    }

    return {
      state: this.state,
      previousState,
      segmentId: this.activeSegmentId,
      changed: this.state !== previousState
    };
  }

  /**
   * Call once the ended segment has been handed off to the processing
   * queues. This only marks the capture-side handoff — it does not wait
   * for STT/translation/TTS to finish. Follow immediately with
   * `completeProcessing()` so the machine returns to `IDLE` and capture
   * can keep listening for the next utterance while the dispatched
   * segment is processed concurrently in the pipeline queues (capture
   * must never be blocked/paused while downstream stages work).
   */
  beginProcessing(): SpeechStateTransition {
    const previousState = this.state;

    if (this.state === "SPEECH_END") {
      this.state = "PROCESSING";
    }

    return {
      state: this.state,
      previousState,
      segmentId: this.activeSegmentId,
      changed: this.state !== previousState
    };
  }

  /**
   * Releases the capture-side machine back to `IDLE` immediately after
   * `beginProcessing()`, so the next utterance can be detected while this
   * segment's STT/translation/TTS continue asynchronously in the queues.
   */
  completeProcessing(): SpeechStateTransition {
    const previousState = this.state;

    if (this.state === "PROCESSING") {
      this.state = "IDLE";
      this.activeSegmentId = null;
    }

    return {
      state: this.state,
      previousState,
      segmentId: this.activeSegmentId,
      changed: this.state !== previousState
    };
  }

  reset() {
    this.state = "IDLE";
    this.activeSegmentId = null;
  }
}

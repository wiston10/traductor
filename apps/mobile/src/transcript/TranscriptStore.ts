import type { TranscriptEntry } from "../types/transcript";

export class TranscriptStore {
  private readonly segments: TranscriptEntry[] = [];

  appendSegment(segment: TranscriptEntry) {
    this.segments.push(segment);
    return segment;
  }

  updateSegment(id: string, patch: Partial<TranscriptEntry>) {
    const index = this.segments.findIndex((segment) => segment.id === id);

    if (index === -1) {
      return null;
    }

    this.segments[index] = { ...this.segments[index], ...patch };
    return this.segments[index];
  }

  getSegments() {
    return [...this.segments];
  }

  exportTranscript(format: "txt" | "json" | "srt" = "json") {
    if (format === "txt") {
      return this.segments.map((segment) => `${segment.original}\n${segment.translation}`).join("\n\n");
    }

    if (format === "srt") {
      return this.segments
        .map((segment, index) => {
          const start = formatSeconds(segment.timestamp / 1000);
          const end = formatSeconds((segment.timestamp + 3000) / 1000);
          return `${index + 1}\n${start} --> ${end}\n${segment.translation}\n`;
        })
        .join("\n");
    }

    return JSON.stringify(this.segments, null, 2);
  }

  clearTranscript() {
    this.segments.length = 0;
  }
}

function formatSeconds(totalSeconds: number) {
  const seconds = Math.floor(totalSeconds);
  const milliseconds = Math.round((totalSeconds - seconds) * 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;

  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")},${String(milliseconds).padStart(3, "0")}`;
}

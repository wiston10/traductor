import { TranscriptStore } from "./TranscriptStore";

export class TranscriptExporter {
  constructor(private readonly store: TranscriptStore) {}

  exportText() {
    return this.store.exportTranscript("txt");
  }

  exportJson() {
    return this.store.exportTranscript("json");
  }

  exportSrt() {
    return this.store.exportTranscript("srt");
  }
}

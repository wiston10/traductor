import Foundation
import AVFoundation

/// Real on-device speech synthesis via `AVSpeechSynthesizer`. `firstAudio`
/// is only reported once the delegate confirms audio playback actually
/// started (`didStart`), never on a timer or artificial delay.
final class SpeechSynthesisManager: NSObject, AVSpeechSynthesizerDelegate {
  enum SynthesisEvent {
    case ttsStart
    case firstAudio
    case finished
    case error(String)
  }

  private let synthesizer = AVSpeechSynthesizer()
  var onEvent: ((SynthesisEvent) -> Void)?

  override init() {
    super.init()
    synthesizer.delegate = self
  }

  func speak(text: String, languageIdentifier: String) {
    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else {
      onEvent?(.error("Cannot synthesize empty text"))
      return
    }

    let utterance = AVSpeechUtterance(string: trimmed)
    utterance.voice = AVSpeechSynthesisVoice(language: languageIdentifier)

    onEvent?(.ttsStart)
    synthesizer.speak(utterance)
  }

  func stop() {
    synthesizer.stopSpeaking(at: .immediate)
  }

  func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
    // This delegate callback fires when the audio engine actually begins
    // rendering audio for the utterance — the real first-audio moment.
    onEvent?(.firstAudio)
  }

  func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
    onEvent?(.finished)
  }

  func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
    onEvent?(.finished)
  }
}

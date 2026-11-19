import Foundation
import Speech
import AVFoundation

/// Real on-device streaming speech recognition using `SFSpeechRecognizer`
/// with `requiresOnDeviceRecognition = true`. No network call, no canned
/// text — the recognizer is fed live PCM buffers captured from the
/// microphone via `AVAudioEngine`.
final class SpeechRecognitionManager: NSObject, SFSpeechRecognitionTaskDelegate {
  enum RecognitionEvent {
    case speechStart
    case partialTranscript(String)
    case finalTranscript(String)
    case speechEnd
    case error(String)
  }

  private var recognizer: SFSpeechRecognizer?
  private var request: SFSpeechAudioBufferRecognitionRequest?
  private var task: SFSpeechRecognitionTask?
  private let audioEngine = AVAudioEngine()
  private var hasEmittedSpeechStart = false

  var onEvent: ((RecognitionEvent) -> Void)?

  static func requestAuthorization() async -> Bool {
    await withCheckedContinuation { continuation in
      SFSpeechRecognizer.requestAuthorization { status in
        continuation.resume(returning: status == .authorized)
      }
    }
  }

  static func requestMicrophonePermission() async -> Bool {
    await withCheckedContinuation { continuation in
      AVAudioApplication.requestRecordPermission { granted in
        continuation.resume(returning: granted)
      }
    }
  }

  func supportsOnDeviceRecognition(localeIdentifier: String) -> Bool {
    guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeIdentifier)) else {
      return false
    }
    return recognizer.supportsOnDeviceRecognition
  }

  func start(localeIdentifier: String) throws {
    stop()

    guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeIdentifier)), recognizer.isAvailable else {
      throw NSError(domain: "OfflinePipeline", code: 1, userInfo: [NSLocalizedDescriptionKey: "Speech recognizer unavailable for locale \(localeIdentifier)"])
    }

    self.recognizer = recognizer
    hasEmittedSpeechStart = false

    let audioSession = AVAudioSession.sharedInstance()
    try audioSession.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
    try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

    let request = SFSpeechAudioBufferRecognitionRequest()
    request.shouldReportPartialResults = true
    // Require true on-device recognition — never silently fall back to a
    // server-based recognizer, which would violate the offline-only
    // requirement of this pipeline.
    request.requiresOnDeviceRecognition = true
    self.request = request

    let inputNode = audioEngine.inputNode
    let recordingFormat = inputNode.outputFormat(forBus: 0)

    inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, _ in
      guard let self else { return }
      self.request?.append(buffer)

      if !self.hasEmittedSpeechStart {
        self.hasEmittedSpeechStart = true
        self.onEvent?(.speechStart)
      }
    }

    audioEngine.prepare()
    try audioEngine.start()

    task = recognizer.recognitionTask(with: request) { [weak self] result, error in
      guard let self else { return }

      if let error {
        self.onEvent?(.error(error.localizedDescription))
        return
      }

      guard let result else { return }

      if result.isFinal {
        self.onEvent?(.finalTranscript(result.bestTranscription.formattedString))
        self.onEvent?(.speechEnd)
        self.hasEmittedSpeechStart = false
      } else {
        self.onEvent?(.partialTranscript(result.bestTranscription.formattedString))
      }
    }
  }

  func stop() {
    if audioEngine.isRunning {
      audioEngine.stop()
      audioEngine.inputNode.removeTap(onBus: 0)
    }
    request?.endAudio()
    task?.cancel()
    request = nil
    task = nil
  }
}

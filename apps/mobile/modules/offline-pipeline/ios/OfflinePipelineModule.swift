import ExpoModulesCore

public class OfflinePipelineModule: Module {
  private let speech = SpeechRecognitionManager()
  private let tts = SpeechSynthesisManager()
  private var translationManager: Any?

  public func definition() -> ModuleDefinition {
    Name("OfflinePipeline")

    Events(
      "onSpeechStart",
      "onPartialTranscript",
      "onFinalTranscript",
      "onSpeechEnd",
      "onSttError",
      "onTtsStart",
      "onFirstAudio",
      "onTtsFinished",
      "onTtsError"
    )

    OnCreate {
      self.speech.onEvent = { [weak self] event in
        guard let self else { return }
        switch event {
        case .speechStart:
          self.sendEvent("onSpeechStart", [:])
        case .partialTranscript(let text):
          self.sendEvent("onPartialTranscript", ["text": text])
        case .finalTranscript(let text):
          self.sendEvent("onFinalTranscript", ["text": text])
        case .speechEnd:
          self.sendEvent("onSpeechEnd", [:])
        case .error(let message):
          self.sendEvent("onSttError", ["message": message])
        }
      }

      self.tts.onEvent = { [weak self] event in
        guard let self else { return }
        switch event {
        case .ttsStart:
          self.sendEvent("onTtsStart", [:])
        case .firstAudio:
          self.sendEvent("onFirstAudio", [:])
        case .finished:
          self.sendEvent("onTtsFinished", [:])
        case .error(let message):
          self.sendEvent("onTtsError", ["message": message])
        }
      }
    }

    AsyncFunction("requestSpeechAuthorization") { () -> Bool in
      let speechGranted = await SpeechRecognitionManager.requestAuthorization()
      let micGranted = await SpeechRecognitionManager.requestMicrophonePermission()
      return speechGranted && micGranted
    }

    Function("supportsOnDeviceRecognition") { (localeIdentifier: String) -> Bool in
      self.speech.supportsOnDeviceRecognition(localeIdentifier: localeIdentifier)
    }

    Function("startRecognition") { (localeIdentifier: String) throws in
      try self.speech.start(localeIdentifier: localeIdentifier)
    }

    Function("stopRecognition") {
      self.speech.stop()
    }

    AsyncFunction("checkTranslationAvailability") { (from: String, to: String) -> String in
      guard #available(iOS 26.0, *) else {
        throw OfflinePipelineError.unsupportedOS
      }
      let manager = self.resolveTranslationManager()
      let status = await manager.checkAvailability(from: from, to: to)
      return status.rawValue
    }

    AsyncFunction("prepareTranslationLanguages") { (from: String, to: String) in
      guard #available(iOS 26.0, *) else {
        throw OfflinePipelineError.unsupportedOS
      }
      let manager = self.resolveTranslationManager()
      try await manager.prepareLanguages(from: from, to: to)
    }

    AsyncFunction("translate") { (text: String, from: String, to: String) -> String in
      guard #available(iOS 26.0, *) else {
        throw OfflinePipelineError.unsupportedOS
      }
      let manager = self.resolveTranslationManager()
      return try await manager.translate(text: text, from: from, to: to)
    }

    Function("speak") { (text: String, languageIdentifier: String) in
      self.tts.speak(text: text, languageIdentifier: languageIdentifier)
    }

    Function("stopSpeaking") {
      self.tts.stop()
    }

    OnDestroy {
      self.speech.stop()
      self.tts.stop()
    }
  }

  @available(iOS 26.0, *)
  private func resolveTranslationManager() -> TranslationManager {
    if let existing = translationManager as? TranslationManager {
      return existing
    }
    let manager = TranslationManager()
    translationManager = manager
    return manager
  }
}

enum OfflinePipelineError: Error, CustomStringConvertible {
  case unsupportedOS

  var description: String {
    switch self {
    case .unsupportedOS:
      return "Real on-device translation requires iOS 26 or later (Apple Translation framework)."
    }
  }
}

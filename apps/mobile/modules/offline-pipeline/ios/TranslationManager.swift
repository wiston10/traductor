import Foundation
import Translation
import SwiftUI
import UIKit

/// Real on-device machine translation via Apple's `Translation` framework
/// (`TranslationSession`). No dictionary lookups, no static strings, no
/// network calls — `session.translate(_:)` runs the actual on-device MT
/// model shipped by Apple for the requested language pair.
///
/// Apple only allows headless (non-SwiftUI) session creation
/// (`TranslationSession.init(installedSource:target:)`) once the language
/// pair has already been installed on the device. The very first time a
/// language pair is used, we must show Apple's own one-time consent/
/// download UI (`translationTask` + `prepareTranslation()`) so the user
/// explicitly approves downloading the on-device model. After that, all
/// translations happen fully offline with no further UI.
@available(iOS 26.0, *)
final class TranslationManager {
  enum AvailabilityStatus: String {
    case installed
    case supported
    case unsupported
  }

  private var session: TranslationSession?
  private var sessionSource: String?
  private var sessionTarget: String?

  func checkAvailability(from: String, to: String) async -> AvailabilityStatus {
    let availability = LanguageAvailability()
    let status = await availability.status(
      from: Locale.Language(identifier: from),
      to: Locale.Language(identifier: to)
    )

    switch status {
    case .installed:
      return .installed
    case .supported:
      return .supported
    case .unsupported:
      return .unsupported
    @unknown default:
      return .unsupported
    }
  }

  /// Presents Apple's translation download/consent UI so the on-device
  /// language pack gets installed. Must be awaited once per language pair
  /// before real-time `translate` calls will succeed offline.
  @MainActor
  func prepareLanguages(from: String, to: String) async throws {
    let host = PreparationHostController(from: from, to: to)
    guard let rootViewController = UIApplication.shared.connectedScenes
      .compactMap({ ($0 as? UIWindowScene)?.keyWindow })
      .first?.rootViewController
    else {
      throw NSError(domain: "OfflinePipeline", code: 3, userInfo: [NSLocalizedDescriptionKey: "No root view controller available to present language download UI"])
    }

    host.modalPresentationStyle = .overFullScreen
    host.view.backgroundColor = .clear
    rootViewController.present(host, animated: false)

    defer { host.dismiss(animated: false) }

    try await host.waitUntilPrepared()
  }

  func translate(text: String, from: String, to: String) async throws -> String {
    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else {
      return ""
    }

    let activeSession = try await resolveSession(from: from, to: to)
    let response = try await activeSession.translate(trimmed)
    return response.targetText
  }

  private func resolveSession(from: String, to: String) async throws -> TranslationSession {
    if let session, sessionSource == from, sessionTarget == to {
      return session
    }

    let newSession = try await TranslationSession(
      installedSource: Locale.Language(identifier: from),
      target: Locale.Language(identifier: to)
    )

    session = newSession
    sessionSource = from
    sessionTarget = to
    return newSession
  }
}

/// Minimal SwiftUI host used only to obtain a `TranslationSession` via the
/// `.translationTask` modifier and call `prepareTranslation()`, which is
/// the API Apple requires for the one-time on-device model download with
/// user consent. Invisible to the user (fully transparent, zero-size).
@available(iOS 26.0, *)
private final class PreparationHostController: UIHostingController<PreparationHostView> {
  private let continuationBox = ContinuationBox()

  init(from: String, to: String) {
    super.init(rootView: PreparationHostView(from: from, to: to, continuationBox: continuationBox))
  }

  @MainActor required dynamic init?(coder aDecoder: NSCoder) {
    fatalError("init(coder:) has not been implemented")
  }

  func waitUntilPrepared() async throws {
    try await withCheckedThrowingContinuation { continuation in
      continuationBox.continuation = continuation
    }
  }
}

private final class ContinuationBox {
  var continuation: CheckedContinuation<Void, Error>?
}

@available(iOS 26.0, *)
private struct PreparationHostView: View {
  let from: String
  let to: String
  let continuationBox: ContinuationBox

  var body: some View {
    Color.clear
      .translationTask(
        TranslationSession.Configuration(
          source: Locale.Language(identifier: from),
          target: Locale.Language(identifier: to)
        )
      ) { session in
        do {
          try await session.prepareTranslation()
          continuationBox.continuation?.resume()
        } catch {
          continuationBox.continuation?.resume(throwing: error)
        }
        continuationBox.continuation = nil
      }
  }
}

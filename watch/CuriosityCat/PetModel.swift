import Foundation
import SwiftUI
import WatchKit

enum CatState { case idle, listening, thinking, speaking }

/// The watch side of a turn: hold to record, release to upload, then play each sentence as it arrives.
@MainActor
final class PetModel: ObservableObject {
    @Published var state: CatState = .idle
    @Published var heard = ""
    @Published var sentences: [String] = []
    @Published var current: Int = -1
    @Published var message = ""
    @Published var isPaired: Bool

    private var client: PetClient
    private let recorder = Recorder()
    private let player = SpeechPlayer()
    private var turnTask: Task<Void, Never>?

    init() {
        let token = Keychain.load()
        client = PetClient.fromBundle(token: token)
        isPaired = token != nil
        player.onStart = { [weak self] id in Task { @MainActor in self?.current = id } }
        player.onIdle = { [weak self] in Task { @MainActor in self?.playbackFinished() } }
        #if DEBUG
        // Simulator testing: pair with a code from the launch environment. Not in release builds.
        if !isPaired, let code = ProcessInfo.processInfo.environment["PET_PAIR_CODE"] {
            Task { _ = await pair(code: code) }
        }
        // Simulator testing: "hold" the cat once after launch, as if the child asked the prepared recording
        if ProcessInfo.processInfo.environment["PET_DEMO_ASK"] != nil {
            Task {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                pressDown()
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                pressUp()
            }
        }
        #endif
    }

    // MARK: pairing

    func pair(code: String) async -> Bool {
        do {
            let token = try await client.pair(code: code, name: WKInterfaceDevice.current().name)
            Keychain.save(token)
            client.token = token
            isPaired = true
            return true
        } catch {
            return false
        }
    }

    func unpair() {
        Keychain.delete()
        client.token = nil
        isPaired = false
    }

    // MARK: talking

    private var waitingForServer = false

    func pressDown() {
        guard state == .idle || state == .speaking else { return }
        player.stop()
        Task {
            guard await Recorder.requestPermission() else {
                message = L.micDenied
                return
            }
            do {
                try recorder.start()
                WKInterfaceDevice.current().play(.start)
                message = ""
                state = .listening
            } catch {
                message = L.offline
            }
        }
    }

    func pressUp() {
        guard state == .listening else { return }
        guard let wav = recorder.stop() else {
            state = .idle
            return
        }
        WKInterfaceDevice.current().play(.click)  // the "heard you" cue: a tap on the wrist
        state = .thinking
        heard = ""
        sentences = []
        current = -1
        turnTask = Task { await runTurn(wav: wav) }
    }

    private func runTurn(wav: Data) async {
        waitingForServer = true
        defer { waitingForServer = false; if !player.isPlaying && state != .listening { state = .idle } }
        do {
            let turn = try await client.startTurn(wav: wav)
            var after = -1
            while !Task.isCancelled {
                let poll = try await client.poll(turn: turn, after: after)
                if let h = poll.heard { heard = h }
                for s in poll.sentences {
                    sentences.append(s.text)
                    if let data = Data(base64Encoded: s.audio) {
                        if state == .thinking { state = .speaking }
                        player.enqueue(id: s.id, wav: data)
                    }
                    after = s.id
                }
                if poll.unavailable && sentences.isEmpty { message = L.tired }
                if poll.done { break }
            }
        } catch PetClient.Failure.unauthorized {
            unpair()
        } catch {
            message = L.offline
        }
    }

    private func playbackFinished() {
        if !waitingForServer && state == .speaking { state = .idle }
    }

    func end() {
        turnTask?.cancel()
        player.stop()
        state = .idle
        heard = ""
        sentences = []
        current = -1
        message = L.seeYou
        Task { await client.end() }
    }
}

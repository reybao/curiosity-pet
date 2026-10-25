import AVFoundation
import Foundation

/// Records only while the child holds the button: 16 kHz mono 16-bit WAV, what the Mac's speech recognizer wants.
final class Recorder {
    #if DEBUG
    /// Simulator testing: a prepared recording stands in (the Mac mini has no microphone). Not in release builds.
    static let demoWav: Data? = ProcessInfo.processInfo.environment["PET_DEMO_WAV"].flatMap { FileManager.default.contents(atPath: $0) }
    #endif

    private var recorder: AVAudioRecorder?
    private let url = FileManager.default.temporaryDirectory.appendingPathComponent("question.wav")

    static func requestPermission() async -> Bool {
        #if DEBUG
        if demoWav != nil { return true }
        #endif
        return await withCheckedContinuation { cont in
            AVAudioApplication.requestRecordPermission { cont.resume(returning: $0) }
        }
    }

    func start() throws {
        #if DEBUG
        if Recorder.demoWav != nil { return }  // simulator testing: no microphone needed
        #endif
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [])
        try session.setActive(true)
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        try? FileManager.default.removeItem(at: url)
        let r = try AVAudioRecorder(url: url, settings: settings)
        r.record(forDuration: 30)  // the server takes at most 30 s
        recorder = r
    }

    /// Returns the recording, or nil when it is too short to be a question.
    func stop() -> Data? {
        #if DEBUG
        if let demo = Recorder.demoWav { return demo }
        #endif
        guard let r = recorder else { return nil }
        let seconds = r.currentTime
        r.stop()
        recorder = nil
        guard seconds >= 0.4 else { return nil }
        return try? Data(contentsOf: url)
    }
}

/// Plays the pet's sentences one after another as they arrive.
final class SpeechPlayer: NSObject, AVAudioPlayerDelegate {
    private var queue: [(Int, Data)] = []
    private var current: AVAudioPlayer?
    var onStart: ((Int) -> Void)?
    var onIdle: (() -> Void)?

    var isPlaying: Bool { current != nil }

    func enqueue(id: Int, wav: Data) {
        queue.append((id, wav))
        if current == nil { playNext() }
    }

    func stop() {
        queue.removeAll()
        current?.stop()
        current = nil
    }

    private func playNext() {
        guard !queue.isEmpty else {
            current = nil
            onIdle?()
            return
        }
        let (id, wav) = queue.removeFirst()
        guard let p = try? AVAudioPlayer(data: wav) else { return playNext() }
        p.delegate = self
        current = p
        onStart?(id)
        p.play()
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        DispatchQueue.main.async { self.playNext() }
    }
}

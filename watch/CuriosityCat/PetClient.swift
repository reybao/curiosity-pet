import Foundation

/// Talks to the Mac's watch API (src/curiosity_pet/watch_api.py). Plain HTTPS requests only:
/// watchOS restricts WebSockets to audio-streaming apps, so a turn is "upload the recording, then long-poll".
struct PetClient {
    enum Failure: Error { case unauthorized, busy, server(Int), badResponse }

    struct Sentence: Decodable, Identifiable {
        let id: Int
        let text: String
        let audio: String  // base64 WAV
    }

    struct Poll: Decodable {
        let heard: String?
        let lang: String?
        let sentences: [Sentence]
        let done: Bool
        let source: String?
        let unavailable: Bool
    }

    let base: URL
    var token: String?

    static func fromBundle(token: String?) -> PetClient {
        let info = Bundle.main.infoDictionary ?? [:]
        let scheme = info["PetScheme"] as? String ?? "https"
        let host = info["PetHost"] as? String ?? "localhost"
        let port = info["PetPort"] as? String ?? "443"
        return PetClient(base: URL(string: "\(scheme)://\(host):\(port)")!, token: token)
    }

    private var session: URLSession {
        let config = URLSessionConfiguration.ephemeral  // no cookies, no cache
        config.timeoutIntervalForRequest = 30
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }

    private func request(_ path: String, method: String = "GET", body: Data? = nil, contentType: String? = nil) -> URLRequest {
        var r = URLRequest(url: base.appendingPathComponent(path))
        r.httpMethod = method
        r.httpBody = body
        if let contentType { r.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return r
    }

    private func send(_ r: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: r)
        guard let http = response as? HTTPURLResponse else { throw Failure.badResponse }
        switch http.statusCode {
        case 200: return data
        case 401: throw Failure.unauthorized
        case 409: throw Failure.busy
        default: throw Failure.server(http.statusCode)
        }
    }

    func pair(code: String, name: String) async throws -> String {
        let body = try JSONSerialization.data(withJSONObject: ["code": code, "name": name])
        let data = try await send(request("watch/pair", method: "POST", body: body, contentType: "application/json"))
        guard let token = (try JSONSerialization.jsonObject(with: data) as? [String: Any])?["token"] as? String else {
            throw Failure.badResponse
        }
        return token
    }

    func ping() async throws {
        _ = try await send(request("watch/ping"))
    }

    func startTurn(wav: Data) async throws -> String {
        let data = try await send(request("watch/turn", method: "POST", body: wav, contentType: "audio/wav"))
        guard let id = (try JSONSerialization.jsonObject(with: data) as? [String: Any])?["turn_id"] as? String else {
            throw Failure.badResponse
        }
        return id
    }

    func poll(turn: String, after: Int) async throws -> Poll {
        var comps = URLComponents(url: base.appendingPathComponent("watch/turn/\(turn)"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "after", value: "\(after)"), URLQueryItem(name: "wait", value: "10")]
        var r = URLRequest(url: comps.url!)
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        return try JSONDecoder().decode(Poll.self, from: try await send(r))
    }

    func end() async {
        _ = try? await send(request("watch/end", method: "POST"))
    }
}

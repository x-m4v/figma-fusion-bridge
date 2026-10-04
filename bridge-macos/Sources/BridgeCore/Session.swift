import CryptoKit
import Foundation

/// Pairing and authentication.
///
/// Any web page the user has open can reach a loopback port, so the port is not
/// a permission. The bridge shows a short code; the user types it into the
/// plugin once; the plugin gets a long-lived token. Every endpoint that does
/// anything requires that token, so a hostile page can knock but not enter.
///
/// The code is regenerated on every launch and expires, which keeps a
/// shoulder-surfed or logged code from being useful later.
public actor Session {
    public struct Snapshot: Sendable {
        public let port: UInt16
        public let pairingCode: String
        public let isPaired: Bool
    }

    public private(set) var port: UInt16 = 0
    public private(set) var token: String
    public private(set) var pairingCode: String
    private var pairingExpiry: Date
    private var pairedClients: Set<String> = []

    /// Long enough to walk to the other window, short enough to be useless later.
    private static let pairingLifetime: TimeInterval = 10 * 60

    public init() {
        // The token outlives the process. Regenerating it on every launch would
        // silently unpair the plugin each time the bridge restarts, which flatly
        // contradicts the "type this once" the interface promises.
        let restored = Session.loadCredentials()
        token = restored?.token ?? Session.randomToken()
        pairedClients = restored?.paired ?? []
        // The pairing *code* is deliberately not persisted. It is a short-lived
        // secret; one still valid after a reboot would be a standing invitation.
        pairingCode = Session.randomCode()
        pairingExpiry = Date().addingTimeInterval(Session.pairingLifetime)
        if restored == nil { try? Self.saveCredentials(token: token, paired: pairedClients) }
    }

    // MARK: - Persistence

    private struct Credentials: Codable {
        var token: String
        var paired: Set<String>
    }

    private static var credentialsURL: URL {
        Paths.support.appendingPathComponent("credentials.json")
    }

    private static func loadCredentials() -> (token: String, paired: Set<String>)? {
        guard let data = try? Data(contentsOf: credentialsURL),
              let decoded = try? JSONDecoder().decode(Credentials.self, from: data),
              decoded.token.count == 64
        else { return nil }
        return (decoded.token, decoded.paired)
    }

    private func persistCredentials() throws {
        try Self.saveCredentials(token: token, paired: pairedClients)
    }

    private static func saveCredentials(token: String, paired: Set<String>) throws {
        try Paths.ensureDirectories()
        let url = Session.credentialsURL
        let data = try JSONEncoder().encode(Credentials(token: token, paired: paired))
        try data.write(to: url, options: [.atomic])
        // Owner-only. This is the credential itself.
        try FileManager.default.setAttributes([.posixPermissions: 0o600],
                                              ofItemAtPath: url.path)
    }

    public func setPort(_ value: UInt16) { port = value }

    public var isPaired: Bool { !pairedClients.isEmpty }

    public func snapshot() -> Snapshot {
        Snapshot(port: port, pairingCode: currentCode(), isPaired: isPaired)
    }

    /// The code currently displayed, refreshed when the old one has expired.
    public func currentCode() -> String {
        if Date() > pairingExpiry {
            pairingCode = Session.randomCode()
            pairingExpiry = Date().addingTimeInterval(Session.pairingLifetime)
        }
        return pairingCode
    }

    public func regenerateCode() -> String {
        pairingCode = Session.randomCode()
        pairingExpiry = Date().addingTimeInterval(Session.pairingLifetime)
        return pairingCode
    }

    /// Exchange a pairing code for the session token.
    public func pair(code: String) -> String? {
        guard Date() <= pairingExpiry else { return nil }
        let given = code.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        // Constant-time comparison: the code is short, so a timing oracle would
        // meaningfully narrow the search space.
        guard constantTimeEquals(given, currentCode()) else { return nil }
        pairedClients.insert("figma")
        try? persistCredentials()
        return token
    }

    public func validate(_ candidate: String?) -> Bool {
        guard let candidate else { return false }
        return constantTimeEquals(candidate, token)
    }

    public func unpairAll() {
        pairedClients.removeAll()
        token = Session.randomToken()
        defer { try? persistCredentials() }
        _ = regenerateCode()
    }

    /// Written so the Resolve scripts — which run on this machine and can read
    /// the user's own files — can authenticate without a pairing step.
    public func writeSessionFile() throws {
        try Paths.ensureDirectories()
        let payload: [String: Any] = ["port": Int(port), "token": token, "pid": ProcessInfo.processInfo.processIdentifier]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted])
        try data.write(to: Paths.sessionFile, options: [.atomic])
        // Owner-only: the token is a credential.
        try FileManager.default.setAttributes([.posixPermissions: 0o600],
                                              ofItemAtPath: Paths.sessionFile.path)
    }

    public func removeSessionFile() {
        try? FileManager.default.removeItem(at: Paths.sessionFile)
    }

    // MARK: - Helpers

    private static func randomToken() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    /// Six characters from an alphabet with no 0/O or 1/I/L, because the user
    /// reads this off one window and types it into another.
    private static func randomCode() -> String {
        let alphabet = Array("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
        var bytes = [UInt8](repeating: 0, count: 6)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return String(bytes.map { alphabet[Int($0) % alphabet.count] })
    }
}

public func constantTimeEquals(_ a: String, _ b: String) -> Bool {
    let lhs = Array(a.utf8), rhs = Array(b.utf8)
    guard lhs.count == rhs.count else { return false }
    var diff: UInt8 = 0
    for i in 0..<lhs.count { diff |= lhs[i] ^ rhs[i] }
    return diff == 0
}

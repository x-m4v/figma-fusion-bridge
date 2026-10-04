import CryptoKit
import Foundation

/// Content-addressed asset storage, shared with the Resolve side.
///
/// Keyed by SHA-256 so an image used many times is stored once and uploaded
/// once — the plugin asks which digests are already here before sending
/// anything, so a re-sync of a design full of photos transfers almost nothing.
public actor AssetStore {
    private let root: URL

    public init(root: URL = Paths.assets) {
        self.root = root
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    private func location(_ digest: String, ext: String) -> URL {
        // Two-level fan-out keeps any single directory small; a flat folder of
        // tens of thousands of files makes Finder and some FS calls crawl.
        root.appendingPathComponent(String(digest.prefix(2)), isDirectory: true)
            .appendingPathComponent(String(digest.dropFirst(2).prefix(2)), isDirectory: true)
            .appendingPathComponent("\(digest).\(ext)")
    }

    private func existing(_ digest: String) -> URL? {
        let dir = root.appendingPathComponent(String(digest.prefix(2)), isDirectory: true)
            .appendingPathComponent(String(digest.dropFirst(2).prefix(2)), isDirectory: true)
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: dir.path) else { return nil }
        guard let match = names.first(where: { $0.hasPrefix(digest) && !$0.hasSuffix(".name") })
        else { return nil }
        return dir.appendingPathComponent(match)
    }

    public func has(_ digest: String) -> Bool { existing(digest) != nil }

    public func known(_ digests: [String]) -> [String] { digests.filter { has($0) } }

    public func path(for digest: String) -> URL? { existing(digest) }

    public func data(for digest: String) -> Data? {
        guard let url = existing(digest) else { return nil }
        return try? Data(contentsOf: url)
    }

    /// Store bytes, verifying that they hash to the id they were sent under.
    ///
    /// Not paranoia: a truncated upload stored under the *expected* digest would
    /// be served to every future transfer as though it were correct.
    @discardableResult
    public func store(_ data: Data, digest: String, mimeType: String, filename: String) throws -> URL {
        let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard actual == digest.lowercased() else {
            throw BridgeError.checksumMismatch(expected: digest, actual: actual)
        }
        let url = location(actual, ext: Self.fileExtension(for: mimeType, filename: filename))
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: url.path) {
            // Write-then-rename, so a crash mid-write cannot leave a partial
            // file that later looks like a valid cache hit.
            let temp = url.appendingPathExtension("part")
            try data.write(to: temp, options: [.atomic])
            _ = try FileManager.default.replaceItemAt(url, withItemAt: temp)
        }
        if !filename.isEmpty {
            try? Data(filename.utf8).write(to: url.appendingPathExtension("name"))
        }
        return url
    }

    public func totalBytes() -> Int64 {
        guard let e = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.fileSizeKey])
        else { return 0 }
        var total: Int64 = 0
        for case let url as URL in e {
            total += Int64((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        }
        return total
    }

    public func clear() {
        try? FileManager.default.removeItem(at: root)
        try? FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }

    public static func fileExtension(for mimeType: String, filename: String) -> String {
        switch mimeType.lowercased() {
        case "image/png": return "png"
        case "image/jpeg", "image/jpg": return "jpg"
        case "image/webp": return "webp"
        case "image/gif": return "gif"
        case "image/svg+xml": return "svg"
        default:
            let ext = (filename as NSString).pathExtension
            return ext.isEmpty ? "bin" : ext.lowercased()
        }
    }
}

public enum BridgeError: LocalizedError {
    case checksumMismatch(expected: String, actual: String)
    case portUnavailable
    case notPaired

    public var errorDescription: String? {
        switch self {
        case .checksumMismatch:
            return "An uploaded image did not match its checksum and was rejected."
        case .portUnavailable:
            return "No local port was available for the bridge."
        case .notPaired:
            return "This client has not been paired with the bridge."
        }
    }
}

/// One completed or pending transfer.
public struct TransferRecord: Codable, Identifiable, Sendable {
    public var id: String
    public var receivedAt: Date
    public var documentName: String
    public var frameName: String
    public var nodeCount: Int
    public var assetCount: Int
    public var warningCount: Int
    public var errorCount: Int
    public var status: String        // "pending" | "ok" | "error"
    public var durationMs: Int
    public var resolveProject: String?

    public init(id: String, receivedAt: Date, documentName: String, frameName: String,
                nodeCount: Int, assetCount: Int, warningCount: Int, errorCount: Int,
                status: String, durationMs: Int, resolveProject: String?) {
        self.id = id
        self.receivedAt = receivedAt
        self.documentName = documentName
        self.frameName = frameName
        self.nodeCount = nodeCount
        self.assetCount = assetCount
        self.warningCount = warningCount
        self.errorCount = errorCount
        self.status = status
        self.durationMs = durationMs
        self.resolveProject = resolveProject
    }
}

/// Pending transfers plus the history shown in the dashboard.
///
/// Only the most recent document is kept in memory for delivery; history keeps
/// metadata only, never the design itself, so the file stays small and contains
/// nothing sensitive.
public actor TransferStore {
    private var pending: [String: Data] = [:]
    private var latestId: String?
    public private(set) var history: [TransferRecord] = []
    /// Long-poll waiters, keyed so each can be resumed exactly once.
    /// A continuation resumed twice is a crash, and a race between a transfer
    /// arriving and the poll timing out is the normal case here, not a rare one.
    private var waiters: [UUID: CheckedContinuation<Data?, Never>] = [:]

    private let historyLimit = 50

    public init() {
        // Loaded synchronously here rather than by calling an actor-isolated
        // method from init, which is not allowed and becomes a hard error under
        // the Swift 6 language mode.
        if let data = try? Data(contentsOf: Paths.historyFile),
           let decoded = try? JSONDecoder().decode([TransferRecord].self, from: data) {
            history = decoded
        }
    }

    public func submit(_ document: Data, record: TransferRecord) {
        pending[record.id] = document
        latestId = record.id
        history.insert(record, at: 0)
        if history.count > historyLimit { history.removeLast(history.count - historyLimit) }
        saveHistory()

        // Wake anything long-polling. Resolve is usually already waiting, so
        // this is what makes Live Sync feel immediate.
        let waiting = waiters.values
        waiters.removeAll()
        for continuation in waiting { continuation.resume(returning: document) }
    }

    public func latest() -> Data? {
        guard let id = latestId else { return nil }
        return pending[id]
    }

    public func take() -> Data? {
        guard let id = latestId, let data = pending[id] else { return nil }
        return data
    }

    /// Long-poll: resume as soon as a transfer arrives, or return nil on timeout.
    public func wait(seconds: Double) async -> Data? {
        if let data = latest() { return data }
        let id = UUID()
        return await withCheckedContinuation { (continuation: CheckedContinuation<Data?, Never>) in
            waiters[id] = continuation
            Task {
                try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                // The Task inherits this actor's isolation, so expire() runs
                // on the actor without a hop — no await needed.
                self.expire(id)
            }
        }
    }

    /// Time out one waiter. Removing it from the table first is what guarantees
    /// the continuation resumes exactly once: if `submit` got there first the
    /// entry is already gone and this does nothing.
    private func expire(_ id: UUID) {
        guard let continuation = waiters.removeValue(forKey: id) else { return }
        continuation.resume(returning: nil)
    }

    public func report(id: String, status: String, nodeCount: Int, assetCount: Int,
                warningCount: Int, errorCount: Int, durationMs: Int) {
        guard let index = history.firstIndex(where: { $0.id == id }) else { return }
        history[index].status = status
        history[index].nodeCount = nodeCount
        history[index].assetCount = assetCount
        history[index].warningCount = warningCount
        history[index].errorCount = errorCount
        history[index].durationMs = durationMs
        saveHistory()
    }

    public func clearHistory() {
        history.removeAll()
        saveHistory()
    }

    private func saveHistory() {
        guard let data = try? JSONEncoder().encode(history) else { return }
        try? FileManager.default.createDirectory(at: Paths.support, withIntermediateDirectories: true)
        try? data.write(to: Paths.historyFile, options: [.atomic])
    }
}

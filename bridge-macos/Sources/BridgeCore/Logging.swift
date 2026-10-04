import Foundation
import os

/// Structured logging.
///
/// Two sinks on purpose. `os.Logger` gives live tailing in Console.app during
/// development; the rotating file is what a user can actually attach to a bug
/// report, and it is what "Export Diagnostic Report" collects.
public final class BridgeLog: @unchecked Sendable {
    public static let shared = BridgeLog()

    private let logger = Logger(subsystem: "com.figmafusionbridge.helper", category: "bridge")
    private let queue = DispatchQueue(label: "ffbridge.log")
    private let fileURL: URL
    private let maxBytes = 2 * 1024 * 1024

    private init() {
        fileURL = Paths.logs.appendingPathComponent("bridge.log")
        try? FileManager.default.createDirectory(at: Paths.logs, withIntermediateDirectories: true)
    }

    public enum Level: String {
        case debug = "DEBUG", info = "INFO", warn = "WARN", error = "ERROR"
    }

    public func log(_ level: Level, _ component: String, _ message: String, transferId: String = "-") {
        switch level {
        case .debug: logger.debug("[\(component, privacy: .public)] \(message, privacy: .public)")
        case .info:  logger.info("[\(component, privacy: .public)] \(message, privacy: .public)")
        case .warn:  logger.warning("[\(component, privacy: .public)] \(message, privacy: .public)")
        case .error: logger.error("[\(component, privacy: .public)] \(message, privacy: .public)")
        }

        queue.async { [self] in
            let stamp = ISO8601DateFormatter().string(from: Date())
            let line = "\(stamp) \(level.rawValue.padding(toLength: 5, withPad: " ", startingAt: 0)) \(component) [\(transferId)] \(message)\n"
            guard let data = line.data(using: .utf8) else { return }
            rotateIfNeeded()
            if let handle = try? FileHandle(forWritingTo: fileURL) {
                defer { try? handle.close() }
                _ = try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
            } else {
                try? data.write(to: fileURL)
            }
        }
    }

    private func rotateIfNeeded() {
        let fm = FileManager.default
        guard let size = try? fm.attributesOfItem(atPath: fileURL.path)[.size] as? Int,
              size > maxBytes else { return }
        let rotated = fileURL.deletingPathExtension().appendingPathExtension("1.log")
        try? fm.removeItem(at: rotated)
        try? fm.moveItem(at: fileURL, to: rotated)
    }

    public func info(_ c: String, _ m: String, transferId: String = "-") { log(.info, c, m, transferId: transferId) }
    public func warn(_ c: String, _ m: String, transferId: String = "-") { log(.warn, c, m, transferId: transferId) }
    public func error(_ c: String, _ m: String, transferId: String = "-") { log(.error, c, m, transferId: transferId) }
    public func debug(_ c: String, _ m: String, transferId: String = "-") { log(.debug, c, m, transferId: transferId) }
}

import Foundation

/// Where the bridge keeps its files.
///
/// Application Support rather than a temporary directory, because a Fusion
/// Loader stores a *path*: assets put in `/tmp` would break every existing
/// composition the next time the machine cleared it out.
public enum Paths {
    public static let appName = "FigmaFusionBridge"

    /// Overrides the whole data directory. Set by the test runner.
    ///
    /// Without this the tests wrote to the real Application Support folder —
    /// creating sessions, pairing and unpairing — which silently invalidated a
    /// running user's pairing every time the suite ran. Sandboxing at the root
    /// covers credentials, assets, history and manifests in one place, rather
    /// than each store having to remember to be careful.
    public static let overrideEnvironmentKey = "FFBRIDGE_SUPPORT_DIR"

    private static var overrideRoot: URL? {
        guard let value = ProcessInfo.processInfo.environment[overrideEnvironmentKey],
              !value.isEmpty else { return nil }
        return URL(fileURLWithPath: value, isDirectory: true)
    }

    public static var support: URL {
        if let overrideRoot { return overrideRoot }
        return FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(appName, isDirectory: true)
    }

    public static var assets: URL { support.appendingPathComponent("Assets", isDirectory: true) }
    public static var transfers: URL { support.appendingPathComponent("Transfers", isDirectory: true) }
    public static var manifests: URL { support.appendingPathComponent("Manifests", isDirectory: true) }
    public static var sessionFile: URL { support.appendingPathComponent("session.json") }
    public static var historyFile: URL { support.appendingPathComponent("history.json") }
    public static var settingsFile: URL { support.appendingPathComponent("settings.json") }

    public static var logs: URL {
        if let overrideRoot { return overrideRoot.appendingPathComponent("Logs", isDirectory: true) }
        return FileManager.default
            .urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs", isDirectory: true)
            .appendingPathComponent(appName, isDirectory: true)
    }

    /// The per-user folder DaVinci Resolve scans for scripts at startup.
    /// Taken verbatim from the Scripting SDK README shipped with Resolve.
    public static var resolveScripts: URL {
        if let root = ProcessInfo.processInfo.environment["FFBRIDGE_SCRIPTS_DIR"], !root.isEmpty {
            return URL(fileURLWithPath: root, isDirectory: true)
        }
        return FileManager.default
            .urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts", isDirectory: true)
    }

    /// Where the Python package the Resolve scripts import is installed.
    public static var libDirectory: URL { support.appendingPathComponent("lib", isDirectory: true) }

    public static func ensureDirectories() throws {
        let fm = FileManager.default
        for url in [support, assets, transfers, manifests, logs, libDirectory] {
            try fm.createDirectory(at: url, withIntermediateDirectories: true)
        }
    }
}

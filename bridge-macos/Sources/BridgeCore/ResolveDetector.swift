import AppKit
import Foundation

/// Finds DaVinci Resolve and reports whether it is running.
///
/// Detection is by running application and by installed bundle, both through
/// public AppKit and file-system calls. Nothing here injects, hooks or inspects
/// another process's memory: the product has to keep working across Resolve
/// updates, and it has to be something a user can reasonably trust.
public struct ResolveDetector {
    public struct Info: Sendable, Equatable {
        public var installed: Bool
        public var running: Bool
        public var version: String?
        public var isStudio: Bool
        public var applicationURL: URL?

        public init(installed: Bool, running: Bool, version: String?,
                    isStudio: Bool, applicationURL: URL?) {
            self.installed = installed
            self.running = running
            self.version = version
            self.isStudio = isStudio
            self.applicationURL = applicationURL
        }

        /// Before the first detection pass has run.
        public static let unknown = Info(installed: false, running: false,
                                         version: nil, isStudio: false, applicationURL: nil)
    }

    /// Standard install location, plus the common alternative of a renamed copy
    /// sitting directly in /Applications.
    private static let searchPaths = [
        "/Applications/DaVinci Resolve/DaVinci Resolve.app",
        "/Applications/DaVinci Resolve.app",
    ]

    public static let bundleIdentifiers = [
        "com.blackmagic-design.DaVinciResolve",
        "com.blackmagicdesign.resolve",
    ]

    public static func detect() -> Info {
        let running = NSWorkspace.shared.runningApplications.first { app in
            guard let id = app.bundleIdentifier else { return false }
            return bundleIdentifiers.contains(id) || id.lowercased().contains("davinciresolve")
        }

        var url: URL?
        for path in searchPaths where FileManager.default.fileExists(atPath: path) {
            url = URL(fileURLWithPath: path)
            break
        }
        if url == nil, let bundleURL = running?.bundleURL { url = bundleURL }

        var version: String?
        var studio = false
        if let url {
            let plist = url.appendingPathComponent("Contents/Info.plist")
            if let data = try? Data(contentsOf: plist),
               let info = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] {
                version = info["CFBundleShortVersionString"] as? String
                let name = (info["CFBundleName"] as? String ?? "")
                studio = name.localizedCaseInsensitiveContains("studio")
            }
            // The free edition ships without the licence marker that Studio has.
            if !studio {
                studio = FileManager.default.fileExists(
                    atPath: "/Library/Application Support/Blackmagic Design/DaVinci Resolve/.license"
                )
            }
        }

        return Info(installed: url != nil,
                    running: running != nil,
                    version: version,
                    isStudio: studio,
                    applicationURL: url)
    }

    /// Bring Resolve forward. Uses the public workspace API, not Apple Events,
    /// so it needs no automation permission.
    public static func activate() {
        let info = detect()
        guard let url = info.applicationURL else { return }
        NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
    }

    public static func activateFigma() {
        let candidates = ["/Applications/Figma.app"]
        for path in candidates where FileManager.default.fileExists(atPath: path) {
            NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: path),
                                               configuration: NSWorkspace.OpenConfiguration())
            return
        }
        if let url = URL(string: "https://www.figma.com/files/") {
            NSWorkspace.shared.open(url)
        }
    }
}

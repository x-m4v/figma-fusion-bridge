import Foundation

/// Installs the Resolve-side scripts and the Python package they import.
///
/// Everything goes into the *per-user* Application Support tree. The all-users
/// location under `/Library` would need an administrator password, and buys
/// nothing for a single-user tool — asking for admin rights to install a script
/// is exactly the kind of friction that makes people give up during setup.
public struct Installer {
    public struct Report {
        public var installedScripts: [String] = []
        public var libraryPath: URL?
        public var errors: [String] = []
        public var ok: Bool { errors.isEmpty }

        public init() {}
    }

    /// Where the bundled payload lives inside the .app.
    private static func bundledResource(_ name: String) -> URL? {
        let sourceName = name == "ffbridge.lua" ? "lua/ffbridge.lua" : name
        let candidates = [
            Bundle.main.resourceURL?.appendingPathComponent(name),
            // Running straight from `swift run` during development.
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
                .appendingPathComponent("../resolve/\(sourceName)"),
            URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()
                .appendingPathComponent("../../../resolve/\(sourceName)"),
        ].compactMap { $0?.standardizedFileURL }

        return candidates.first { FileManager.default.fileExists(atPath: $0.path) }
    }

    public static func install() -> Report {
        var report = Report()
        let fm = FileManager.default

        do {
            try Paths.ensureDirectories()
        } catch {
            report.errors.append("Could not create the support folder: \(error.localizedDescription)")
            return report
        }

        // 1. The Python package the scripts import.
        if let source = bundledResource("ffbridge") {
            let destination = Paths.libDirectory.appendingPathComponent("ffbridge", isDirectory: true)
            do {
                if fm.fileExists(atPath: destination.path) {
                    try fm.removeItem(at: destination)
                }
                try fm.copyItem(at: source, to: destination)
                report.libraryPath = destination
            } catch {
                report.errors.append("Could not install the bridge library: \(error.localizedDescription)")
            }
        } else {
            report.errors.append("The bridge library is missing from the application bundle.")
        }

        // Lua helper and file-based CLI launcher are required by the menu commands.
        for name in ["ffbridge.lua", "ffbridge_launcher.py"] {
            guard let source = bundledResource(name) else {
                report.errors.append("Missing bundled helper: \(name)")
                continue
            }
            let destination = Paths.libDirectory.appendingPathComponent(name)
            do {
                if fm.fileExists(atPath: destination.path) { try fm.removeItem(at: destination) }
                try fm.copyItem(at: source, to: destination)
            } catch { report.errors.append("Could not install \(name): \(error.localizedDescription)") }
        }

        // 2. The menu scripts.
        guard let scripts = bundledResource("scripts") else {
            report.errors.append("The Resolve scripts are missing from the application bundle.")
            return report
        }

        let target = Paths.resolveScripts
        do {
            try fm.createDirectory(at: target, withIntermediateDirectories: true)
        } catch {
            report.errors.append(
                "Could not write to the DaVinci Resolve scripts folder. "
                + "Is DaVinci Resolve installed?"
            )
            return report
        }

        guard let walker = fm.enumerator(at: scripts, includingPropertiesForKeys: [.isDirectoryKey]) else {
            report.errors.append("The bundled scripts could not be read.")
            return report
        }

        for case let source as URL in walker {
            let relative = source.path.replacingOccurrences(of: scripts.path + "/", with: "")
            let destination = target.appendingPathComponent(relative)
            let isDirectory = (try? source.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) ?? false
            do {
                if isDirectory {
                    try fm.createDirectory(at: destination, withIntermediateDirectories: true)
                } else {
                    try fm.createDirectory(at: destination.deletingLastPathComponent(),
                                           withIntermediateDirectories: true)
                    if fm.fileExists(atPath: destination.path) {
                        try fm.removeItem(at: destination)
                    }
                    try fm.copyItem(at: source, to: destination)
                    if source.pathExtension == "lua" {
                        report.installedScripts.append(relative)
                    }
                }
            } catch {
                report.errors.append("Could not install \(relative): \(error.localizedDescription)")
            }
        }

        BridgeLog.shared.info("installer",
                              "Installed \(report.installedScripts.count) scripts, \(report.errors.count) errors")
        return report
    }

    public static func isInstalled() -> Bool {
        FileManager.default.fileExists(
            atPath: Paths.resolveScripts
                .appendingPathComponent("Comp/Figma Fusion Bridge - Receive.lua").path
        ) && FileManager.default.fileExists(
            atPath: Paths.libDirectory.appendingPathComponent("ffbridge.lua").path
        ) && FileManager.default.fileExists(
            atPath: Paths.libDirectory.appendingPathComponent("ffbridge/builder.py").path
        )
    }

    public static func uninstall() {
        let fm = FileManager.default
        for name in ["Comp/Figma Fusion Bridge", "Utility/Figma Fusion Bridge", "_bootstrap.py"] {
            try? fm.removeItem(at: Paths.resolveScripts.appendingPathComponent(name))
        }
        for name in ["Comp/Figma Fusion Bridge - Receive.lua", "Comp/Figma Fusion Bridge - Pull Figma Selection.lua", "Utility/Figma Fusion Bridge - Connection Test.lua"] {
            try? fm.removeItem(at: Paths.resolveScripts.appendingPathComponent(name))
        }
        for name in ["ffbridge", "ffbridge.lua", "ffbridge_launcher.py", "python-path.txt"] {
            try? fm.removeItem(at: Paths.libDirectory.appendingPathComponent(name))
        }
    }
}

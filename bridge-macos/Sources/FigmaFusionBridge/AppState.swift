import AppKit
import BridgeCore
import Combine
import Foundation
import SwiftUI

/// Everything the interface shows, in one observable place.
///
/// `@MainActor` throughout: the server runs off-main and reaches in through
/// async calls, and funnelling every mutation to the main actor is what keeps
/// SwiftUI from being updated from a background queue.
@MainActor
final class AppState: ObservableObject, BridgeStatusSink {
    /// One instance, because the server is started before any view exists and
    /// must publish into the same object the dashboard later observes.
    static let shared = AppState()

    enum Tab: String, CaseIterable, Identifiable {
        case status = "Status", setup = "Setup", history = "History", settings = "Settings"
        var id: String { rawValue }
    }

    enum Connection: String {
        case connected, connecting, disconnected, error

        var color: Color {
            switch self {
            case .connected: return .green
            case .connecting: return .accentColor
            case .disconnected: return .secondary
            case .error: return .red
            }
        }
    }

    // Status
    @Published var bridgeRunning = false
    @Published var port: UInt16 = 0
    @Published var pairingCode = ""
    @Published var figmaConnected = false
    @Published var resolve: ResolveDetector.Info = .unknown
    /// Whether a plugin has exchanged the pairing code for a token.
    @Published var isPaired: Bool = false
    /// When a Resolve script last made a request. Nil until one does.
    private var lastResolveScriptContact: Date?
    @Published var scriptsInstalled = false
    @Published var lastError: String?

    // Transfers
    @Published var history: [TransferRecord] = []
    @Published var lastTransferAt: Date?
    @Published var cacheBytes: Int64 = 0

    // UI
    @Published var dashboardTab: Tab = .status

    // Settings
    @Published var launchAtLogin = false
    @Published var showNotifications = true

    private var session: Session?
    private var transfers: TransferStore?
    private var assets: AssetStore?
    private var pollTimer: Timer?
    /// Figma has no heartbeat, so "connected" decays if the plugin stops asking.
    private var lastFigmaContact: Date?
    private static let figmaTimeout: TimeInterval = 20

    func attach(session: Session, transfers: TransferStore, assets: AssetStore) {
        self.session = session
        self.transfers = transfers
        self.assets = assets
    }

    // MARK: - Derived status

    var bridgeStatus: Connection { bridgeRunning ? .connected : .error }

    var resolveStatus: Connection {
        if resolve.running { return .connected }
        return resolve.installed ? .disconnected : .error
    }

    var figmaStatus: Connection { figmaConnected ? .connected : .disconnected }

    var resolveDescription: String {
        if !resolve.installed { return "not installed" }
        if !resolve.running { return "not running" }
        let edition = resolve.isStudio ? "Studio" : "Free"
        return "\(resolve.version ?? "?") \(edition)"
    }

    var cacheDescription: String {
        ByteCountFormatter.string(fromByteCount: cacheBytes, countStyle: .file)
    }

    // MARK: - Mutations from the server

    func setFigmaConnected(_ value: Bool) {
        figmaConnected = value
        if value { lastFigmaContact = Date() }
    }

    /// Called when a Resolve script talks to the bridge.
    ///
    /// Records that separately rather than forcing `resolve.running`, which the
    /// detector owns. Overwriting the detector's answer made the flag latch on
    /// and never clear, so the status stayed green after Resolve had quit.
    func setResolveConnected(_ value: Bool) {
        if value { lastResolveScriptContact = Date() }
    }

    func noteClient(_ client: String?) {
        switch client {
        case "figma": setFigmaConnected(true)
        case "resolve": setResolveConnected(true)
        default: break
        }
    }

    func noteTransfer(_ record: TransferRecord) {
        lastTransferAt = record.receivedAt
        setFigmaConnected(true)
        Task { await refreshHistory() }
    }

    /// A script counts as present for this long after its last request. Long
    /// enough to span a user reading a transfer report, short enough that a
    /// closed Resolve goes grey while they are still looking at the panel.
    private static let resolveScriptTimeout: TimeInterval = 120

    var resolveScriptSeen: Bool {
        guard resolve.running, let last = lastResolveScriptContact else { return false }
        return Date().timeIntervalSince(last) < Self.resolveScriptTimeout
    }

    func statusSnapshot() -> BridgeSnapshot {
        BridgeSnapshot(figmaConnected: figmaConnected,
                       resolveRunning: resolve.running,
                       resolveScriptSeen: resolveScriptSeen,
                       lastTransferAt: lastTransferAt)
    }

    // MARK: - Polling

    /// Poll rather than observe, because there is no notification for "Resolve
    /// opened a composition". Two seconds is well under the time it takes a
    /// user to switch windows, and the check is a couple of cheap syscalls.
    func startPolling() {
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        refresh()
    }

    func refresh() {
        resolve = ResolveDetector.detect()
        scriptsInstalled = Installer.isInstalled()

        if let last = lastFigmaContact, Date().timeIntervalSince(last) > Self.figmaTimeout {
            figmaConnected = false
        }
        Task {
            if let session { 
                let snap = await session.snapshot()
                await MainActor.run {
                    self.port = snap.port
                    self.pairingCode = snap.pairingCode
                    self.isPaired = snap.isPaired
                }
            }
            if let assets {
                let bytes = await assets.totalBytes()
                await MainActor.run { self.cacheBytes = bytes }
            }
        }
    }

    func refreshHistory() async {
        guard let transfers else { return }
        let records = await transfers.history
        await MainActor.run { self.history = records }
    }

    // MARK: - Actions

    func installScripts() {
        let report = Installer.install()
        scriptsInstalled = report.ok && Installer.isInstalled()
        lastError = report.errors.first
    }

    func clearCache() {
        Task {
            await assets?.clear()
            let bytes = await assets?.totalBytes() ?? 0
            await MainActor.run { self.cacheBytes = bytes }
        }
    }

    func regenerateCode() {
        Task {
            guard let session else { return }
            let code = await session.regenerateCode()
            await MainActor.run { self.pairingCode = code }
        }
    }

    func unpair() {
        Task {
            await session?.unpairAll()
            try? await session?.writeSessionFile()
            await MainActor.run {
                self.figmaConnected = false
                self.refresh()
            }
        }
    }

    func openLogs() {
        NSWorkspace.shared.open(Paths.logs)
    }

    func exportDiagnostics() {
        // A folder rather than a zip: Finder can compress it in one click, and
        // the user can see exactly what they are about to share.
        NSWorkspace.shared.selectFile(Paths.logs.appendingPathComponent("bridge.log").path,
                                      inFileViewerRootedAtPath: Paths.logs.path)
    }
}

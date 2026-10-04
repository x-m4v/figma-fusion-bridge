import AppKit
import BridgeCore
import SwiftUI

/// A status line: a coloured dot, a label, and the detail on the right.
/// Repeated everywhere, so it is one view rather than four near-copies.
struct StatusRow: View {
    let title: String
    let state: AppState.Connection
    let detail: String

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(state.color)
                .frame(width: 7, height: 7)
            Text(title)
            Spacer(minLength: 12)
            Text(detail)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title): \(state.rawValue). \(detail)")
    }
}

// MARK: - Menu bar

struct MenuBarView: View {
    @ObservedObject var state: AppState
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 6) {
                StatusRow(title: "Bridge", state: state.bridgeStatus,
                          detail: state.bridgeRunning ? "port \(state.port)" : "stopped")
                StatusRow(title: "Figma", state: state.figmaStatus,
                          detail: state.figmaConnected ? "connected" : "not connected")
                StatusRow(title: "DaVinci Resolve", state: state.resolveStatus,
                          detail: state.resolveDescription)
            }
            .font(.system(size: 12))

            // The pairing code belongs here, not only in the dashboard. The
            // plugin tells the user to "open the app and type the code it
            // shows", and this popover is what opening the app looks like.
            //
            // Shown only while unpaired: once the plugin holds a token the code
            // is noise, and leaving a live credential on screen is worse than
            // useless.
            // Shown whenever the plugin is not actually talking to us, which
            // covers both a first pairing and a token that has gone stale.
            // Keying this off `isPaired` alone was a trap: the bridge can
            // believe it is paired while the plugin holds a dead token, and
            // then the one thing needed to recover is hidden.
            if !state.figmaConnected {
                Divider()
                VStack(alignment: .leading, spacing: 4) {
                    Text(state.isPaired ? "Pairing code" : "Pairing code")
                        .font(.system(size: 11, weight: .semibold))
                    Text("Type this into the plugin in Figma, once.")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    HStack(spacing: 8) {
                        Text(state.pairingCode)
                            .font(.system(size: 18, weight: .medium, design: .monospaced))
                            .tracking(4)
                            .textSelection(.enabled)
                        Spacer()
                        Button("New") { state.regenerateCode() }
                            .font(.system(size: 11))
                    }
                }
            }

            Divider()

            if let last = state.history.first {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Last transfer").font(.system(size: 11, weight: .semibold))
                    Text("\(last.nodeCount) layers · \(last.assetCount) assets · \(last.warningCount) warnings")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
            } else {
                Text("No transfers yet")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Divider()

            VStack(alignment: .leading, spacing: 3) {
                Button("Open Dashboard") { openWindow(id: "dashboard") }
                Button("Open DaVinci Resolve") { ResolveDetector.activate() }
                    .disabled(!state.resolve.installed)
                Button("Open Figma") { ResolveDetector.activateFigma() }
                Divider()
                Button("Quit") { NSApplication.shared.terminate(nil) }
            }
            .buttonStyle(.plain)
            .font(.system(size: 12))
        }
        .padding(12)
        .frame(width: 250)
    }
}

// MARK: - Dashboard

struct DashboardView: View {
    @ObservedObject var state: AppState

    // The selected tab lives on AppState rather than in a `@State` property,
    // because `@State` is a macro and macro plugins are not part of the
    // Command Line Tools SDK this project builds against.
    typealias Tab = AppState.Tab

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: Binding(
                get: { state.dashboardTab },
                set: { state.dashboardTab = $0 }
            )) {
                ForEach(Tab.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(12)

            Divider()

            ScrollView {
                Group {
                    switch state.dashboardTab {
                    case .status: StatusPane(state: state)
                    case .setup: SetupPane(state: state)
                    case .history: HistoryPane(state: state)
                    case .settings: SettingsPane(state: state)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            Divider()
            HStack {
                Text("All transfers stay on this Mac.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                Spacer()
                Text("v\(AppInfo.version) · schema \(AppInfo.schemaVersion)")
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 9)
        }
    }
}

struct StatusPane: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            GroupBox {
                VStack(alignment: .leading, spacing: 9) {
                    StatusRow(title: "Bridge", state: state.bridgeStatus,
                              detail: state.bridgeRunning ? "listening on 127.0.0.1:\(state.port)" : "stopped")
                    StatusRow(title: "Figma plugin", state: state.figmaStatus,
                              detail: state.figmaConnected ? "connected" : "not connected")
                    StatusRow(title: "DaVinci Resolve", state: state.resolveStatus,
                              detail: state.resolveDescription)
                    StatusRow(title: "Resolve scripts",
                              state: state.scriptsInstalled ? .connected : .error,
                              detail: state.scriptsInstalled ? "installed" : "not installed")
                }
                .padding(6)
            }

            if !state.figmaConnected {
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Pairing code").font(.headline)
                        Text("Open the plugin in Figma and type this code once.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                        HStack {
                            Text(state.pairingCode)
                                .font(.system(size: 26, weight: .medium, design: .monospaced))
                                .tracking(6)
                                .textSelection(.enabled)
                            Spacer()
                            Button("New code") { state.regenerateCode() }
                        }
                    }
                    .padding(6)
                }
            }

            if let error = state.lastError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.system(size: 12))
            }
        }
    }
}

struct SetupPane: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Setup").font(.title3.weight(.semibold))

            SetupStep(number: 1, title: "DaVinci Resolve",
                      done: state.resolve.installed,
                      detail: state.resolve.installed
                        ? "Found \(state.resolve.version ?? "") \(state.resolve.isStudio ? "Studio" : "Free")"
                        : "Install DaVinci Resolve, then press Refresh.")

            SetupStep(number: 2, title: "Resolve scripts",
                      done: state.scriptsInstalled,
                      detail: state.scriptsInstalled
                        ? "Installed in your Fusion Scripts folder."
                        : "Adds Receive commands to Workspace ▸ Scripts.") {
                Button(state.scriptsInstalled ? "Reinstall" : "Install scripts") {
                    state.installScripts()
                }
                .disabled(!state.resolve.installed)
            }

            SetupStep(number: 3, title: "Figma plugin",
                      done: state.figmaConnected,
                      detail: state.figmaConnected
                        ? "Paired and connected."
                        : "Run the plugin in Figma and enter the pairing code from the Status tab.")

            Divider().padding(.vertical, 4)

            Text("If Resolve was already running when you installed the scripts, restart it — "
                 + "Resolve only scans the Scripts folder at startup.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            Button("Refresh") { state.refresh() }
        }
    }
}

struct SetupStep<Action: View>: View {
    let number: Int
    let title: String
    let done: Bool
    let detail: String
    @ViewBuilder var action: () -> Action

    init(number: Int, title: String, done: Bool, detail: String,
         @ViewBuilder action: @escaping () -> Action = { EmptyView() }) {
        self.number = number
        self.title = title
        self.done = done
        self.detail = detail
        self.action = action
    }

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            ZStack {
                Circle()
                    .fill(done ? Color.green : Color.secondary.opacity(0.25))
                    .frame(width: 20, height: 20)
                if done {
                    Image(systemName: "checkmark")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.white)
                } else {
                    Text("\(number)").font(.system(size: 11, weight: .semibold))
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 13, weight: .medium))
                Text(detail)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            action()
        }
    }
}

struct HistoryPane: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Transfers").font(.title3.weight(.semibold))
                Spacer()
                Text("\(state.history.count)")
                    .foregroundStyle(.secondary)
            }

            if state.history.isEmpty {
                Text("Nothing has been sent yet. Select a frame in Figma and press Send to Fusion.")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            } else {
                ForEach(state.history) { record in
                    HStack(spacing: 10) {
                        Circle()
                            .fill(record.errorCount > 0 ? Color.red
                                  : record.warningCount > 0 ? Color.orange : Color.green)
                            .frame(width: 7, height: 7)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(record.documentName.isEmpty ? "Untitled" : record.documentName)
                                .font(.system(size: 12, weight: .medium))
                            Text("\(record.nodeCount) layers · \(record.assetCount) assets"
                                 + (record.durationMs > 0 ? " · \(record.durationMs) ms" : ""))
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(record.receivedAt, style: .time)
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                    }
                    .padding(.vertical, 3)
                    Divider()
                }
            }
        }
    }
}

struct SettingsPane: View {
    @ObservedObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Settings").font(.title3.weight(.semibold))

            GroupBox("Asset cache") {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Size on disk")
                        Spacer()
                        Text(state.cacheDescription).foregroundStyle(.secondary)
                    }
                    Text("Images are stored by content, so the same image used many times "
                         + "is kept once.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button("Reveal in Finder") {
                            NSWorkspace.shared.open(Paths.assets)
                        }
                        Button("Clear cache") { state.clearCache() }
                    }
                }
                .padding(6)
            }

            GroupBox("Security") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("The bridge listens only on 127.0.0.1 and requires a pairing code. "
                         + "Your designs never leave this Mac.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Button("Unpair Figma") { state.unpair() }
                }
                .padding(6)
            }

            GroupBox("Diagnostics") {
                HStack {
                    Button("Open log folder") { state.openLogs() }
                    Button("Export diagnostic report") { state.exportDiagnostics() }
                }
                .padding(6)
            }
        }
    }
}

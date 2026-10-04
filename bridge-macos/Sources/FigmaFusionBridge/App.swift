import AppKit
import BridgeCore
import SwiftUI

/// The application.
///
/// A menu-bar item is the whole interface by default — this is a background
/// utility, and a Dock icon plus a window for something that spends its life
/// waiting for a button press in another app would be noise. `LSUIElement` in
/// Info.plist is what makes that stick.
@main
struct FigmaFusionBridgeApp: App {
    @StateObject private var state = AppState.shared

    init() {
        // The server starts here, not from a view's `.task`.
        //
        // This is an LSUIElement app, so no window exists at launch — the
        // dashboard is only created when the user opens it. Hanging startup off
        // that window meant the bridge silently never began listening until
        // someone happened to open the dashboard, which is the one thing a
        // background helper must never do.
        Task { @MainActor in
            await Runtime.shared.start(state: AppState.shared)
        }
    }

    // `Runtime` is reached through a shared instance rather than `@State`.
    // `@State` is implemented as a compiler macro in current SDKs, and macro
    // plugins ship with Xcode rather than the Command Line Tools — so using it
    // would make the project unbuildable on a machine that has only the CLT.
    // Every property wrapper used here (`@StateObject`, `@ObservedObject`,
    // `@Published`, `@Environment`) is an ordinary type, not a macro.

    var body: some Scene {
        MenuBarExtra {
            MenuBarView(state: state)
        } label: {
            // Filled once everything is connected, outline while it is not, so
            // the state is readable at a glance in a monochrome menu bar.
            Image(systemName: state.bridgeRunning && state.figmaConnected
                  ? "arrow.triangle.branch.circle.fill"
                  : "arrow.triangle.branch")
        }
        .menuBarExtraStyle(.window)

        Window("Figma Fusion Bridge", id: "dashboard") {
            DashboardView(state: state)
                .frame(minWidth: 560, minHeight: 440)
                // start() is idempotent; this is a safety net, not the trigger.
                .task { await Runtime.shared.start(state: state) }
        }
        .windowResizability(.contentSize)
        .defaultSize(width: 620, height: 520)
    }
}

/// Owns the long-lived actors. Kept out of `AppState` so the UI type stays a
/// view model rather than a service locator.
@MainActor
final class Runtime {
    static let shared = Runtime()

    private var server: BridgeServer?
    private var started = false

    func start(state: AppState) async {
        guard !started else { return }
        started = true

        let session = Session()
        let transfers = TransferStore()
        let assets = AssetStore()
        state.attach(session: session, transfers: transfers, assets: assets)

        let server = BridgeServer(session: session, transfers: transfers, assets: assets, state: state)
        self.server = server

        do {
            let port = try await server.start()
            state.bridgeRunning = true
            state.port = port
            state.lastError = nil
        } catch {
            state.bridgeRunning = false
            state.lastError = "The bridge could not open a local port. "
                + "Another copy may already be running."
            BridgeLog.shared.error("app", "Startup failed: \(error.localizedDescription)")
        }

        state.startPolling()
        await state.refreshHistory()
    }
}

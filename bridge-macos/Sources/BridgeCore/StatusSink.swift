import Foundation

/// What the server needs from the interface.
///
/// The server used to hold a reference to the app's view model directly, which
/// meant the networking layer could not be built or tested without SwiftUI.
/// Narrowing that to a protocol keeps the dependency pointing the right way:
/// the app knows about the server, the server knows only about this.
@MainActor
public protocol BridgeStatusSink: AnyObject {
    func setFigmaConnected(_ value: Bool)
    func setResolveConnected(_ value: Bool)
    func noteClient(_ client: String?)
    func noteTransfer(_ record: TransferRecord)
    func statusSnapshot() -> BridgeSnapshot
    func refreshHistory() async
}

public struct BridgeSnapshot: Sendable {
    public var figmaConnected: Bool
    /// The Resolve application is running, from the detector.
    public var resolveRunning: Bool
    /// A Resolve script has contacted the bridge in this session.
    ///
    /// Distinct from `resolveRunning` on purpose. Whether a Fusion composition
    /// is open is something only a script running inside Resolve can know; the
    /// bridge cannot see it. Reporting "Fusion ready" from "the app is running"
    /// would be claiming knowledge we do not have.
    public var resolveScriptSeen: Bool
    public var lastTransferAt: Date?

    public init(figmaConnected: Bool, resolveRunning: Bool,
                resolveScriptSeen: Bool = false, lastTransferAt: Date?) {
        self.figmaConnected = figmaConnected
        self.resolveRunning = resolveRunning
        self.resolveScriptSeen = resolveScriptSeen
        self.lastTransferAt = lastTransferAt
    }

    public static let empty = BridgeSnapshot(figmaConnected: false, resolveRunning: false,
                                             resolveScriptSeen: false, lastTransferAt: nil)
}

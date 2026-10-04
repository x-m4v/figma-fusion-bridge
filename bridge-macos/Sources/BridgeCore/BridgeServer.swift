import Foundation
import Network

/// The local HTTP server.
///
/// Bound to the loopback interface and nothing else — `requiredLocalEndpoint`
/// is what enforces that, so the socket is not reachable from the network even
/// if the Mac's firewall is off. There is deliberately no option to bind
/// `0.0.0.0`.
///
/// Both loopback families are bound: `127.0.0.1` and `::1`. Figma's manifest
/// only accepts `localhost` in `allowedDomains` — literal IP addresses are
/// rejected — and `localhost` resolves to both, with Chromium free to try the
/// IPv6 address first. Binding IPv4 alone therefore works from curl, which
/// falls back, and intermittently fails from the plugin, which may not.
///
/// Why HTTP rather than a WebSocket for everything: the Resolve side runs in
/// DaVinci's embedded Python, where only the standard library can be assumed.
/// `urllib` is always there; a WebSocket client is not. A long poll over
/// loopback delivers as fast as a socket push and costs nothing while idle.
public actor BridgeServer {
    /// Tried in order. Short and deterministic so the port in the log is
    /// predictable enough for a user to reason about.
    public static let candidatePorts: [UInt16] = [8787, 8788, 8789, 8790, 8791]

    /// One per loopback family. IPv4 is required; IPv6 is best-effort, since a
    /// machine with IPv6 disabled must still work.
    private var listeners: [NWListener] = []
    private var connections: [ObjectIdentifier: NWConnection] = [:]
    private let queue = DispatchQueue(label: "ffbridge.server", attributes: .concurrent)

    private let session: Session
    private let transfers: TransferStore
    private let assets: AssetStore
    private weak var state: (any BridgeStatusSink)?

    public private(set) var boundPort: UInt16?

    public init(session: Session, transfers: TransferStore, assets: AssetStore, state: (any BridgeStatusSink)?) {
        self.session = session
        self.transfers = transfers
        self.assets = assets
        self.state = state
    }

    // MARK: - Lifecycle

    public func start() async throws -> UInt16 {
        for port in Self.candidatePorts {
            do {
                let bound = try await bind(port: port)
                await session.setPort(bound)
                try? await session.writeSessionFile()
                BridgeLog.shared.info("server", "Listening on 127.0.0.1:\(bound)")

                // Best-effort second family. A failure here is not fatal: IPv4
                // alone still serves every client, just less reliably from
                // Chromium-based hosts.
                do {
                    try await bindLoopbackV6(port: bound)
                    BridgeLog.shared.info("server", "Also listening on [::1]:\(bound)")
                } catch {
                    BridgeLog.shared.warn(
                        "server",
                        "IPv6 loopback unavailable on port \(bound); IPv4 only. \(error)")
                }

                boundPort = bound
                return bound
            } catch {
                BridgeLog.shared.debug("server", "Port \(port) unavailable, trying the next one")
                continue
            }
        }
        throw BridgeError.portUnavailable
    }

    private func bind(port: UInt16) async throws -> UInt16 {
        try await startListener(host: "127.0.0.1", port: port)
        return port
    }

    /// The IPv6 half. Separate so a failure can be caught without losing IPv4.
    private func bindLoopbackV6(port: UInt16) async throws {
        try await startListener(host: "::1", port: port)
    }

    private func startListener(host: String, port: UInt16) async throws {
        let params = NWParameters.tcp
        params.allowLocalEndpointReuse = true
        // The single most important line in the file: loopback only.
        params.requiredLocalEndpoint = NWEndpoint.hostPort(host: NWEndpoint.Host(host),
                                                           port: NWEndpoint.Port(rawValue: port)!)

        let listener = try NWListener(using: params)
        listeners.append(listener)

        // NWListener reports state from its own queue and can report more than
        // once (.waiting then .failed, say). A continuation resumed twice is a
        // crash, so the one-shot guard is a lock-protected box rather than a
        // captured var.
        let guardBox = ResumeGuard()
        return try await withCheckedThrowingContinuation { continuation in
            listener.stateUpdateHandler = { newState in
                switch newState {
                case .ready:
                    guard guardBox.claim() else { return }
                    continuation.resume()
                case .failed(let error), .waiting(let error):
                    guard guardBox.claim() else { return }
                    listener.cancel()
                    continuation.resume(throwing: error)
                default:
                    break
                }
            }
            listener.newConnectionHandler = { [weak self] connection in
                Task { await self?.accept(connection) }
            }
            listener.start(queue: queue)
        }
    }

    public func stop() async {
        for listener in listeners { listener.cancel() }
        listeners.removeAll()
        for connection in connections.values { connection.cancel() }
        connections.removeAll()
        await session.removeSessionFile()
        BridgeLog.shared.info("server", "Stopped")
    }

    // MARK: - Connections

    private func accept(_ connection: NWConnection) {
        connections[ObjectIdentifier(connection)] = connection
        connection.stateUpdateHandler = { [weak self] state in
            switch state {
            case .cancelled, .failed:
                Task { await self?.drop(connection) }
            default:
                break
            }
        }
        connection.start(queue: queue)
        Task { await self.pump(connection, parser: HTTPParser()) }
    }

    private func drop(_ connection: NWConnection) {
        connections.removeValue(forKey: ObjectIdentifier(connection))
    }

    /// Read, parse, dispatch, repeat.
    ///
    /// Recursive rather than a loop because `NWConnection` is callback-based;
    /// each completed request re-arms the read so keep-alive works and a long
    /// poll does not block other requests on the same connection.
    private func pump(_ connection: NWConnection, parser: HTTPParser) async {
        var parser = parser
        let readGuard = ResumeGuard()
        let chunk: Data? = await withCheckedContinuation { continuation in
            connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 20) { data, _, isComplete, error in
                guard readGuard.claim() else { return }
                if error != nil || (isComplete && (data?.isEmpty ?? true)) {
                    continuation.resume(returning: nil)
                } else {
                    continuation.resume(returning: data ?? Data())
                }
            }
        }

        guard let chunk else {
            connection.cancel()
            drop(connection)
            return
        }
        parser.append(chunk)

        while true {
            switch parser.next() {
            case .needMore:
                await pump(connection, parser: parser)
                return
            case .failed(let reason):
                BridgeLog.shared.warn("server", "Bad request: \(reason)")
                send(.error(400, reason), on: connection, close: true)
                return
            case .complete(let request, _):
                let response = await route(request)
                let keepAlive = request.wantsKeepAlive
                send(response, on: connection, close: !keepAlive)
                if !keepAlive { return }
            }
        }
    }

    private func send(_ response: HTTPResponse, on connection: NWConnection, close: Bool) {
        connection.send(content: response.serialize(), completion: .contentProcessed { _ in
            if close { connection.cancel() }
        })
    }

    // MARK: - Routing

    private func authorised(_ request: HTTPRequest) async -> Bool {
        await session.validate(request.header("X-FFBridge-Token"))
    }

    private func route(_ request: HTTPRequest) async -> HTTPResponse {
        if request.method == "OPTIONS" { return .empty(204) }

        switch (request.method, request.path) {

        // -- unauthenticated: discovery and pairing only --------------------

        case ("GET", "/api/hello"):
            // Deliberately says nothing about the user's work. Its whole job is
            // to let the plugin tell this port apart from any other listener.
            return .json([
                "app": "figma-fusion-bridge",
                "version": AppInfo.version,
                "schemaVersion": AppInfo.schemaVersion,
                "paired": await session.isPaired,
            ])

        case ("POST", "/api/pair"):
            guard let body = try? JSONSerialization.jsonObject(with: request.body) as? [String: Any],
                  let code = body["code"] as? String else {
                return .error(400, "Missing pairing code.")
            }
            guard let token = await session.pair(code: code) else {
                BridgeLog.shared.warn("server", "Rejected a pairing attempt with a wrong code")
                return .error(403, "That code is not right.")
            }
            BridgeLog.shared.info("server", "Figma plugin paired")
            await state?.setFigmaConnected(true)
            return .json(["token": token])

        // -- everything below requires the token ----------------------------

        default:
            guard await authorised(request) else {
                return .error(401, "This client is not paired with the bridge.")
            }
        }

        switch (request.method, request.path) {

        case ("GET", "/api/status"):
            await state?.noteClient(request.header("X-FFBridge-Client"))
            let snapshot = await state?.statusSnapshot() ?? BridgeSnapshot.empty
            return .json([
                "version": AppInfo.version,
                // The real pairing state. This used to be hardcoded true, which
                // disagreed with /api/hello and told the plugin it was paired
                // when it held no token.
                "paired": await session.isPaired,
                "figmaConnected": snapshot.figmaConnected,
                "resolveConnected": snapshot.resolveRunning,
                // Only a script inside Resolve can know a composition is open.
                "fusionReady": snapshot.resolveScriptSeen,
                "lastTransferAt": snapshot.lastTransferAt.map { ISO8601DateFormatter().string(from: $0) } ?? "",
            ])

        case ("POST", "/api/transfer"):
            return await acceptTransfer(request)

        case ("GET", "/api/transfer/latest"):
            guard let data = await transfers.latest() else {
                return .error(404, "There is nothing waiting to be received.")
            }
            await state?.setResolveConnected(true)
            return HTTPResponse(status: 200,
                                headers: ["Content-Type": "application/json; charset=utf-8"],
                                body: data)

        case ("GET", "/api/transfer/wait"):
            let seconds = min(Double(request.query["timeout"] ?? "30") ?? 30, 120)
            await state?.setResolveConnected(true)
            guard let data = await transfers.wait(seconds: seconds) else {
                return .error(404, "There is nothing waiting to be received.")
            }
            return HTTPResponse(status: 200,
                                headers: ["Content-Type": "application/json; charset=utf-8"],
                                body: data)

        case ("POST", "/api/transfer/report"):
            return await acceptReport(request)

        case ("POST", "/api/asset/known"):
            guard let body = try? JSONSerialization.jsonObject(with: request.body) as? [String: Any],
                  let ids = body["ids"] as? [String] else {
                return .error(400, "Expected a list of asset ids.")
            }
            return .json(["known": await assets.known(ids)])

        case ("POST", "/api/figma/pull"):
            // Reserved for Resolve-initiated pulls. Answering 404 rather than
            // failing means the Resolve script reports "nothing to receive",
            // which is accurate when no plugin is listening.
            return .error(404, "The Figma plugin is not listening for pull requests.")

        default:
            break
        }

        // -- asset transfer -------------------------------------------------

        if request.path.hasPrefix("/api/asset/") {
            let digest = String(request.path.dropFirst("/api/asset/".count))
            guard isHexDigest(digest) else { return .error(400, "Malformed asset id.") }

            if request.method == "PUT" {
                let filename = (request.header("X-FFBridge-Filename") ?? "").removingPercentEncoding ?? ""
                do {
                    _ = try await assets.store(request.body,
                                               digest: digest,
                                               mimeType: request.header("content-type") ?? "",
                                               filename: filename)
                    return .empty(201)
                } catch {
                    BridgeLog.shared.warn("assets", "Rejected upload \(digest.prefix(12)): \(error.localizedDescription)")
                    return .error(400, error.localizedDescription)
                }
            }
            if request.method == "GET" {
                guard let data = await assets.data(for: digest) else {
                    return .error(404, "That image is not in the cache.")
                }
                return .binary(data, contentType: "application/octet-stream")
            }
        }

        return .error(404, "Unknown endpoint.")
    }

    // MARK: - Handlers

    private func acceptTransfer(_ request: HTTPRequest) async -> HTTPResponse {
        guard let object = try? JSONSerialization.jsonObject(with: request.body) as? [String: Any] else {
            return .error(400, "The transfer was not valid JSON.")
        }
        guard let transferId = object["transferId"] as? String, !transferId.isEmpty else {
            return .error(400, "The transfer has no id.")
        }
        let schemaMajor = (object["schemaVersion"] as? String)
            .flatMap { $0.split(separator: ".").first }
            .map(String.init)
        guard schemaMajor == AppInfo.schemaMajor else {
            return .error(400, "This transfer uses an incompatible format version. "
                             + "Update the Figma plugin or the bridge so both match.")
        }

        let source = object["source"] as? [String: Any] ?? [:]
        let nodes = object["nodes"] as? [[String: Any]] ?? []
        let assetList = object["assets"] as? [[String: Any]] ?? []
        let diagnostics = object["diagnostics"] as? [[String: Any]] ?? []

        let record = TransferRecord(
            id: transferId,
            receivedAt: Date(),
            documentName: source["documentName"] as? String ?? "",
            frameName: (object["selection"] as? [String])?.first ?? "",
            nodeCount: nodes.count,
            assetCount: assetList.count,
            warningCount: diagnostics.filter { ($0["severity"] as? String) == "WARNING" }.count,
            errorCount: diagnostics.filter { ($0["severity"] as? String) == "ERROR" }.count,
            status: "pending",
            durationMs: 0,
            resolveProject: nil
        )

        await transfers.submit(request.body, record: record)
        await state?.noteTransfer(record)
        BridgeLog.shared.info("transfer",
                              "Received \(nodes.count) nodes, \(assetList.count) assets",
                              transferId: transferId)
        return .json(["transferId": transferId, "ok": true])
    }

    private func acceptReport(_ request: HTTPRequest) async -> HTTPResponse {
        guard let body = try? JSONSerialization.jsonObject(with: request.body) as? [String: Any],
              let id = body["transferId"] as? String else {
            return .error(400, "Expected a transfer id.")
        }
        let diagnostics = body["diagnostics"] as? [[String: Any]] ?? []
        await transfers.report(
            id: id,
            status: body["status"] as? String ?? "ok",
            nodeCount: body["nodeCount"] as? Int ?? 0,
            assetCount: body["assetCount"] as? Int ?? 0,
            warningCount: diagnostics.filter { ($0["severity"] as? String) == "WARNING" }.count,
            errorCount: diagnostics.filter { ($0["severity"] as? String) == "ERROR" }.count,
            durationMs: body["durationMs"] as? Int ?? 0
        )
        await state?.setResolveConnected(true)
        await state?.refreshHistory()
        BridgeLog.shared.info("transfer", "Resolve reported \(body["status"] as? String ?? "?")", transferId: id)
        return .json(["ok": true])
    }

    private func isHexDigest(_ value: String) -> Bool {
        value.count == 64 && value.allSatisfy { $0.isHexDigit }
    }
}

/// One-shot guard for continuations resumed from callback-based APIs.
/// `NWConnection` and `NWListener` both call back on their own queues and both
/// can fire more than once, which makes double-resume a real risk rather than a
/// theoretical one.
public final class ResumeGuard: @unchecked Sendable {
    private let lock = NSLock()
    private var claimed = false

    public func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        if claimed { return false }
        claimed = true
        return true
    }
}

public enum AppInfo {
    public static let version = "0.1.0"
    public static let schemaVersion = "1.0.0"
    public static let schemaMajor = "1"
}

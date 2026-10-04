import BridgeCore
import CryptoKit
import Foundation

// __SANDBOX__
// Point every store at a throwaway directory before anything touches disk.
//
// The suite creates sessions, pairs and unpairs them, and writes assets. Run
// against the real Application Support folder, that silently unpaired whoever
// had the bridge open. Tests must never write where the product lives.
private let sandboxRoot: String = {
    let dir = NSTemporaryDirectory() + "ffbridge-tests-" + UUID().uuidString
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    setenv(Paths.overrideEnvironmentKey, dir, 1)
    return dir
}()

// Forced before anything else: a lazy `let` would not run until first use, and
// by then a store may already have written to the real directory.
private let sandboxReady = sandboxRoot

_ = sandboxReady
let t = Harness()

// ---------------------------------------------------------------------------
// HTTP parsing — hand-rolled, so tested against the shapes it will really meet.
// ---------------------------------------------------------------------------

// Install into the test sandbox and verify the Lua payload, then repair and remove.
setenv("FFBRIDGE_SCRIPTS_DIR", sandboxRoot + "/Scripts", 1)
t.suite("Resolve installer")
let installed = Installer.install()
t.check("installer copies the complete payload", installed.ok, installed.errors.joined(separator: "; "))
t.equal("installer counts Lua menu commands", installed.installedScripts.count, 3)
t.check("installed state recognises Lua payload", Installer.isInstalled())
t.check("repair is repeatable", Installer.install().ok)
Installer.uninstall()
t.check("uninstall removes menu command and helper", !Installer.isInstalled())

t.suite("HTTP request parsing")

func parseOne(_ text: String) -> HTTPRequest? {
    var parser = HTTPParser()
    parser.append(Data(text.utf8))
    if case .complete(let request, _) = parser.next() { return request }
    return nil
}

if let r = parseOne("GET /api/status HTTP/1.1\r\nHost: x\r\n\r\n") {
    t.equal("parses the method", r.method, "GET")
    t.equal("parses the path", r.path, "/api/status")
    t.equal("parses a header", r.header("Host") ?? "", "x")
} else {
    t.check("parses a simple request", false)
}

if let r = parseOne("GET / HTTP/1.1\r\nX-FFBridge-Token: abc\r\n\r\n") {
    t.equal("header lookup ignores case", r.header("x-ffbridge-token") ?? "", "abc")
}

if let r = parseOne("GET /api/wait?timeout=30&x=a%20b HTTP/1.1\r\n\r\n") {
    t.equal("splits the query off the path", r.path, "/api/wait")
    t.equal("parses a query value", r.query["timeout"] ?? "", "30")
    t.equal("decodes percent escapes", r.query["x"] ?? "", "a b")
}

do {
    var parser = HTTPParser()
    parser.append(Data("POST /api/transfer HTTP/1.1\r\nContent-Length: 10\r\n\r\nabc".utf8))
    var incomplete = false
    if case .needMore = parser.next() { incomplete = true }
    t.check("a truncated body is not treated as complete", incomplete)

    parser.append(Data("defghij".utf8))
    var body = ""
    if case .complete(let request, _) = parser.next() {
        body = String(data: request.body, encoding: .utf8) ?? ""
    }
    t.equal("the body is reassembled once it arrives", body, "abcdefghij")
}

do {
    // What a multi-megabyte image upload actually looks like on the wire.
    let payload = Data(repeating: 0xAB, count: 300_000)
    var parser = HTTPParser()
    parser.append(Data("PUT /api/asset/x HTTP/1.1\r\nContent-Length: \(payload.count)\r\n\r\n".utf8))
    var offset = 0
    while offset < payload.count {
        let end = min(offset + 4096, payload.count)
        parser.append(payload[offset..<end])
        offset = end
    }
    var got = Data()
    if case .complete(let request, _) = parser.next() { got = request.body }
    t.check("a body split across many reads is reassembled intact", got == payload,
            "got \(got.count) of \(payload.count) bytes")
}

do {
    var parser = HTTPParser()
    parser.append(Data("GET /a HTTP/1.1\r\n\r\nGET /b HTTP/1.1\r\n\r\n".utf8))
    var first = "", second = ""
    if case .complete(let r, _) = parser.next() { first = r.path }
    if case .complete(let r, _) = parser.next() { second = r.path }
    t.check("two pipelined requests both parse", first == "/a" && second == "/b",
            "got \(first), \(second)")
}

do {
    var parser = HTTPParser()
    parser.append(Data("PUT /x HTTP/1.1\r\nContent-Length: 999999999999\r\n\r\n".utf8))
    var refused = false
    if case .failed = parser.next() { refused = true }
    t.check("an absurd Content-Length is refused, not allocated for", refused)
}

do {
    var parser = HTTPParser()
    parser.append(Data("GET / HTTP/1.1\r\n".utf8))
    parser.append(Data(repeating: 0x41, count: 70_000))
    var refused = false
    if case .failed = parser.next() { refused = true }
    t.check("an endless header is refused", refused)
}

t.check("keep-alive is the default", parseOne("GET / HTTP/1.1\r\n\r\n")?.wantsKeepAlive == true)
t.check("Connection: close is honoured",
        parseOne("GET / HTTP/1.1\r\nConnection: close\r\n\r\n")?.wantsKeepAlive == false)

// ---------------------------------------------------------------------------
// HTTP responses
// ---------------------------------------------------------------------------

t.suite("HTTP responses")

do {
    let text = String(data: HTTPResponse.text("hello").serialize(), encoding: .utf8)!
    t.check("status line is well formed", text.hasPrefix("HTTP/1.1 200 OK\r\n"))
    t.check("Content-Length is set", text.contains("Content-Length: 5"))
    t.check("body follows the headers", text.hasSuffix("hello"))
}

do {
    // A character count here would truncate every non-ASCII response.
    let text = String(data: HTTPResponse.text("Заголовок").serialize(), encoding: .utf8)!
    t.check("Content-Length counts bytes, not characters", text.contains("Content-Length: 18"))
}

do {
    let response = HTTPResponse.error(401, "not paired")
    let body = (try? JSONSerialization.jsonObject(with: response.body)) as? [String: String]
    t.equal("errors carry a machine-readable message", body?["error"] ?? "", "not paired")
    t.equal("errors carry their status", response.status, 401)
}

// ---------------------------------------------------------------------------
// Pairing — the only thing between a hostile local page and the user's Resolve.
// ---------------------------------------------------------------------------

t.suite("Pairing and authentication")

let sem = DispatchSemaphore(value: 0)
Task {
    do {
        let session = Session()
        let real = await session.currentCode()
        let wrong = real == "AAAAAA" ? "BBBBBB" : "AAAAAA"
        let refused = await session.pair(code: wrong)
        t.check("a wrong code is refused", refused == nil)
        let paired = await session.isPaired
        t.check("a refused attempt does not pair the client", !paired)
    }

    do {
        let session = Session()
        let code = await session.currentCode()
        let token = await session.pair(code: code)
        t.check("the right code returns a token", token != nil)
        t.equal("the token is a 256-bit hex string", token?.count ?? 0, 64)
    }

    do {
        let session = Session()
        let code = await session.currentCode()
        let token = await session.pair(code: "  \(code.lowercased())  ")
        t.check("the code tolerates case and stray whitespace", token != nil)
    }

    do {
        let session = Session()
        let code = await session.currentCode()
        let token = await session.pair(code: code)!
        let good = await session.validate(token)
        let bad = await session.validate(String(repeating: "0", count: 64))
        let missing = await session.validate(nil)
        t.check("the issued token validates", good)
        t.check("another token does not", !bad)
        t.check("a missing token does not", !missing)
    }

    do {
        let session = Session()
        let code = await session.currentCode()
        let token = await session.pair(code: code)!
        await session.unpairAll()
        let stillValid = await session.validate(token)
        t.check("unpairing invalidates the old token", !stillValid)
    }

    do {
        let session = Session()
        let old = await session.currentCode()
        _ = await session.regenerateCode()
        let token = await session.pair(code: old)
        t.check("regenerating the code invalidates the old one", token == nil)
    }

    do {
        // The user reads this off one window and types it into another.
        var ambiguous = false
        var wrongLength = false
        for _ in 0..<200 {
            let code = await Session().currentCode()
            if code.count != 6 { wrongLength = true }
            if code.contains(where: { "01OIL".contains($0) }) { ambiguous = true }
        }
        t.check("codes are six characters", !wrongLength)
        t.check("codes avoid characters that are easy to misread", !ambiguous)
    }

    t.check("constant-time compare still compares equal strings", constantTimeEquals("abc", "abc"))
    t.check("constant-time compare rejects a different string", !constantTimeEquals("abc", "abd"))
    t.check("constant-time compare rejects a different length", !constantTimeEquals("abc", "abcd"))

    // -----------------------------------------------------------------------
    // Asset store
    // -----------------------------------------------------------------------

    t.suite("Asset store")

    let tempRoot = URL(fileURLWithPath: NSTemporaryDirectory())
        .appendingPathComponent("ffbridge-tests-\(UUID().uuidString)")
    let store = AssetStore(root: tempRoot)
    defer { try? FileManager.default.removeItem(at: tempRoot) }

    let payload = Data("a real image would go here".utf8)
    let digest = sha256Hex(payload)

    do {
        let url = try? await store.store(payload, digest: digest, mimeType: "image/png", filename: "logo.png")
        t.check("stores an asset under its digest", url != nil)
        let has = await store.has(digest)
        t.check("reports the asset as present", has)
        let round = await store.data(for: digest)
        t.check("reads the same bytes back", round == payload)
    }

    do {
        // The same logo used twenty times must be one file, not twenty.
        let first = try? await store.store(payload, digest: digest, mimeType: "image/png", filename: "logo.png")
        let again = try? await store.store(payload, digest: digest, mimeType: "image/png", filename: "logo-copy.png")
        t.check("identical bytes deduplicate to one path", first?.path == again?.path)
    }

    do {
        // A truncated upload stored under the expected digest would be served
        // to every future transfer as though it were correct.
        var rejected = false
        do {
            _ = try await store.store(Data("different".utf8), digest: digest,
                                      mimeType: "image/png", filename: "x.png")
        } catch {
            rejected = true
        }
        t.check("bytes that do not match their checksum are rejected", rejected)
    }

    do {
        let known = await store.known([digest, String(repeating: "f", count: 64)])
        t.equal("known() reports only cached digests", known, [digest])
    }

    t.suite("Resolve detection")
    do {
        let info = ResolveDetector.detect()
        // This machine has Resolve installed; on one that does not, the check
        // below still holds because `installed` and `version` move together.
        t.check("detection is internally consistent",
                info.installed == (info.applicationURL != nil))
        if info.installed {
            t.check("a version was read from the bundle", info.version != nil,
                    "found \(info.version ?? "nil")")
        }
    }

    sem.signal()
}
sem.wait()

t.finish()

// MARK: - helpers

func sha256Hex(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

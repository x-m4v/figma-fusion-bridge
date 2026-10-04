import Foundation

/// A parsed HTTP request.
public struct HTTPRequest {
    public let method: String
    public let path: String
    public let query: [String: String]
    public let headers: [String: String]
    public let body: Data

    public func header(_ name: String) -> String? { headers[name.lowercased()] }

    public var contentLength: Int { Int(header("content-length") ?? "") ?? 0 }
    public var wantsKeepAlive: Bool {
        (header("connection") ?? "keep-alive").lowercased() != "close"
    }
}

/// A response to send back.
public struct HTTPResponse {
    public var status: Int = 200
    public var headers: [String: String] = [:]
    public var body: Data = Data()

    public static func json(_ object: Any, status: Int = 200) -> HTTPResponse {
        let data = (try? JSONSerialization.data(withJSONObject: object)) ?? Data("{}".utf8)
        return HTTPResponse(status: status,
                            headers: ["Content-Type": "application/json; charset=utf-8"],
                            body: data)
    }

    public static func text(_ string: String, status: Int = 200) -> HTTPResponse {
        HTTPResponse(status: status,
                     headers: ["Content-Type": "text/plain; charset=utf-8"],
                     body: Data(string.utf8))
    }

    public static func binary(_ data: Data, contentType: String) -> HTTPResponse {
        HTTPResponse(status: 200, headers: ["Content-Type": contentType], body: data)
    }

    public static func empty(_ status: Int) -> HTTPResponse { HTTPResponse(status: status) }

    public static func error(_ status: Int, _ message: String) -> HTTPResponse {
        .json(["error": message], status: status)
    }

    public func serialize() -> Data {
        var head = "HTTP/1.1 \(status) \(HTTPResponse.reason(status))\r\n"
        var all = headers
        all["Content-Length"] = String(body.count)
        // The plugin runs in a sandboxed iframe whose origin is opaque, so it
        // sends `Origin: null`. Allowing any origin here is safe only because
        // every endpoint that does anything is behind the pairing token — the
        // token, not CORS, is what stops a hostile page.
        all["Access-Control-Allow-Origin"] = "*"
        all["Access-Control-Allow-Headers"] = "Content-Type, X-FFBridge-Token, X-FFBridge-Client, X-FFBridge-Filename"
        all["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
        all["Access-Control-Max-Age"] = "600"
        for (key, value) in all { head += "\(key): \(value)\r\n" }
        head += "\r\n"
        return Data(head.utf8) + body
    }

    public static func reason(_ code: Int) -> String {
        switch code {
        case 200: return "OK"
        case 201: return "Created"
        case 204: return "No Content"
        case 400: return "Bad Request"
        case 401: return "Unauthorized"
        case 403: return "Forbidden"
        case 404: return "Not Found"
        case 408: return "Request Timeout"
        case 413: return "Payload Too Large"
        case 415: return "Unsupported Media Type"
        case 500: return "Internal Server Error"
        default: return "Status"
        }
    }
}

/// Incremental HTTP/1.1 request parser.
///
/// Incremental because asset uploads arrive in many TCP segments and a parser
/// that assumed one read per request would truncate every image above the MTU.
public struct HTTPParser {
    private var buffer = Data()

    public init() {}

    /// Refuses anything larger than this, so a malformed or hostile request
    /// cannot exhaust memory. Comfortably above any real design asset.
    public static let maxBodyBytes = 256 * 1024 * 1024

    public enum Outcome {
        case needMore
        case complete(HTTPRequest, consumed: Int)
        case failed(String)
    }

    public mutating func append(_ data: Data) { buffer.append(data) }

    public mutating func next() -> Outcome {
        guard let headerEnd = buffer.range(of: Data("\r\n\r\n".utf8)) else {
            return buffer.count > 64 * 1024 ? .failed("Header too large") : .needMore
        }

        let headerData = buffer[buffer.startIndex..<headerEnd.lowerBound]
        guard let headerText = String(data: headerData, encoding: .utf8) else {
            return .failed("Malformed header encoding")
        }

        var lines = headerText.components(separatedBy: "\r\n")
        guard !lines.isEmpty else { return .failed("Empty request") }

        let requestLine = lines.removeFirst().split(separator: " ", maxSplits: 2).map(String.init)
        guard requestLine.count >= 2 else { return .failed("Malformed request line") }

        var headers: [String: String] = [:]
        for line in lines {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let name = line[line.startIndex..<colon].trimmingCharacters(in: .whitespaces).lowercased()
            let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            headers[name] = value
        }

        let length = Int(headers["content-length"] ?? "0") ?? 0
        if length > HTTPParser.maxBodyBytes { return .failed("Body too large") }

        let bodyStart = headerEnd.upperBound
        let available = buffer.distance(from: bodyStart, to: buffer.endIndex)
        if available < length { return .needMore }

        let bodyEnd = buffer.index(bodyStart, offsetBy: length)
        let body = Data(buffer[bodyStart..<bodyEnd])

        let (path, query) = HTTPParser.splitQuery(requestLine[1])
        let request = HTTPRequest(
            method: requestLine[0].uppercased(),
            path: path,
            query: query,
            headers: headers,
            body: body
        )

        let consumed = buffer.distance(from: buffer.startIndex, to: bodyEnd)
        buffer.removeSubrange(buffer.startIndex..<bodyEnd)
        return .complete(request, consumed: consumed)
    }

    public static func splitQuery(_ target: String) -> (String, [String: String]) {
        guard let mark = target.firstIndex(of: "?") else { return (target, [:]) }
        let path = String(target[target.startIndex..<mark])
        var query: [String: String] = [:]
        for pair in target[target.index(after: mark)...].split(separator: "&") {
            let parts = pair.split(separator: "=", maxSplits: 1).map(String.init)
            guard let key = parts.first?.removingPercentEncoding else { continue }
            query[key] = parts.count > 1 ? (parts[1].removingPercentEncoding ?? parts[1]) : ""
        }
        return (path, query)
    }
}

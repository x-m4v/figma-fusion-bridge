import Foundation

/// A very small test harness.
///
/// XCTest ships with Xcode, not with the Command Line Tools, and this project
/// deliberately builds against the CLT so it can be built on a clean machine
/// and in a CI image without a full Xcode install. Rather than have a test
/// suite that cannot run here, the suite is an ordinary executable: it links
/// the library, asserts, prints, and exits non-zero on failure — which is all a
/// CI system needs from it.
public final class Harness {
    private var passed = 0
    private var failures: [String] = []
    private var currentSuite = ""

    public init() {}

    public func suite(_ name: String) {
        currentSuite = name
        print("\n\u{001B}[1m\(name)\u{001B}[0m")
    }

    public func check(_ name: String, _ condition: @autoclosure () -> Bool, _ detail: @autoclosure () -> String = "") {
        if condition() {
            passed += 1
            print("  ✓ \(name)")
        } else {
            let extra = detail()
            failures.append("\(currentSuite) › \(name)\(extra.isEmpty ? "" : " — \(extra)")")
            print("  ✗ \(name)\(extra.isEmpty ? "" : " — \(extra)")")
        }
    }

    public func equal<T: Equatable>(_ name: String, _ actual: T, _ expected: T) {
        check(name, actual == expected, "got \(actual), expected \(expected)")
    }

    public func close(_ name: String, _ actual: Double, _ expected: Double, tolerance: Double = 1e-9) {
        check(name, abs(actual - expected) <= tolerance, "got \(actual), expected \(expected)")
    }

    public func finish() -> Never {
        print("\n" + String(repeating: "─", count: 52))
        if failures.isEmpty {
            print("\u{001B}[32m\(passed) passed\u{001B}[0m")
            exit(0)
        }
        print("\u{001B}[31m\(failures.count) failed\u{001B}[0m, \(passed) passed\n")
        for failure in failures { print("  • \(failure)") }
        exit(1)
    }
}

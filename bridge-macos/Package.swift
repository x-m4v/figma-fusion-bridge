// swift-tools-version:5.9
import PackageDescription

// Three targets rather than one, for two reasons that turned out to be the same
// reason.
//
// Architecturally, the server, the stores and the installer have nothing to do
// with SwiftUI, and keeping them in a library makes that boundary real instead
// of aspirational.
//
// Practically, it is what lets the tests run. This project builds against the
// Command Line Tools, whose SDK ships neither the SwiftUI macro plugins nor
// XCTest — so the test suite is a plain executable that links the library and
// exits non-zero on failure. It runs anywhere Swift does, including CI images
// without Xcode.
let package = Package(
    name: "FigmaFusionBridge",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "FigmaFusionBridge", targets: ["FigmaFusionBridge"]),
        .library(name: "BridgeCore", targets: ["BridgeCore"]),
    ],
    targets: [
        .target(name: "BridgeCore", path: "Sources/BridgeCore"),
        .executableTarget(
            name: "FigmaFusionBridge",
            dependencies: ["BridgeCore"],
            path: "Sources/FigmaFusionBridge",
            swiftSettings: [.unsafeFlags(["-parse-as-library"])]
        ),
        .executableTarget(
            name: "BridgeTests",
            dependencies: ["BridgeCore"],
            path: "Sources/BridgeTests"
        ),
    ]
)

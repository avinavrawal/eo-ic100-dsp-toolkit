// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "EOIC100DSPTuner",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "EOIC100DSPTuner", targets: ["EOIC100DSPTuner"])],
    targets: [.executableTarget(name: "EOIC100DSPTuner")]
)

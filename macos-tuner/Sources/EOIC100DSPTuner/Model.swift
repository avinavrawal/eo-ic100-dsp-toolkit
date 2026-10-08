import Foundation

enum FilterType: Int, CaseIterable, Codable, Identifiable {
    case peak = 1, lowShelf = 0, highShelf = 2, lowPass = 3, highPass = 4
    var id: Int { rawValue }
    var title: String {
        switch self {
        case .peak: "Peak"
        case .lowShelf: "Low shelf"
        case .highShelf: "High shelf"
        case .lowPass: "Low pass"
        case .highPass: "High pass"
        }
    }
}

struct EQBand: Codable, Identifiable, Equatable {
    var id: Int
    var type: Int
    var frequency_hz: Double
    var gain_db: Double
    var q: Double
    var filter: FilterType { FilterType(rawValue: type) ?? .peak }
}

struct EQPreset: Codable, Equatable {
    var name: String
    var description: String
    var global_gain_db: Double
    var filters: [EQBand]

    static let diamond8 = EQPreset(
        name: "Diamond8",
        description: "Eight-band EO-IC100 internal EQ preset.",
        global_gain_db: -5.7,
        filters: [
            EQBand(id: 1, type: 1, frequency_hz: 199.9619903564453, gain_db: -6.099795818328857, q: 0.30000001192092896),
            EQBand(id: 2, type: 1, frequency_hz: 660.1016845703125, gain_db: 5.015218257904053, q: 0.6404694318771362),
            EQBand(id: 3, type: 2, frequency_hz: 1200, gain_db: 1.5575666427612305, q: 0.6051259636878967),
            EQBand(id: 4, type: 1, frequency_hz: 3456.447509765625, gain_db: -1.4372888803482056, q: 2.6809444427490234),
            EQBand(id: 5, type: 1, frequency_hz: 4909.03564453125, gain_db: 2.161358118057251, q: 2.987760543823242),
            EQBand(id: 6, type: 1, frequency_hz: 8423.484375, gain_db: 3.8687260150909424, q: 1.4768214225769043),
            EQBand(id: 7, type: 1, frequency_hz: 9002.74609375, gain_db: -1.9818049669265747, q: 8.060710906982422),
            EQBand(id: 8, type: 1, frequency_hz: 14655.1962890625, gain_db: -1.5634068250656128, q: 1.927000641822815)
        ])
}

enum PresetStore {
    static var directory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("EOIC100 DSP Tuner/Presets", isDirectory: true)
    }
    static func save(_ preset: EQPreset, to url: URL? = nil) throws -> URL {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let target = url ?? directory.appendingPathComponent("\(safeName(preset.name)).json")
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(preset).write(to: target, options: .atomic)
        return target
    }
    static func load(from url: URL) throws -> EQPreset {
        let value = try JSONDecoder().decode(EQPreset.self, from: Data(contentsOf: url))
        guard value.filters.count == 8 else { throw CocoaError(.fileReadCorruptFile) }
        return value
    }
    private static func safeName(_ value: String) -> String {
        let chars = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_ "))
        return String(value.unicodeScalars.filter(chars.contains)).trimmingCharacters(in: .whitespaces)
    }
}

enum Repository {
    static func locate() -> URL? {
        var candidates = [Bundle.main.bundleURL, URL(fileURLWithPath: FileManager.default.currentDirectoryPath)]
        while let current = candidates.first {
            if FileManager.default.fileExists(atPath: current.appendingPathComponent("patcher/patch_eq.py").path) { return current }
            candidates.removeFirst()
            let parent = current.deletingLastPathComponent()
            if parent == current || parent.path == "/" { continue }
            candidates.append(parent)
        }
        return nil
    }
}

enum TunerError: LocalizedError {
    case repositoryMissing, processFailed(String), unsafeOutput
    var errorDescription: String? {
        switch self {
        case .repositoryMissing: "Could not locate the EO-IC100 project folder. Launch this app from the project build, or open the repository first."
        case .processFailed(let text): text
        case .unsafeOutput: "Firmware generation output failed its expected hash and format checks."
        }
    }
}

enum FirmwareTools {
    static func run(_ script: String, arguments: [String], root: URL, timeout: TimeInterval = 1800) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [root.appendingPathComponent(script).path] + arguments
        process.currentDirectoryURL = root
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = root.path
        process.environment = environment
        let output = Pipe(); process.standardOutput = output; process.standardError = output
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let text = String(decoding: data, as: UTF8.self)
        guard process.terminationStatus == 0 else { throw TunerError.processFailed(text) }
        return text
    }
}

enum EQMath {
    static func response(preset: EQPreset, frequency: Double, sampleRate: Double = 48000) -> Double {
        var sum = preset.global_gain_db
        for band in preset.filters {
            let type = band.filter
            let f0 = min(max(band.frequency_hz, 20), sampleRate * 0.49)
            let w = 2 * Double.pi * f0 / sampleRate
            let c = cos(w), s = sin(w), A = pow(10, band.gain_db / 40)
            let alpha = s / (2 * max(band.q, 0.1))
            var b0: Double = 1, b1: Double = 0, b2: Double = 0
            var a0: Double = 1, a1: Double = 0, a2: Double = 0
            switch type {
            case .peak:
                b0 = 1 + alpha * A; b1 = -2*c; b2 = 1 - alpha*A
                a0 = 1 + alpha/A; a1 = -2*c; a2 = 1 - alpha/A
            case .lowPass:
                b0 = (1-c)/2; b1 = 1-c; b2 = (1-c)/2
                a0 = 1+alpha; a1 = -2*c; a2 = 1-alpha
            case .highPass:
                b0 = (1+c)/2; b1 = -(1+c); b2 = (1+c)/2
                a0 = 1+alpha; a1 = -2*c; a2 = 1-alpha
            case .lowShelf, .highShelf:
                let beta = 2 * sqrt(A) * alpha
                if type == .lowShelf {
                    b0=A*((A+1)-(A-1)*c+beta); b1=2*A*((A-1)-(A+1)*c); b2=A*((A+1)-(A-1)*c-beta)
                    a0=(A+1)+(A-1)*c+beta; a1 = -2*((A-1)+(A+1)*c); a2=(A+1)+(A-1)*c-beta
                } else {
                    b0=A*((A+1)+(A-1)*c+beta); b1 = -2*A*((A-1)+(A+1)*c); b2=A*((A+1)+(A-1)*c-beta)
                    a0=(A+1)-(A-1)*c+beta; a1=2*((A-1)-(A+1)*c); a2=(A+1)-(A-1)*c-beta
                }
            }
            let z1 = 2 * Double.pi * frequency / sampleRate
            func mag(_ x: Double, _ y: Double, _ z: Double, _ omega: Double) -> Double {
                let re = x + y*cos(omega) + z*cos(2*omega)
                let im = -y*sin(omega) - z*sin(2*omega)
                return hypot(re, im)
            }
            let numerator = mag(b0,b1,b2,z1), denominator = mag(a0,a1,a2,z1)
            if denominator > 0 && numerator > 0 { sum += 20 * log10(numerator / denominator) }
        }
        return sum
    }
}

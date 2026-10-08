import AppKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class TunerModel: ObservableObject, @unchecked Sendable {
    @Published var preset = EQPreset.diamond8
    @Published var selectedBand = 0
    @Published var output = "Ready. Generate an EQ image, then choose Install EQ to start the guided workflow."
    @Published var working = false
    @Published var firmwareHash: String?
    @Published var firmwareURL: URL?
    @Published var activeSession: URL?
    @Published var deviceSummary = UserDefaults.standard.string(forKey: "deviceSummary") ?? "Device not queried"
    @Published var phaseToConfirm: DevicePhase?
    @Published var privateDirectory: URL?
    @Published var installStep: InstallStep = .idle {
        didSet { UserDefaults.standard.set(installStep.rawValue, forKey: "installStep") }
    }
    @Published var switchSkipped = UserDefaults.standard.bool(forKey: "switchSkipped") {
        didSet { UserDefaults.standard.set(switchSkipped, forKey: "switchSkipped") }
    }
    @Published var switchCompleted = UserDefaults.standard.bool(forKey: "switchCompleted") {
        didSet { UserDefaults.standard.set(switchCompleted, forKey: "switchCompleted") }
    }
    @Published var recoveryOrigin = UserDefaults.standard.string(forKey: "recoveryOrigin") ?? "normal-B"

    var root: URL? { Repository.locate() }
    var privateAssets: URL? { privateDirectory ?? root?.appendingPathComponent("firmware/private") }
    var stagedReceiptExists: Bool {
        guard let activeSession else { return false }
        return FileManager.default.fileExists(atPath: activeSession.appendingPathComponent("stage/receipt.json").path)
    }

    init() {
        preset = EQPreset.diamond8
        if let raw = UserDefaults.standard.string(forKey: "installStep"), let saved = InstallStep(rawValue: raw) {
            installStep = saved
        }
        if let path = UserDefaults.standard.string(forKey: "generatedImage"), FileManager.default.fileExists(atPath: path) {
            firmwareURL = URL(fileURLWithPath: path)
            firmwareHash = UserDefaults.standard.string(forKey: "generatedImageHash")
        }
        if let path = UserDefaults.standard.string(forKey: "activeSession") { activeSession = URL(fileURLWithPath: path) }
        if let path = UserDefaults.standard.string(forKey: "privateDirectory") { privateDirectory = URL(fileURLWithPath: path) }
        resumeSavedWorkflow()
    }

    private func resumeSavedWorkflow() {
        let interrupted = installStep
        guard [.checking, .switchingA, .preparing, .staging, .activating, .recovering,
               .checkingReconnectA, .checkingReconnectB].contains(interrupted) else { return }
        guard let activeSession else {
            installStep = .attention
            output = "The app closed during an operation and its session record is missing. No operation was repeated. Detect the device and inspect its saved evidence before continuing."
            return
        }
        func receipt(_ phase: String) -> Bool {
            FileManager.default.fileExists(atPath: activeSession.appendingPathComponent("\(phase)/receipt.json").path)
        }
        switch interrupted {
        case .switchingA, .recovering:
            if receipt("recover") { installStep = .reconnectA }
            else { installStep = .attention }
        case .preparing:
            if receipt("prepare") { installStep = .needsStage }
            else { installStep = .attention }
        case .staging:
            if receipt("stage") { installStep = .needsActivation }
            else { installStep = .attention }
        case .activating:
            if receipt("activate") { installStep = .reconnectB }
            else { installStep = .attention }
        case .checkingReconnectA: installStep = .reconnectA
        case .checkingReconnectB: installStep = .reconnectB
        case .checking: installStep = .attention
        default: break
        }
        if installStep == .attention {
            output = "The app closed before a phase receipt was saved. No write phase was repeated. Inspect the saved log and current device state before continuing."
        } else {
            output = "Resumed from the last verified phase receipt. No USB operation was repeated. Continue only after the displayed device state is confirmed."
        }
    }

    func generate() {
        guard let root, let privateAssets else { output = "Repository or private firmware folder is unavailable."; return }
        do {
            let cache = root.appendingPathComponent("research/cache/tuner", isDirectory: true)
            try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
            let presetURL = cache.appendingPathComponent("active-preset.json")
            var generatedPreset = preset
            if generatedPreset != .diamond8 { generatedPreset.name = "Custom" }
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(generatedPreset).write(to: presetURL, options: .atomic)
            let image = cache.appendingPathComponent("eq-b.bin")
            let text = try FirmwareTools.run("tools/caps/tuner_firmware.py", arguments: [
                privateAssets.appendingPathComponent("stock_b.bin").path, presetURL.path, image.path
            ], root: root)
            let manifestURL = image.appendingPathExtension("json")
            let manifest = try JSONDecoder().decode(ImageReceipt.self, from: Data(contentsOf: manifestURL))
            guard manifest.output_sha256.count == 64,
                  try Data(contentsOf: image).count == 0x20004 else { throw TunerError.unsafeOutput }
            firmwareURL = image; firmwareHash = manifest.output_sha256
            activeSession = cache.appendingPathComponent("session-\(manifest.output_sha256.prefix(12))-\(Int(Date().timeIntervalSince1970))")
            UserDefaults.standard.set(image.path, forKey: "generatedImage")
            UserDefaults.standard.set(manifest.output_sha256, forKey: "generatedImageHash")
            UserDefaults.standard.set(activeSession?.path, forKey: "activeSession")
            installStep = .idle; switchCompleted = false; switchSkipped = false
            output = "Verified official input and generated slot-B image. SHA-256: \(manifest.output_sha256)\n\(text)"
        } catch { output = "Generation stopped: \(error.localizedDescription)" }
    }

    func detect() {
        guard let root, let privateAssets else { output = "Repository or local firmware assets are unavailable."; return }
        working = true
        let model = self
        Task.detached(priority: .userInitiated) {
            do {
                let cache = root.appendingPathComponent("research/cache/tuner/device-query", isDirectory: true)
                try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
                let result = try FirmwareTools.run("tools/caps/tuner_device.py", arguments: [
                    "query", "--private", privateAssets.path, "--session", cache.path
                ], root: root)
                await MainActor.run { model.deviceSummary = result; UserDefaults.standard.set(result, forKey: "deviceSummary"); model.output = result; model.working = false }
            } catch {
                await MainActor.run { model.output = "Read-only query stopped: \(error.localizedDescription)"; model.working = false }
            }
        }
    }

    func startInstall() {
        guard let root, let privateAssets, let firmwareURL, let activeSession else {
            output = "Generate an EQ image first; the app will verify its hash and the preserved stock A assets before detection."
            return
        }
        working = true; installStep = .checking
        let model = self
        Task.detached(priority: .userInitiated) {
            do {
                let preflight = try FirmwareTools.run("tools/caps/tuner_package.py", arguments: [
                    "check", "--private", privateAssets.path, "--image", firmwareURL.path, "--session", activeSession.path
                ], root: root)
                let queryDir = activeSession.appendingPathComponent("initial-detect", isDirectory: true)
                try FileManager.default.createDirectory(at: queryDir, withIntermediateDirectories: true)
                let query = try FirmwareTools.run("tools/caps/tuner_device.py", arguments: [
                    "query", "--private", privateAssets.path, "--session", queryDir.path
                ], root: root)
                await MainActor.run {
                    model.deviceSummary = query; UserDefaults.standard.set(query, forKey: "deviceSummary")
                    model.output = preflight + "\n" + query
                    model.switchCompleted = false
                    if query.contains("ACTIVE_SLOT=B ") {
                        model.switchSkipped = false; model.installStep = .needsSwitchA
                    } else if query.contains("ACTIVE_SLOT=A ") {
                        model.switchSkipped = true; model.installStep = .needsPrepare
                    } else {
                        model.installStep = .attention
                        model.output += "\nInstall stopped: running slot is unknown."
                    }
                    model.working = false
                }
            } catch {
                await MainActor.run { model.installStep = .attention; model.output = "Install preflight stopped: \(error.localizedDescription)"; model.working = false }
            }
        }
    }

    func requestNextAction() {
        switch installStep {
        case .needsSwitchA: phaseToConfirm = .switchToA
        case .needsPrepare: phaseToConfirm = .prepareStage
        case .needsStage: phaseToConfirm = .stage
        case .needsActivation: phaseToConfirm = .activate
        default: break
        }
    }

    func runConfirmed(_ phase: DevicePhase) {
        guard let root, let privateAssets, let firmwareURL, let activeSession else { return }
        if let expected = phase.expectedStep, installStep != expected { return }
        if phase == .stage && !stagedPrepareExists { output = "Staging is blocked until the complete flash capture proved A, B, and both flags."; return }
        if phase == .activate && !stagedReceiptExists { output = "Activation is blocked until full B readback verification succeeds."; return }
        switch phase {
        case .switchToA: installStep = .switchingA
        case .prepareStage: installStep = .preparing
        case .stage: installStep = .staging
        case .activate: installStep = .activating
        case .recover: installStep = .recovering
        }
        working = true
        let selectedRecoveryOrigin = recoveryOrigin
        let model = self
        Task.detached(priority: .userInitiated) {
            do {
                var arguments = [phase.packagePhase, "--private", privateAssets.path,
                                 "--image", firmwareURL.path, "--session", activeSession.path]
                if let confirm = phase.confirmation { arguments += ["--confirm", confirm] }
                if phase == .switchToA { arguments += ["--origin", "normal-B"] }
                if phase == .recover { arguments += ["--origin", selectedRecoveryOrigin] }
                let text = try FirmwareTools.run("tools/caps/tuner_package.py", arguments: arguments, root: root)
                await MainActor.run {
                    model.output = text
                    switch phase {
                    case .switchToA: model.switchCompleted = true; model.installStep = .reconnectA
                    case .prepareStage: model.installStep = .needsStage
                    case .stage: model.installStep = .needsActivation
                    case .activate: model.installStep = .reconnectB
                    case .recover: model.installStep = .reconnectA
                    }
                    model.working = false
                }
            } catch {
                await MainActor.run { model.installStep = .attention; model.output = "\(phase.title) stopped. No automatic retry was made. Inspect the saved phase log before another operation.\n\(error.localizedDescription)"; model.working = false }
            }
        }
    }

    var stagedPrepareExists: Bool {
        guard let activeSession else { return false }
        return FileManager.default.fileExists(atPath: activeSession.appendingPathComponent("prepare/receipt.json").path)
    }

    func verifyReconnect(slot: String) {
        guard let root, let privateAssets, let activeSession else { return }
        let expected: InstallStep = slot == "A" ? .reconnectA : .reconnectB
        guard installStep == expected else { return }
        installStep = slot == "A" ? .checkingReconnectA : .checkingReconnectB
        working = true; let model = self
        Task.detached(priority: .userInitiated) {
            do {
                let dir = activeSession.appendingPathComponent("reconnect-\(slot)-\(Int(Date().timeIntervalSince1970))", isDirectory: true)
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let result = try FirmwareTools.run("tools/caps/tuner_device.py", arguments: [
                    "wait-normal", "--private", privateAssets.path, "--session", dir.path,
                    "--expect-slot", slot, "--timeout", "30"
                ], root: root)
                await MainActor.run {
                    model.deviceSummary = result; UserDefaults.standard.set(result, forKey: "deviceSummary")
                    model.output = result
                    model.installStep = slot == "A" ? .needsPrepare : .complete
                    model.working = false
                }
            } catch {
                await MainActor.run {
                    model.installStep = expected
                    model.output = "Reconnect verification did not pass. No write or reboot was attempted. Reconnect normally, then check again.\n\(error.localizedDescription)"
                    model.working = false
                }
            }
        }
    }

    func requestRecovery() {
        guard let root, let privateAssets, firmwareURL != nil, let activeSession else {
            output = "Generate and verify a firmware image before recovery."
            return
        }
        working = true; let model = self
        Task.detached(priority: .userInitiated) {
            do {
                let dir = activeSession.appendingPathComponent("recovery-detect-\(Int(Date().timeIntervalSince1970))", isDirectory: true)
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let state = try FirmwareTools.run("tools/caps/tuner_device.py", arguments: [
                    "state", "--private", privateAssets.path, "--session", dir.path
                ], root: root)
                await MainActor.run {
                    model.output = state
                    if state.contains("STATE=NORMAL") && state.contains("ACTIVE_SLOT=B ") {
                        model.recoveryOrigin = "normal-B"; UserDefaults.standard.set("normal-B", forKey: "recoveryOrigin")
                        model.phaseToConfirm = .recover
                    } else if state.contains("STATE=PROGRAMMER") {
                        model.recoveryOrigin = "programmer"; UserDefaults.standard.set("programmer", forKey: "recoveryOrigin")
                        model.phaseToConfirm = .recover
                    } else {
                        model.output += "\nRecovery is available only after a unique known B or programmer identity is visible. No write was attempted."
                    }
                    model.working = false
                }
            } catch {
                await MainActor.run { model.output = "Recovery preflight stopped without writing: \(error.localizedDescription)"; model.working = false }
            }
        }
    }

    func loadPreset() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do { preset = try PresetStore.load(from: url); output = "Loaded preset: \(preset.name)" }
        catch { output = "Could not load preset: \(error.localizedDescription)" }
    }

    func savePreset() {
        let panel = NSSavePanel(); panel.allowedContentTypes = [.json]
        panel.nameFieldStringValue = "\(preset.name).json"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do { let saved = try PresetStore.save(preset, to: url); output = "Saved preset: \(saved.path)" }
        catch { output = "Could not save preset: \(error.localizedDescription)" }
    }

    func choosePrivateAssets() {
        let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK else { return }
        privateDirectory = panel.url
        UserDefaults.standard.set(panel.url?.path, forKey: "privateDirectory")
        output = "Selected local private firmware folder. Its assets will be hash-checked before use."
    }
}

private struct ImageReceipt: Decodable {
    let output_sha256: String
}

enum InstallStep: String {
    case idle, checking, needsSwitchA, switchingA, reconnectA, needsPrepare, preparing
    case needsStage, staging, needsActivation, activating, reconnectB, complete
    case checkingReconnectA, checkingReconnectB, recovering, attention

    var currentIndex: Int {
        switch self {
        case .idle, .checking, .attention: 0
        case .needsSwitchA: 1
        case .switchingA: 2
        case .reconnectA, .checkingReconnectA: 3
        case .needsPrepare, .preparing: 1
        case .needsStage, .staging: 4
        case .needsActivation: 5
        case .activating: 6
        case .reconnectB, .checkingReconnectB: 7
        case .complete: 9
        case .recovering: 1
        }
    }
    var prompt: String {
        switch self {
        case .idle: "Ready to install"
        case .checking: "Checking hashes and detecting device…"
        case .needsSwitchA: "B is running. Verify A and switch selection to recovery A."
        case .switchingA: "Verifying A and boot flags, then switching to A…"
        case .reconnectA: "Physically unplug for 15 seconds, reconnect, then verify recovery A."
        case .needsPrepare: "Enter programmer and verify recovery A and inactive B."
        case .preparing: "Entering programmer and reading full flash…"
        case .needsStage: "Recovery A and inactive B are verified. Confirm B-only staging."
        case .staging: "Writing only B; full readback and flash comparison in progress…"
        case .needsActivation: "B readback passed. Confirm the separate boot selection change."
        case .activating: "Rechecking A/B and flags, then activating B…"
        case .reconnectB: "Physically unplug for 15 seconds, reconnect, then verify B."
        case .checkingReconnectA, .checkingReconnectB: "Waiting for normal USB and checking firmware…"
        case .complete: "Install verified: normal B, CHECK, USB audio, and HID passed."
        case .recovering: "Separately approved recovery to A is in progress…"
        case .attention: "Install paused. No failed write phase is retried automatically."
        }
    }
}

enum DevicePhase: String, Identifiable {
    case switchToA, prepareStage, stage, activate, recover
    var id: String { rawValue }
    var title: String {
        switch self {
        case .switchToA: "Switch boot selection to recovery A"
        case .prepareStage: "Enter programmer and verify flash"
        case .stage: "Write EQ firmware to inactive B"
        case .activate: "Activate verified B"
        case .recover: "Recover to verified stock A"
        }
    }
    var packagePhase: String {
        switch self { case .switchToA, .recover: "recover"; case .prepareStage: "prepare-stage"; case .stage: "stage"; case .activate: "activate" }
    }
    var confirmation: String? {
        switch self {
        case .switchToA: "RECOVER-VERIFIED-A"
        case .prepareStage: nil
        case .stage: "STAGE-EQ-B"
        case .activate: "ACTIVATE-EQ-B"
        case .recover: "RECOVER-VERIFIED-A"
        }
    }
    var expectedStep: InstallStep? {
        switch self {
        case .switchToA: .needsSwitchA
        case .prepareStage: .needsPrepare
        case .stage: .needsStage
        case .activate: .needsActivation
        case .recover: nil
        }
    }
    var details: String {
        switch self {
        case .switchToA: "This sends the known FW_UPDATE → SYS_REBOOT transition to enter programmer mode, reads the complete flash, verifies recovery A and both boot flags, then changes only the active B→A selection. No image is written. This is a software transition into programmer mode; after the flag readback, you must physically unplug for 15 seconds. No software reboot follows the flag write."
        case .prepareStage: "This uses the known FW_UPDATE → SYS_REBOOT path and reads the full 512 KiB flash. It does not write flash or boot flags. The next step asks separately before any B erase/write."
        case .stage: "This writes only inactive B and its validity marker. It rechecks that the full flash still matches the preflight capture, reads all of B back byte-for-byte, and verifies A, flags, and every byte outside B. Cancel now to leave firmware unchanged."
        case .activate: "This rechecks complete recovery A and staged B, backs up the previous A selection, changes only the active flag to B, and verifies both flags. It does not reboot. Cancel now to keep A active."
        case .recover: "This separately verifies the complete preserved recovery A against flash, verifies boot flags, and changes only active selection to A. It never writes either image and does not reboot."
        }
    }
}

struct TunerView: View {
    @StateObject private var model = TunerModel()
    @State private var showConfirm = false
    private var selected: Binding<EQBand> {
        Binding(get: { model.preset.filters[model.selectedBand] }, set: { model.preset.filters[model.selectedBand] = $0 })
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            HStack(spacing: 18) {
                VStack(spacing: 14) {
                    ResponseGraph(preset: $model.preset, selectedBand: $model.selectedBand)
                        .frame(height: 340)
                    HStack {
                        Text("Global preamp").font(.headline)
                        Slider(value: $model.preset.global_gain_db, in: -24...12, step: 0.1)
                        Text("\(model.preset.global_gain_db, specifier: "%+.1f") dB").monospacedDigit().frame(width: 70, alignment: .trailing)
                    }
                    bandPicker
                }
                .frame(maxWidth: .infinity)
                bandEditor.frame(width: 290)
            }
            .padding(18)
            Divider()
            devicePanel
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .confirmationDialog(model.phaseToConfirm?.title ?? "Confirm device operation", isPresented: $showConfirm, titleVisibility: .visible, presenting: model.phaseToConfirm) { phase in
            Button(phase.title, role: .destructive) { model.runConfirmed(phase); model.phaseToConfirm = nil }
            Button("Cancel", role: .cancel) { model.phaseToConfirm = nil }
        } message: { phase in Text(phase.details) }
        .onChange(of: model.phaseToConfirm) { value in showConfirm = value != nil }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "slider.horizontal.3").font(.system(size: 25, weight: .semibold)).foregroundStyle(Color.accentColor)
            VStack(alignment: .leading, spacing: 2) {
                Text("EO-IC100 DSP Tuner").font(.title2.bold())
                Text("Eight-band firmware EQ · official Samsung 0.23 input").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Diamond8") { model.preset = .diamond8 }
            Button("Load…") { model.loadPreset() }
            Button("Save…") { model.savePreset() }
            Button("Generate firmware") { model.generate() }.disabled(model.working)
            Button("Install EQ") { model.startInstall() }.buttonStyle(.borderedProminent).disabled(model.working || model.firmwareURL == nil)
        }
        .padding(.horizontal, 20).padding(.vertical, 14)
    }

    private var bandPicker: some View {
        HStack(spacing: 6) {
            ForEach(0..<8, id: \.self) { index in
                Button {
                    model.selectedBand = index
                } label: {
                    VStack(spacing: 4) {
                        Text("B\(index + 1)").font(.headline)
                        Text("\(model.preset.filters[index].frequency_hz, format: .number.precision(.fractionLength(0))) Hz")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 8)
                    .background(model.selectedBand == index ? Color.accentColor.opacity(0.15) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
                }.buttonStyle(.plain)
            }
        }
    }

    private var bandEditor: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Band \(model.selectedBand + 1)").font(.title3.bold())
            Picker("Filter", selection: Binding(get: { selected.wrappedValue.filter }, set: { selected.wrappedValue.type = $0.rawValue })) {
                ForEach(FilterType.allCases) { type in Text(type.title).tag(type) }
            }
            valueEditor("Frequency", value: Binding(get: { selected.wrappedValue.frequency_hz }, set: { selected.wrappedValue.frequency_hz = $0 }), range: 20...20000, step: 1, suffix: "Hz", logarithmic: true)
            valueEditor("Gain", value: Binding(get: { selected.wrappedValue.gain_db }, set: { selected.wrappedValue.gain_db = $0 }), range: -18...18, step: 0.1, suffix: "dB")
            valueEditor("Q", value: Binding(get: { selected.wrappedValue.q }, set: { selected.wrappedValue.q = $0 }), range: 0.1...10, step: 0.01, suffix: "")
            Spacer(minLength: 4)
            Text("Stored in firmware as eight coefficient-generation parameters. The graph previews the standard biquad response.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(14).background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
    }

    private func valueEditor(_ title: String, value: Binding<Double>, range: ClosedRange<Double>, step: Double, suffix: String, logarithmic: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack { Text(title).font(.subheadline.weight(.medium)); Spacer(); Text("\(value.wrappedValue, specifier: title == "Frequency" ? "%.0f" : "%.2f") \(suffix)").monospacedDigit().foregroundStyle(.secondary) }
            if logarithmic {
                Slider(value: Binding(get: {
                    log(max(value.wrappedValue, range.lowerBound) / range.lowerBound) / log(range.upperBound / range.lowerBound)
                }, set: {
                    value.wrappedValue = range.lowerBound * pow(range.upperBound / range.lowerBound, $0)
                }), in: 0...1)
            } else {
                Slider(value: value, in: range, step: step)
            }
        }
    }

    private var devicePanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "cable.connector").foregroundStyle(.secondary)
                Text("Device & firmware").font(.headline)
                Spacer()
                if model.working { ProgressView().controlSize(.small) }
                Button("Detect / query") { model.detect() }.disabled(model.working)
                Button("Private assets…") { model.choosePrivateAssets() }
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), alignment: .leading), count: 3), alignment: .leading, spacing: 8) {
                ForEach(Array(progressTitles.enumerated()), id: \.offset) { index, title in
                    let state = progressState(index)
                    HStack(spacing: 6) {
                        Image(systemName: state == .done ? "checkmark.circle.fill" : state == .skipped ? "minus.circle" : state == .current ? "arrow.right.circle.fill" : "circle")
                            .foregroundStyle(state == .done ? Color.green : state == .current ? Color.accentColor : Color.secondary)
                        Text(title).font(.caption).lineLimit(1)
                        if state == .skipped { Text("skipped").font(.caption2).foregroundStyle(.secondary) }
                    }
                }
            }
            HStack {
                Text(model.installStep.prompt).font(.callout.weight(.medium)).frame(maxWidth: .infinity, alignment: .leading)
                workflowAction
                Button("Recovery to stock A…") { model.requestRecovery() }.disabled(model.working || model.firmwareURL == nil)
            }
            HStack(alignment: .top, spacing: 16) {
                Text(model.deviceSummary).font(.system(.caption, design: .monospaced)).frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.firmwareHash.map { "Image SHA-256: \($0)" } ?? "No generated image")
                        .font(.system(.caption2, design: .monospaced)).textSelection(.enabled)
                }.frame(width: 500, alignment: .leading)
            }
            ScrollView {
                Text(model.output).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(8)
            }.frame(height: 92).background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 7))
        }
        .padding(.horizontal, 20).padding(.vertical, 12)
    }

    private let progressTitles = ["Detect device", "Verify recovery", "Switch to A", "Reconnect", "Stage EQ to B", "Verify firmware", "Activate B", "Reconnect", "Verify installation"]
    private enum ProgressState { case done, current, pending, skipped }
    private func progressState(_ index: Int) -> ProgressState {
        if model.switchSkipped && (index == 2 || index == 3) { return .skipped }
        if model.installStep == .complete { return .done }
        let current = model.installStep.currentIndex
        if index < current { return .done }
        if index == current { return .current }
        return .pending
    }
    @ViewBuilder private var workflowAction: some View {
        switch model.installStep {
        case .needsSwitchA, .needsPrepare, .needsStage, .needsActivation:
            Button("Continue…") { model.requestNextAction() }.buttonStyle(.borderedProminent).disabled(model.working)
        case .reconnectA:
            Button("I unplugged for 15 seconds and reconnected · Verify A") { model.verifyReconnect(slot: "A") }.buttonStyle(.borderedProminent).disabled(model.working)
        case .reconnectB:
            Button("I unplugged for 15 seconds and reconnected · Verify B") { model.verifyReconnect(slot: "B") }.buttonStyle(.borderedProminent).disabled(model.working)
        case .complete:
            Label("Installation successful", systemImage: "checkmark.seal.fill").foregroundStyle(.green)
        default:
            EmptyView()
        }
    }
}

private struct ResponseGraph: View {
    @Binding var preset: EQPreset
    @Binding var selectedBand: Int
    private let minHz = 20.0, maxHz = 20000.0, minDb = -24.0, maxDb = 24.0

    var body: some View {
        GeometryReader { geometry in
            Canvas { context, size in
                let rect = CGRect(x: 42, y: 10, width: size.width - 54, height: size.height - 34)
                func x(_ hz: Double) -> CGFloat { rect.minX + CGFloat(log(hz/minHz) / log(maxHz/minHz)) * rect.width }
                func y(_ db: Double) -> CGFloat { rect.maxY - CGFloat((db-minDb)/(maxDb-minDb)) * rect.height }
                for db in stride(from: -20.0, through: 20.0, by: 10) {
                    var grid = Path(); grid.move(to: CGPoint(x: rect.minX, y: y(db))); grid.addLine(to: CGPoint(x: rect.maxX, y: y(db)))
                    context.stroke(grid, with: .color(db == 0 ? .secondary : .secondary.opacity(0.22)), lineWidth: db == 0 ? 1 : 0.5)
                    context.draw(Text("\(Int(db)) dB").font(.system(size: 10)).foregroundColor(.secondary), at: CGPoint(x: 20, y: y(db)))
                }
                for hz in [20.0, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000] {
                    var grid = Path(); grid.move(to: CGPoint(x: x(hz), y: rect.minY)); grid.addLine(to: CGPoint(x: x(hz), y: rect.maxY))
                    context.stroke(grid, with: .color(.secondary.opacity(0.15)), lineWidth: 0.5)
                    let label = hz >= 1000 ? "\(Int(hz/1000))k" : "\(Int(hz))"
                    context.draw(Text(label).font(.system(size: 9)).foregroundColor(.secondary), at: CGPoint(x: x(hz), y: rect.maxY + 12))
                }
                var response = Path()
                for i in 0...360 {
                    let hz = minHz * pow(maxHz/minHz, Double(i)/360)
                    let point = CGPoint(x: x(hz), y: y(min(max(EQMath.response(preset: preset, frequency: hz), minDb), maxDb)))
                    if i == 0 { response.move(to: point) } else { response.addLine(to: point) }
                }
                context.stroke(response, with: .color(.accentColor), style: StrokeStyle(lineWidth: 2.4, lineCap: .round, lineJoin: .round))
                for (i, band) in preset.filters.enumerated() {
                    let point = CGPoint(x: x(band.frequency_hz), y: y(min(max(EQMath.response(preset: preset, frequency: band.frequency_hz), minDb), maxDb)))
                    let r: CGFloat = i == selectedBand ? 6 : 4
                    context.fill(Path(ellipseIn: CGRect(x: point.x-r, y: point.y-r, width: r*2, height: r*2)), with: .color(i == selectedBand ? .orange : .accentColor))
                }
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { gesture in
                guard let near = preset.filters.enumerated().min(by: { abs(log($0.element.frequency_hz)-log(max(minHz, frequency(at: gesture.location.x, width: geometry.size.width)))) < abs(log($1.element.frequency_hz)-log(max(minHz, frequency(at: gesture.location.x, width: geometry.size.width)))) }) else { return }
                if selectedBand != near.offset { selectedBand = near.offset }
                let i = selectedBand
                let f = frequency(at: gesture.location.x, width: geometry.size.width)
                let current = EQMath.response(preset: preset, frequency: preset.filters[i].frequency_hz)
                let target = decibels(at: gesture.location.y, height: geometry.size.height)
                preset.filters[i].frequency_hz = f
                preset.filters[i].gain_db = min(max(preset.filters[i].gain_db + target - current, -18), 18)
            })
            .overlay(alignment: .topLeading) { Text("Frequency response · 48 kHz reference").font(.caption).foregroundStyle(.secondary).padding(.leading, 43).padding(.top, 8) }
        }
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
    }

    private func frequency(at x: CGFloat, width: CGFloat) -> Double {
        let normalized = min(max((x - 42) / max(width - 54, 1), 0), 1)
        return minHz * pow(maxHz/minHz, Double(normalized))
    }
    private func decibels(at y: CGFloat, height: CGFloat) -> Double {
        let top: CGFloat = 10, plotHeight = max(height - 34, 1)
        return maxDb - Double((y - top) / plotHeight) * (maxDb - minDb)
    }
}

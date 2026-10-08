import SwiftUI

@main
struct EOIC100DSPTunerApp: App {
    var body: some Scene {
        WindowGroup {
            TunerView().frame(minWidth: 1040, minHeight: 760)
        }
        .windowResizability(.contentSize)
    }
}

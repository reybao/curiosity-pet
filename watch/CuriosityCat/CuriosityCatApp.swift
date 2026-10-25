import SwiftUI

@main
struct CuriosityCatApp: App {
    @StateObject private var model = PetModel()

    var body: some Scene {
        WindowGroup {
            if model.isPaired {
                ContentView().environmentObject(model)
            } else {
                PairingView().environmentObject(model)
            }
        }
    }
}

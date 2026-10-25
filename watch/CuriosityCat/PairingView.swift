import SwiftUI

/// First run: a grown-up runs `uv run pet-watch-pair` on the Mac and types the 6-digit code here.
struct PairingView: View {
    @EnvironmentObject var model: PetModel
    @State private var code = ""
    @State private var failed = false
    @State private var busy = false

    var body: some View {
        ScrollView {
            VStack(spacing: 8) {
                CatFace(state: .idle).frame(height: 70)
                Text(L.pairTitle).font(.headline)
                Text(L.pairHint).font(.caption2).multilineTextAlignment(.center).foregroundStyle(.secondary)
                TextField(L.pairCode, text: $code)
                    .textContentType(.oneTimeCode)
                    .multilineTextAlignment(.center)
                Button(L.pairButton) {
                    busy = true
                    Task {
                        failed = !(await model.pair(code: code.filter(\.isNumber)))
                        busy = false
                    }
                }
                .disabled(code.filter(\.isNumber).count != 6 || busy)
                if failed {
                    Text(L.pairFailed).font(.caption2).foregroundStyle(.red)
                }
            }
        }
    }
}

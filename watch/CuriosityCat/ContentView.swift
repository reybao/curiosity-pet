import SwiftUI

/// One screen: the cat on top (hold it to talk), the current sentence below, the Digital Crown scrolls.
struct ContentView: View {
    @EnvironmentObject var model: PetModel
    @State private var holding = false

    var body: some View {
        ScrollView {
            VStack(spacing: 4) {
                CatFace(state: model.state)
                    .frame(height: 110)
                    .contentShape(Rectangle())
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { _ in
                                if !holding {
                                    holding = true
                                    model.pressDown()
                                }
                            }
                            .onEnded { _ in
                                holding = false
                                model.pressUp()
                            }
                    )
                    .accessibilityLabel(L.holdToTalk)

                Text(status)
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                if !model.heard.isEmpty {
                    Text(model.heard)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }

                ForEach(Array(model.sentences.enumerated()), id: \.offset) { i, s in
                    Text(s)
                        .font(.body)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 4)
                        .background(i == model.current ? Color.yellow.opacity(0.35) : Color.clear)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .foregroundStyle(i <= model.current ? Color.primary : Color.secondary)
                }

                if !model.sentences.isEmpty || model.state != .idle {
                    Button(L.done) { model.end() }
                        .buttonStyle(.bordered)
                        .padding(.top, 6)
                }
            }
        }
    }

    private var status: String {
        if !model.message.isEmpty { return model.message }
        switch model.state {
        case .idle: return L.holdToTalk
        case .listening: return L.listening
        case .thinking: return L.thinking
        case .speaking: return ""
        }
    }
}

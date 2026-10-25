import SwiftUI

/// The British Shorthair blue cat, drawn in a 240 x 260 box like the iPad's SVG and scaled to fit.
/// The collar light is the "this is a program" marker (hard constraint 4) and changes color with the state.
struct CatFace: View {
    let state: CatState
    @State private var blink = false
    @State private var phase = false

    private let fur = Color(red: 0.55, green: 0.61, blue: 0.69)
    private let furDark = Color(red: 0.46, green: 0.52, blue: 0.60)
    private let furLight = Color(red: 0.71, green: 0.76, blue: 0.82)
    private let earInner = Color(red: 0.79, green: 0.65, blue: 0.69)
    private let iris = Color(red: 0.91, green: 0.64, blue: 0.24)
    private let ink = Color(red: 0.18, green: 0.16, blue: 0.15)

    private var light: Color {
        switch state {
        case .idle: return Color(red: 0.95, green: 0.84, blue: 0.48)
        case .listening: return Color(red: 0.44, green: 0.81, blue: 0.56)
        case .thinking: return Color(red: 0.71, green: 0.61, blue: 0.94)
        case .speaking: return Color(red: 0.95, green: 0.60, blue: 0.42)
        }
    }

    var body: some View {
        GeometryReader { geo in
            let s = min(geo.size.width / 240, geo.size.height / 260)
            ZStack {
                cat
                    .frame(width: 240, height: 260)
                    .scaleEffect(s, anchor: .topLeading)
                    .frame(width: 240 * s, height: 260 * s, alignment: .topLeading)
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 0.28).repeatForever(autoreverses: true)) { phase = true }
            Timer.scheduledTimer(withTimeInterval: 4.5, repeats: true) { _ in
                withAnimation(.easeInOut(duration: 0.12)) { blink = true }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    withAnimation(.easeInOut(duration: 0.12)) { blink = false }
                }
            }
        }
    }

    private var cat: some View {
        ZStack {
            // body, tail, paws
            Capsule().fill(furDark).frame(width: 20, height: 68).rotationEffect(.degrees(state == .thinking && phase ? 38 : 28))
                .offset(x: 66, y: 74)
            Ellipse().fill(fur).frame(width: 124, height: 80).offset(y: 78)
            Ellipse().fill(furLight).frame(width: 68, height: 48).offset(y: 86)
            Ellipse().fill(furDark).frame(width: 34, height: 20).offset(x: -24, y: 114)
            Ellipse().fill(furDark).frame(width: 34, height: 20).offset(x: 24, y: 114)

            // head (tilts while thinking)
            ZStack {
                ear(left: true)
                ear(left: false)
                Ellipse().fill(fur).frame(width: 148, height: 124).offset(y: -18)
                Ellipse().fill(furLight).frame(width: 64, height: 40).offset(y: 4)
                eye(x: -28)
                eye(x: 28)
                Ellipse().fill(Color(red: 0.95, green: 0.66, blue: 0.65).opacity(0.55)).frame(width: 18, height: 10).offset(x: -48, y: 2)
                Ellipse().fill(Color(red: 0.95, green: 0.66, blue: 0.65).opacity(0.55)).frame(width: 18, height: 10).offset(x: 48, y: 2)
                Triangle().fill(Color(red: 0.54, green: 0.43, blue: 0.47)).frame(width: 14, height: 8).rotationEffect(.degrees(180)).offset(y: -6)
                mouth
                whiskers
            }
            .rotationEffect(.degrees(state == .thinking ? -7 : 0))
            .animation(.easeInOut(duration: 0.3), value: state)

            // collar and the program light
            Capsule().fill(Color(red: 0.88, green: 0.48, blue: 0.37)).frame(width: 80, height: 11).offset(y: 41)
            Circle().fill(light).overlay(Circle().stroke(Color.white, lineWidth: 2.5)).frame(width: 16, height: 16)
                .offset(y: 53)
                .opacity(state == .listening || state == .thinking ? (phase ? 1 : 0.5) : 1)

            if state == .thinking { thinkingDots }
            if state == .listening { soundRings }
        }
        .offset(y: state == .speaking && phase ? -3 : 0)
    }

    private func ear(left: Bool) -> some View {
        let up = state == .listening ? -6.0 : 0.0
        return ZStack {
            Triangle().fill(fur).frame(width: 44, height: 50)
            Triangle().fill(earInner).frame(width: 26, height: 32).offset(y: 6)
        }
        .rotationEffect(.degrees(left ? -18 : 18))
        .offset(x: left ? -48 : 48, y: -74 + up)
        .animation(.easeOut(duration: 0.25), value: state)
    }

    private func eye(x: CGFloat) -> some View {
        let look: CGSize = state == .thinking ? CGSize(width: 3, height: -5) : .zero
        return ZStack {
            Ellipse().fill(iris).frame(width: 28, height: 30)
            Ellipse().fill(ink).frame(width: 10, height: 20).offset(look)
            Circle().fill(Color.white).frame(width: 8, height: 8).offset(x: 4 + look.width, y: -6 + look.height)
        }
        .scaleEffect(x: 1, y: blink ? 0.1 : 1)
        .offset(x: x, y: -24)
    }

    @ViewBuilder private var mouth: some View {
        if state == .speaking {
            Ellipse().fill(Color(red: 0.48, green: 0.29, blue: 0.33)).frame(width: 16, height: phase ? 14 : 5).offset(y: 10)
        } else {
            WMouth().stroke(ink, style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round))
                .frame(width: 24, height: 7).offset(y: 6)
        }
    }

    private var whiskers: some View {
        let twitch = state == .speaking && phase ? 4.0 : 0.0
        return ZStack {
            ForEach([-1.0, 1.0], id: \.self) { side in
                ForEach([-4.0, 4.0], id: \.self) { dy in
                    Capsule().fill(Color.white.opacity(0.9)).frame(width: 40, height: 2.5)
                        .rotationEffect(.degrees((dy < 0 ? -8 : 4) * side + twitch * side))
                        .offset(x: 46 * side, y: 2 + dy)
                }
            }
        }
    }

    private var thinkingDots: some View {
        HStack(spacing: 8) {
            ForEach(0..<3) { i in
                Circle().fill(Color(red: 0.71, green: 0.61, blue: 0.94)).frame(width: 12, height: 12)
                    .offset(y: phase ? (i == 1 ? -8 : -3) : 0)
            }
        }
        .offset(x: 70, y: -112)
    }

    private var soundRings: some View {
        ZStack {
            ForEach([-1.0, 1.0], id: \.self) { side in
                ForEach([0.0, 1.0], id: \.self) { k in
                    Arc().stroke(Color(red: 0.44, green: 0.81, blue: 0.56), style: StrokeStyle(lineWidth: 5, lineCap: .round))
                        .frame(width: 20 + 16 * k, height: 56 + 28 * k)
                        .scaleEffect(x: side, y: 1)
                        .offset(x: (96 + 12 * k) * side, y: -18)
                        .opacity(phase ? 0.9 - 0.4 * k : 0.3)
                }
            }
        }
    }
}

private struct Triangle: Shape {
    func path(in r: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: r.midX, y: r.minY))
            p.addLine(to: CGPoint(x: r.maxX, y: r.maxY))
            p.addLine(to: CGPoint(x: r.minX, y: r.maxY))
            p.closeSubpath()
        }
    }
}

/// The cat's "w" mouth.
private struct WMouth: Shape {
    func path(in r: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: r.minX, y: r.minY))
            p.addQuadCurve(to: CGPoint(x: r.midX, y: r.minY), control: CGPoint(x: r.minX + r.width / 4, y: r.maxY))
            p.addQuadCurve(to: CGPoint(x: r.maxX, y: r.minY), control: CGPoint(x: r.maxX - r.width / 4, y: r.maxY))
        }
    }
}

/// A sound ring on the left side; flipped for the right.
private struct Arc: Shape {
    func path(in r: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: r.maxX, y: r.minY))
            p.addQuadCurve(to: CGPoint(x: r.maxX, y: r.maxY), control: CGPoint(x: r.minX - r.width / 2, y: r.midY))
        }
    }
}

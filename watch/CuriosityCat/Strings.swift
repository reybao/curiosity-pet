import Foundation

/// Interface text in the watch's language. The pet itself answers in whatever language the child asked in.
enum L {
    static let zh = Locale.preferredLanguages.first?.hasPrefix("zh") ?? false

    static var holdToTalk: String { zh ? "按住说话" : "Hold to talk" }
    static var listening: String { zh ? "我在听" : "Listening" }
    static var thinking: String { zh ? "让我想一想" : "Let me think" }
    static var done: String { zh ? "结束" : "Done" }
    static var seeYou: String { zh ? "下次见!" : "See you!" }
    static var pairTitle: String { zh ? "和小猫配对" : "Pair with the cat" }
    static var pairHint: String { zh ? "请大人在 Mac 上运行 pet-watch-pair,输入 6 位配对码" : "Ask a grown-up to run pet-watch-pair on the Mac and enter the 6-digit code" }
    static var pairCode: String { zh ? "配对码" : "Code" }
    static var pairButton: String { zh ? "配对" : "Pair" }
    static var pairFailed: String { zh ? "配对码不对或已过期" : "Wrong or expired code" }
    static var offline: String { zh ? "连不上小猫,等一下再试" : "Can't reach the cat. Try again later" }
    static var tired: String { zh ? "小猫有点累,等一下再问吧" : "The cat needs a rest. Ask again soon" }
    static var micDenied: String { zh ? "需要麦克风权限:请大人在设置里打开" : "Microphone access needed: ask a grown-up to allow it in Settings" }
    static var unpair: String { zh ? "取消配对" : "Unpair" }
}

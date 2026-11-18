// Dock an already-open current-chat page, or use the named work-screen window for a link.
import AppKit
import ApplicationServices

func finish(_ status: String, _ fields: [String: Any] = [:], code: Int32 = 0) -> Never {
    var result = fields
    result["status"] = status
    let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    print(String(decoding: data, as: UTF8.self))
    exit(code)
}

func attribute(_ element: AXUIElement, _ key: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, key as CFString, &value) == .success else { return nil }
    return value
}

func frame(_ element: AXUIElement) -> CGRect {
    guard let pos = attribute(element, "AXPosition"), let size = attribute(element, "AXSize") else { return .zero }
    var origin = CGPoint.zero, dimensions = CGSize.zero
    AXValueGetValue(pos as! AXValue, .cgPoint, &origin)
    AXValueGetValue(size as! AXValue, .cgSize, &dimensions)
    return CGRect(origin: origin, size: dimensions)
}

func controls(_ root: AXUIElement, role: String, labels: [String] = []) -> [AXUIElement] {
    var queue = [root], matches: [AXUIElement] = [], index = 0
    while index < queue.count {
        let node = queue[index]
        index += 1
        let kind = attribute(node, "AXRole") as? String
        if kind == role && (labels.isEmpty || ["AXTitle", "AXDescription"].contains {
            labels.contains(attribute(node, $0) as? String ?? "")
        }) { matches.append(node) }
        // Inspect the host controls and web area URLs, never controls inside an exercise or another website.
        if kind == "AXWebArea", (attribute(node, "AXURL") as? URL)?.scheme != "app" { continue }
        queue += attribute(node, "AXChildren") as? [AXUIElement] ?? []
    }
    return matches
}

func until<T>(_ read: () -> T?) -> T? {
    let deadline = Date().addingTimeInterval(2.5)
    repeat {
        if let value = read() { return value }
        Thread.sleep(forTimeInterval: 0.12)
    } while Date() < deadline
    return nil
}

func screenRect(_ screen: NSScreen) -> CGRect {
    let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as! NSNumber
    return CGDisplayBounds(CGDirectDisplayID(number.uint32Value))
}

let virtualNames = ["ipad", "sidecar", "airplay", "opendisplay", "virtual", "dummy", "虚拟", "隔空播放"]
let args = Array(CommandLine.arguments.dropFirst())
let currentPageOnly = (2...3).contains(args.count) && args[1] == "--current-page"
    && (args.count == 2 || args[2] == "--reload")
let currentChatByName = args.count == 4 && args[3] == "--current-chat" && !args[1].isEmpty && !args[2].isEmpty
let currentChat = currentPageOnly || currentChatByName
let screens = NSScreen.screens.filter { screen in
    !virtualNames.contains { screen.localizedName.lowercased().contains($0) }
}.sorted { screenRect($0).minX < screenRect($1).minX }
let work = screens.first.map(screenRect) ?? CGRect.null
if !currentChat && (work.isNull || screens.dropFirst().first.map({ screenRect($0).minX == work.minX }) == true) {
    finish("work_screen_ambiguous", code: 1)
}
let apps = NSRunningApplication.runningApplications(withBundleIdentifier: "com.openai.codex")
guard AXIsProcessTrusted(), !apps.isEmpty else { finish("codex_accessibility_unavailable", code: 1) }
let onScreen = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
let windows = apps.flatMap { app -> [AXUIElement] in
    let visibleFrames = onScreen.compactMap { info -> CGRect? in
        guard info[kCGWindowOwnerPID as String] as? Int32 == app.processIdentifier,
              info[kCGWindowLayer as String] as? Int == 0,
              let bounds = info[kCGWindowBounds as String] as? NSDictionary else { return nil }
        return CGRect(dictionaryRepresentation: bounds)
    }
    let host = AXUIElementCreateApplication(app.processIdentifier)
    return (attribute(host, "AXWindows") as? [AXUIElement] ?? []).filter {
        let box = frame($0)
        return box.width > 200 && (currentChat || work.contains(box)) && visibleFrames.contains(box)
            && (attribute($0, "AXMinimized") as? Bool != true)
    }
}
if args == ["--windows"] {
    finish("work_screen", ["display": screens.first?.localizedName ?? "", "frame": NSStringFromRect(work),
                           "windows": windows.compactMap { attribute($0, "AXTitle") as? String }])
}
guard currentChat || ((3...4).contains(args.count) && (args.count == 3 || args[3] == "--reload")) else {
    finish("usage", ["usage": "PAGE.html --current-page [--reload] | PAGE.html WINDOW_TITLE LINK_LABEL [--current-chat|--reload] | --windows"], code: 2)
}
let target = URL(fileURLWithPath: args[0]).standardizedFileURL.resolvingSymlinksInPath()
guard ["html", "htm"].contains(target.pathExtension.lowercased()), FileManager.default.isReadableFile(atPath: target.path)
else { finish("missing_html", code: 1) }
func containsTarget(_ candidate: AXUIElement) -> Bool {
    controls(candidate, role: "AXWebArea").contains {
        guard let url = attribute($0, "AXURL") as? URL, url.isFileURL else { return false }
        let page = frame($0)
        return url.standardizedFileURL.resolvingSymlinksInPath() == target && page.width > 4 && frame(candidate).contains(page)
    }
}
let matching = windows.filter { currentPageOnly ? containsTarget($0) : attribute($0, "AXTitle") as? String == args[1] }
guard matching.count == 1 else { finish("task_window_unconfirmed", code: 1) }
let window = matching[0]

func visible(_ control: AXUIElement) -> Bool {
    let rect = frame(control), box = frame(window)
    return rect.width > 4 && rect.height > 4 && (currentChat || work.contains(box)) && box.contains(rect)
}

func currentPage() -> AXUIElement? {
    controls(window, role: "AXWebArea").first {
        guard let url = attribute($0, "AXURL") as? URL, url.isFileURL else { return false }
        return url.standardizedFileURL.resolvingSymlinksInPath() == target && visible($0)
    }
}

func press(_ matches: [AXUIElement]) -> Bool {
    let available = matches.filter(visible)
    return available.count == 1 && AXUIElementPerformAction(available[0], kAXPressAction as CFString) == .success
}

func chatAtRight() -> CGRect? {
    guard let page = currentPage() else { return nil }
    return controls(window, role: "AXTextArea").filter(visible).map(frame).first { $0.minX >= frame(page).maxX - 2 }
}

if currentPage() == nil {
    if currentPageOnly { finish("page_unconfirmed", code: 1) }
    let links = controls(window, role: "AXButton", labels: [args[2]]) + controls(window, role: "AXLink", labels: [args[2]])
    guard press(links) else { finish("link_needed", code: 1) }
    guard until(currentPage) != nil else { finish("page_unconfirmed", code: 1) }
} else if args.last == "--reload", let page = currentPage() {
    let area = frame(page)
    let reload = controls(window, role: "AXButton", labels: ["重新加载页面", "Reload page"]).filter {
        let r = frame($0)
        return (area.minX...area.maxX).contains(r.midX) && r.maxY <= area.minY + 1
    }
    guard press(reload) else { finish("reload_unconfirmed", code: 1) }
}
if chatAtRight() == nil {
    let dock = controls(window, role: "AXPopUpButton", labels: ["停靠聊天", "Dock chat"])
    guard press(dock) else { finish("chat_dock_unconfirmed", code: 1) }
    let options = until { () -> [AXUIElement]? in
        let items = controls(window, role: "AXMenuItem", labels: ["移至右侧窗格", "Move to right pane"])
        return items.isEmpty ? nil : items
    }
    guard let options, press(options) else { finish("right_pane_unconfirmed", code: 1) }
}
guard let chat = until(chatAtRight), let page = currentPage() else { finish("layout_unconfirmed", code: 1) }
finish("shown", ["path": target.path, "display": NSScreen.screens.first { screenRect($0).contains(frame(page).origin) }?.localizedName ?? "",
                 "page": NSStringFromRect(frame(page)), "chat": NSStringFromRect(chat)])

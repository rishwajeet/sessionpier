import AppKit
import SwiftUI
import Carbon

@MainActor final class CompanionDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow?
    private var statusItem: NSStatusItem?
    private let popover = NSPopover()
    private var shortcut: EventHotKeyRef?
    private var eventHandler: EventHandlerRef?
    private var registeredShortcut = false
    private var previousDock: Bool?
    private let model = CompanionModel.shared

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let icon = Bundle.main.url(forResource: "Accounts", withExtension: "icns") {
            NSApp.applicationIconImage = NSImage(contentsOf: icon)
        }
        makeMenu()
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem = item
        if let button = item.button {
            let image = NSImage(systemSymbolName: "rectangle.2.swap", accessibilityDescription: "SessionPier")
            image?.isTemplate = true
            button.image = image
            button.target = self
            button.action = #selector(togglePopover)
            button.toolTip = "SessionPier · Control–Option–Space"
        }
        popover.behavior = .transient
        popover.animates = !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        let menuHost = NSHostingController(rootView: CompanionMenu(model: model, showWindow: { [weak self] route in self?.showWindow(route) }, dismiss: { [weak self] in self?.popover.performClose(nil) }))
        menuHost.sizingOptions = [.preferredContentSize]
        popover.contentViewController = menuHost
        model.onPreferencesChanged = { [weak self] in self?.applyPreferences() }
        model.onAccountsChanged = { [weak self] in self?.updateStatus() }
        applyPreferences()
        showWindow("accounts")
        model.start()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow("accounts")
        return true
    }
    func windowWillClose(_ notification: Notification) {
        if !model.preferences.showDockIcon { NSApp.setActivationPolicy(.accessory) }
    }
    func applicationWillTerminate(_ notification: Notification) {
        if let shortcut { UnregisterEventHotKey(shortcut) }
        if let eventHandler { RemoveEventHandler(eventHandler) }
    }
    func showWindow(_ route: String) {
        model.navigation = route
        if window == nil {
            let view = CompanionWindow(model: model)
            let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1050, height: 720),
                               styleMask: [.titled, .closable, .miniaturizable, .resizable],
                               backing: .buffered, defer: false)
            win.title = "SessionPier"
            win.identifier = NSUserInterfaceItemIdentifier("companion-window")
            win.setFrameAutosaveName("CompanionWindow")
            win.minSize = NSSize(width: 955, height: 645)
            win.contentView = NSHostingView(rootView: view)
            win.isReleasedWhenClosed = false
            win.delegate = self
            win.center()
            window = win
        }
        if model.preferences.showDockIcon { NSApp.setActivationPolicy(.regular) }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    @objc private func openMain() { showWindow("accounts") }
    @objc private func toggleDemo() { model.toggleDemo(); showWindow("accounts") }
    @objc private func openSettings() { showWindow("settings") }
    @objc private func refreshUsage() { model.refreshUsage(force: true) }
    @objc private func newAccount() { showWindow("accounts"); model.showAdd = true }
    @objc func togglePopover() {
        if popover.isShown { popover.performClose(nil); return }
        guard let button = statusItem?.button else { return }
        model.readLocal()
        if let host = popover.contentViewController {
            host.view.layoutSubtreeIfNeeded()
            popover.contentSize = host.view.fittingSize
        }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
    }
    private func updateStatus() {
        let fresh = model.accounts.filter { $0.usage.isFresh }
        let ready = fresh.filter { ($0.usage.limitingWindow?.remaining ?? 0) > 0 }.count
        statusItem?.button?.title = ready > 0 ? " \(ready)" : ""
        statusItem?.button?.toolTip = "SessionPier · \(ready) within reported limits · Control–Option–Space"
    }
    private func applyPreferences() {
        if previousDock != model.preferences.showDockIcon {
            NSApp.setActivationPolicy(model.preferences.showDockIcon ? .regular : .accessory)
            previousDock = model.preferences.showDockIcon
        }
        if model.preferences.globalShortcutEnabled != registeredShortcut {
            if let shortcut { UnregisterEventHotKey(shortcut); self.shortcut = nil }
            registeredShortcut = model.preferences.globalShortcutEnabled
            if registeredShortcut {
                if eventHandler == nil {
                    var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
                    InstallEventHandler(GetApplicationEventTarget(), { _, _, context in
                        guard let context else { return noErr }
                        let delegate = Unmanaged<CompanionDelegate>.fromOpaque(context).takeUnretainedValue()
                        Task { @MainActor in delegate.togglePopover() }
                        return noErr
                    }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), &eventHandler)
                }
                let id = EventHotKeyID(signature: OSType(0x43414354), id: 1)
                let result = RegisterEventHotKey(UInt32(kVK_Space), UInt32(controlKey | optionKey), id, GetApplicationEventTarget(), 0, &shortcut)
                if result != noErr { model.message = "The quick-access shortcut is already in use. The menu-bar button is still available." }
            }
        }
    }
    private func makeMenu() {
        let bar = NSMenu()
        let appRoot = NSMenuItem()
        bar.addItem(appRoot)
        let app = NSMenu()
        app.addItem(withTitle: "About SessionPier", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        let prefs = app.addItem(withTitle: "Settings…", action: #selector(openSettings), keyEquivalent: ",")
        prefs.target = self
        let demoItem = app.addItem(withTitle: "Preview with example accounts", action: #selector(toggleDemo), keyEquivalent: "")
        demoItem.target = self
        app.addItem(.separator())
        app.addItem(withTitle: "Hide SessionPier", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(withTitle: "Quit SessionPier", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appRoot.submenu = app
        let fileRoot = NSMenuItem()
        fileRoot.title = "File"
        let file = NSMenu(title: "File")
        for (title, action, key) in [("Open Companion", #selector(openMain), "0"), ("Add Account…", #selector(newAccount), "n"), ("Refresh Usage", #selector(refreshUsage), "r")] {
            let item = file.addItem(withTitle: title, action: action, keyEquivalent: key)
            item.target = self
        }
        let quickItem = file.addItem(withTitle: "Quick access", action: #selector(togglePopover), keyEquivalent: " ")
        quickItem.keyEquivalentModifierMask = [.control, .option]
        quickItem.target = self
        file.addItem(.separator())
        file.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileRoot.submenu = file
        bar.addItem(fileRoot)
        let editRoot = NSMenuItem()
        editRoot.title = "Edit"
        let edit = NSMenu(title: "Edit")
        for (title, selector, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        editRoot.submenu = edit
        bar.addItem(editRoot)
        let windowRoot = NSMenuItem()
        windowRoot.title = "Window"
        let windows = NSMenu(title: "Window")
        windows.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowRoot.submenu = windows
        bar.addItem(windowRoot)
        NSApp.windowsMenu = windows
        NSApp.mainMenu = bar
    }
}

@main enum Entry {
    static func main() {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments.first == "--activate-pid", arguments.count == 2, let pid = Int32(arguments[1]) {
            guard let app = NSRunningApplication(processIdentifier: pid), app.activate(options: [.activateAllWindows]) else { exit(1) }
            exit(0)
        }
        if arguments.first == "--quit-pid", arguments.count == 2, let pid = Int32(arguments[1]) {
            guard let app = NSRunningApplication(processIdentifier: pid), app.terminate() else { exit(1) }
            exit(0)
        }
        if arguments.first == "--launch-desktop" {
            let config = NSWorkspace.OpenConfiguration()
            config.createsNewApplicationInstance = true
            config.activates = true
            config.arguments = Array(arguments.dropFirst())
            config.environment = ProcessInfo.processInfo.environment
            NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: "/Applications/Claude.app"), configuration: config) { _, error in
                if let error { fputs(error.localizedDescription + "\n", stderr); exit(1) }
                exit(0)
            }
            RunLoop.main.run()
            return
        }
        let app = NSApplication.shared
        let delegate = CompanionDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}

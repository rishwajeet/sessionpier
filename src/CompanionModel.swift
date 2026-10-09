import AppKit
import SwiftUI
import UserNotifications

struct UsageWindow: Identifiable, Decodable {
    let id: String
    let label: String
    let usedPercent: Double?
    let windowMinutes: Double?
    let resetsAt: Double?
    let resetDescription: String?
    var remaining: Double? { usedPercent.map { max(0, 100 - $0) } }
    var valueLabel: String {
        guard let value = usedPercent else { return "Not reported" }
        return value == value.rounded() ? String(format: "%.0f%% used", value) : String(format: "%.1f%% used", value)
    }
    var resetLabel: String {
        guard let timestamp = resetsAt else { return resetDescription ?? "Reset time not reported" }
        let date = Date(timeIntervalSince1970: timestamp)
        let seconds = date.timeIntervalSinceNow
        if seconds <= 0 { return "Reset due · awaiting refresh" }
        let minutes = Int(ceil(seconds / 60))
        if minutes < 60 { return "Resets in \(minutes)m" }
        if minutes < 1440 { return "Resets in \(minutes / 60)h \(minutes % 60)m" }
        return "Resets \(date.formatted(.dateTime.weekday(.abbreviated).hour().minute()))"
    }
}

struct UsageReading: Decodable {
    let status: String
    let source: String?
    let sampledAt: Double?
    let ageSeconds: Int?
    let stale: Bool
    let meters: [UsageWindow]
    var ageLabel: String {
        guard let sampledAt else { return "No reading yet" }
        let age = max(0, Int(Date().timeIntervalSince1970 - sampledAt))
        if age < 60 { return "just now" }
        if age < 3600 { return "\(age / 60)m ago" }
        if age < 86400 { return "\(age / 3600)h ago" }
        return "\(age / 86400)d ago"
    }
    var limitingWindow: UsageWindow? { meters.filter { $0.usedPercent != nil }.max { ($0.usedPercent ?? 0) < ($1.usedPercent ?? 0) } }
    var isFresh: Bool { status == "live" && !stale }
}

struct AccountConnection: Decodable {
    let state: String
    let message: String
    var needsLogin: Bool { ["login_required", "identity_mismatch", "identity_changed"].contains(state) }
    var needsSetup: Bool { state == "setup_required" }
}

struct CompanionAccount: Identifiable, Decodable {
    let id: String
    let profileId: String
    let name: String
    let provider: String
    let providerLabel: String
    let `default`: Bool
    let email: String
    let plan: String
    let desktopRunning: Bool
    let desktopPID: Int32?
    let desktopLoginSaved: Bool
    let historyReady: Bool
    let historySharingEnabled: Bool
    let remoteControlBlocked: Bool
    let requiresRemoteControlBlock: Bool
    let desktopRuntimeMatches: Bool
    let desktopPath: String
    let cliPath: String
    let connection: AccountConnection
    let usage: UsageReading
    let lastAttemptAt: Double?
    let nextAttemptAt: Double?
    var isClaude: Bool { provider == "claude" }
    var tint: Color { isClaude ? Color(red: 0.72, green: 0.38, blue: 0.24) : Color(red: 0.12, green: 0.53, blue: 0.43) }
    var symbol: String { isClaude ? (name.lowercased() == "work" ? "briefcase" : `default` ? "person.crop.circle" : "person.crop.square") : "terminal" }
    var remainingLabel: String {
        guard let value = usage.limitingWindow?.remaining else { return "—" }
        return value == value.rounded() ? String(format: "%.0f%%", value) : String(format: "%.1f%%", value)
    }
    var statusLabel: String {
        if connection.needsLogin { return "Connect live usage" }
        if connection.needsSetup { return "Finish setup" }
        if usage.status == "snapshot" { return "Saved reading" }
        if !usage.isFresh { return usage.sampledAt == nil ? "Not connected" : "Reading out of date" }
        if (usage.limitingWindow?.usedPercent ?? 0) >= 100 { return "At limit" }
        if (usage.limitingWindow?.usedPercent ?? 0) >= 80 { return "Running low" }
        return "Live"
    }
    var statusColor: Color {
        guard usage.isFresh else { return .secondary }
        if (usage.limitingWindow?.usedPercent ?? 0) >= 100 { return .red }
        if (usage.limitingWindow?.usedPercent ?? 0) >= 80 { return .orange }
        return .green
    }
    var openLabel: String { isClaude ? (desktopRunning ? "Switch to Claude" : "Open Claude") : "Open Codex CLI" }
}

struct CompanionPreferences: Decodable {
    var refreshSeconds: Int = 300
    var notificationsEnabled: Bool = false
    var showDockIcon: Bool = true
    var globalShortcutEnabled: Bool = true
    var launchAtLogin: Bool = false
}
struct CompanionSnapshot: Decodable {
    let generatedAt: Double
    let settings: CompanionPreferences
    let accounts: [CompanionAccount]
}
struct BackendFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

enum Backend {
    static func run(_ args: [String], legacy: Bool = false) throws -> Data {
        guard let configURL = Bundle.main.url(forResource: "backend", withExtension: "json"),
              let config = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any] else {
            throw BackendFailure(message: "The app’s local backend is missing. Reinstall this app.")
        }
        let task = Process()
        let resources = Bundle.main.resourceURL!
        if let python = config["python"] as? String, let backend = config["backend"] as? String {
            task.executableURL = resources.appendingPathComponent(python)
            task.arguments = ["-B", resources.appendingPathComponent(backend).appendingPathComponent(legacy ? "claude_profile.py" : "companion.py").path] + args
        } else if var command = config["command"] as? [String], !command.isEmpty {
            if !legacy, let last = command.last { command[command.count - 1] = URL(fileURLWithPath: last).deletingLastPathComponent().appendingPathComponent("companion.py").path }
            task.executableURL = URL(fileURLWithPath: command.removeFirst())
            task.arguments = command + args
        } else { throw BackendFailure(message: "The app’s backend configuration is invalid.") }
        var env = ProcessInfo.processInfo.environment
        env["COMPANION_APP_BUNDLE"] = Bundle.main.bundlePath
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        task.environment = env
        task.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        let output = Pipe()
        task.standardOutput = output
        task.standardError = output
        try task.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        guard task.terminationStatus == 0 else {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw BackendFailure(message: object?["error"] as? String ?? String(data: data, encoding: .utf8) ?? "The local action failed.")
        }
        return data
    }
}

@MainActor final class CompanionModel: ObservableObject {
    static let shared = CompanionModel()
    @Published var accounts: [CompanionAccount] = []
    @Published var preferences = CompanionPreferences()
    @Published var isLoading = true
    @Published var isRefreshing = false
    @Published var actionInFlight: String?
    @Published var selectedID = UserDefaults.standard.string(forKey: "selectedAccount") ?? ""
    @Published var navigation = "accounts"
    @Published var search = ""
    @Published var providerFilter = "all"
    @Published var message: String?
    @Published var error: String?
    @Published var diagnostics: String?
    @Published var showAdd = false
    @Published var confirmHistory: CompanionAccount?
    @Published var confirmDesktopLogin: CompanionAccount?
    @Published var changedIDs: Set<String> = []
    @Published var hideEmails = UserDefaults.standard.bool(forKey: "hideEmails")
    @Published var demo = CommandLine.arguments.contains("--demo")
    private var timer: Timer?
    private var localReading = false
    private var ticks = 0
    private var notificationBaseline: [String: Double] = [:]
    var onPreferencesChanged: (() -> Void)?
    var onAccountsChanged: (() -> Void)?
    var selected: CompanionAccount? { filteredAccounts.first { $0.id == selectedID } ?? filteredAccounts.first }
    var filteredAccounts: [CompanionAccount] {
        accounts.filter { account in
            (providerFilter == "all" || account.provider == providerFilter) &&
            (search.isEmpty || [account.name, account.providerLabel, hideEmails ? "" : account.email].joined(separator: " ").localizedCaseInsensitiveContains(search))
        }
    }
    var connectedCount: Int { accounts.filter { $0.usage.isFresh }.count }
    var refreshLabel: String { preferences.refreshSeconds == 60 ? "Every minute" : "Every \(preferences.refreshSeconds / 60) minutes" }

    func start() {
        guard timer == nil else { return }
        readLocal { self.refreshUsage() }
        timer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.ticks += 1
                self.readLocal()
                if self.ticks % 2 == 0 { self.refreshUsage() }
            }
        }
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.refreshUsage() }
        }
    }
    func toggleDemo() {
        demo.toggle()
        selectedID = demo ? "demo-0" : UserDefaults.standard.string(forKey: "selectedAccount") ?? ""
        readLocal()
    }
    func select(_ account: CompanionAccount) {
        selectedID = account.id
        if !demo { UserDefaults.standard.set(account.id, forKey: "selectedAccount") }
    }
    func accept(_ value: CompanionSnapshot) {
        let before = Dictionary(uniqueKeysWithValues: accounts.map { ($0.id, $0.usage.sampledAt) })
        let changed = Set(value.accounts.filter { account in
            account.usage.isFresh && before[account.id] != nil && (before[account.id] ?? nil) != account.usage.sampledAt
        }.map(\.id))
        accounts = value.accounts
        preferences = value.settings
        isLoading = false
        if !accounts.contains(where: { $0.id == selectedID }), let first = accounts.first { select(first) }
        changedIDs = changed
        if !changed.isEmpty { DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { self.changedIDs = [] } }
        deliverNotifications()
        onAccountsChanged?()
        onPreferencesChanged?()
    }
    func readLocal(completion: (() -> Void)? = nil) {
        guard !localReading else { return }
        localReading = true
        let isDemo = demo
        DispatchQueue.global(qos: .utility).async {
            do {
                let data = isDemo ? try Data(contentsOf: Bundle.main.url(forResource: "demo-snapshot", withExtension: "json")!) : try Backend.run(["snapshot"])
                let value = try JSONDecoder().decode(CompanionSnapshot.self, from: data)
                DispatchQueue.main.async {
                    self.localReading = false
                    guard self.demo == isDemo else { self.readLocal(); return }
                    self.accept(value); completion?()
                }
            } catch {
                DispatchQueue.main.async { self.error = error.localizedDescription; self.isLoading = false; self.localReading = false }
            }
        }
    }
    func refreshUsage(account: CompanionAccount? = nil, force: Bool = false) {
        guard !isRefreshing, !demo else { return }
        let now = Date().timeIntervalSince1970
        if !force && account == nil && !accounts.contains(where: { ($0.nextAttemptAt ?? 0) <= now }) { return }
        isRefreshing = true
        var args = ["refresh"]
        if let account { args.append(account.id) }
        if force { args.append("--force") }
        DispatchQueue.global(qos: .utility).async {
            do {
                let data = try Backend.run(args)
                let value = try JSONDecoder().decode(CompanionSnapshot.self, from: data)
                DispatchQueue.main.async { if !self.demo { self.accept(value) }; self.isRefreshing = false }
            } catch {
                DispatchQueue.main.async { self.error = error.localizedDescription; self.isRefreshing = false }
            }
        }
    }
    func perform(_ args: [String], account: CompanionAccount? = nil, legacy: Bool = false, diagnostic: Bool = false) {
        guard actionInFlight == nil, !demo else { return }
        actionInFlight = account?.id ?? "global"
        message = nil
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let data = try Backend.run(args, legacy: legacy)
                let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                let text = object?["message"] as? String ?? (args.first == "add" ? "Account added. Connect its official client to enable live usage." : String(data: data, encoding: .utf8) ?? "Done")
                DispatchQueue.main.async {
                    self.actionInFlight = nil
                    if args.first == "add", let id = object?["id"] as? String { self.selectedID = id; self.navigation = "accounts" }
                    if diagnostic { self.diagnostics = String(data: (try? JSONSerialization.data(withJSONObject: object ?? [:], options: [.prettyPrinted, .sortedKeys])) ?? data, encoding: .utf8) }
                    else { self.message = text }
                    self.readLocal {
                        if ["open", "refresh-history", "sign-in-desktop"].contains(args.first ?? ""),
                           let id = account?.id, let pid = self.accounts.first(where: { $0.id == id })?.desktopPID,
                           let app = NSRunningApplication(processIdentifier: pid) {
                            if #available(macOS 14.0, *) { _ = app.activate(from: .current, options: [.activateAllWindows]) }
                            else { app.activate(options: [.activateAllWindows]) }
                        }
                    }
                }
            } catch {
                DispatchQueue.main.async { self.actionInFlight = nil; self.error = error.localizedDescription }
            }
        }
    }
    func open(_ account: CompanionAccount) {
        select(account)
        if account.isClaude {
            if account.desktopLoginSaved { perform(["open", account.id], account: account) }
            else { confirmDesktopLogin = account }
        } else { chooseProject(account) }
    }
    func chooseProject(_ account: CompanionAccount) {
        let panel = NSOpenPanel()
        panel.title = "Open \(account.name)"
        panel.message = "Choose a project for the official \(account.isClaude ? "Claude Code" : "Codex") client."
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.prompt = "Open project"
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser
        if panel.runModal() == .OK, let url = panel.url {
            perform(["terminal", account.id, "--cwd", url.path], account: account)
        }
    }
    func setPreference(_ key: String, _ value: Any) {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: .fragmentsAllowed),
              let text = String(data: data, encoding: .utf8) else { return }
        perform(["set-preference", key, text])
    }
    func setNotifications(_ enabled: Bool) {
        guard enabled else { setPreference("notificationsEnabled", false); return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { allowed, _ in
            DispatchQueue.main.async {
                self.setPreference("notificationsEnabled", allowed)
                if !allowed { self.error = "Notifications are off in macOS. You can enable them for SessionPier in System Settings → Notifications." }
            }
        }
    }
    private func deliverNotifications() {
        for account in accounts where account.usage.isFresh {
            guard let value = account.usage.limitingWindow?.usedPercent else { continue }
            let old = notificationBaseline[account.id]
            notificationBaseline[account.id] = value
            guard preferences.notificationsEnabled, let old, !demo else { continue }
            let threshold = [80.0, 95, 100].last { value >= $0 && old < $0 }
            let recovered = old >= 100 && value < 100
            guard threshold != nil || recovered else { continue }
            let content = UNMutableNotificationContent()
            content.title = recovered ? "\(account.name) has capacity again" : "\(account.name) is \(Int(threshold!))% used"
            content.body = recovered ? "A fresh reading is available in SessionPier." : "\(account.usage.limitingWindow?.label ?? "Usage") limit. Open the companion to choose your next account."
            content.sound = .default
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "usage-\(account.id)-\(UUID().uuidString)", content: content, trigger: nil))
        }
    }
}

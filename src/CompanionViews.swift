import AppKit
import SwiftUI
import ServiceManagement

private enum Palette {
    static let accentFill = Color(red: 0.36, green: 0.38, blue: 0.83)
    static let accent = Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(srgbRed: 0.64, green: 0.66, blue: 1, alpha: 1)
            : NSColor(srgbRed: 0.30, green: 0.32, blue: 0.75, alpha: 1)
    })
    static let line = Color.primary.opacity(0.09)
    static let rail = Color(nsColor: .underPageBackgroundColor)
    static let surface = Color(nsColor: .controlBackgroundColor)
}

struct AccountMark: View {
    let account: CompanionAccount
    var size: CGFloat = 34
    var body: some View {
        Image(systemName: account.symbol)
            .font(.system(size: size * 0.44, weight: .medium))
            .foregroundStyle(account.tint)
            .frame(width: size, height: size)
            .background(account.tint.opacity(0.11), in: RoundedRectangle(cornerRadius: size * 0.23))
            .accessibilityHidden(true)
    }
}

struct StateLabel: View {
    let account: CompanionAccount
    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(account.statusColor).frame(width: 5, height: 5)
            Text(account.statusLabel)
        }.font(.system(size: 11)).foregroundStyle(account.statusColor)
    }
}

struct CapacityLine: View {
    let meter: UsageWindow
    let stale: Bool
    var compact = false
    var tint: Color {
        guard let value = meter.usedPercent else { return .secondary }
        return value >= 100 ? .red : value >= 80 ? .orange : Palette.accent
    }
    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 5 : 8) {
            HStack {
                Text(meter.label).fontWeight(.medium)
                Spacer()
                Text(meter.valueLabel).monospacedDigit().foregroundStyle(meter.usedPercent == nil ? Color.secondary : tint)
            }.font(.system(size: compact ? 11 : 12))
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.075))
                    if let amount = meter.usedPercent, amount > 0 {
                        Capsule().fill(tint.opacity(stale ? 0.4 : 0.85))
                            .frame(width: max(2, geometry.size.width * min(100, amount) / 100))
                    }
                }
            }.frame(height: compact ? 3 : 5)
            if !compact {
                Text(meter.resetLabel).font(.system(size: 11)).foregroundStyle(.secondary)
                    .help(meter.resetsAt.map { Date(timeIntervalSince1970: $0).formatted(date: .complete, time: .shortened) } ?? meter.resetDescription ?? "The provider has not reported a reset time.")
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(meter.label), \(meter.valueLabel), \(meter.resetLabel)\(stale ? ", older reading" : "")")
    }
}

struct AccountRow: View {
    let account: CompanionAccount
    @ObservedObject var model: CompanionModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovering = false
    private var selected: Bool { model.selected?.id == account.id }
    var body: some View {
        HStack(spacing: 12) {
            Button { model.select(account) } label: {
                HStack(spacing: 12) {
                AccountMark(account: account)
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 7) {
                        Text(account.name).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                        if account.desktopRunning {
                            Text("OPEN").font(.system(size: 8, weight: .semibold)).tracking(0.3)
                                .padding(.horizontal, 5).padding(.vertical, 2)
                                .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 3))
                        }
                    }
                    Text(account.providerLabel + (account.usage.isFresh ? "" : " · " + account.statusLabel)).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(2)
                }.frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .trailing, spacing: 5) {
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(account.remainingLabel).font(.system(size: 18, weight: .medium)).monospacedDigit()
                        if account.usage.limitingWindow != nil { Text("left").font(.system(size: 10)).foregroundStyle(.secondary) }
                    }.foregroundStyle(account.usage.isFresh ? Color.primary : .secondary)
                    Text(account.usage.limitingWindow?.label ?? "Usage unavailable")
                        .font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                }.frame(width: 116, alignment: .trailing)
                }.contentShape(Rectangle())
            }.buttonStyle(.plain)
                .accessibilityLabel("\(account.name), \(account.providerLabel), \(account.remainingLabel) remaining in \(account.usage.limitingWindow?.label ?? "reported limits"), \(account.statusLabel)")
                .help("Capacity in the tightest reported window. Missing limits are not counted as unused.")
            if selected {
                Button { model.open(account) } label: {
                    Label("Open", systemImage: "arrow.up.right")
                        .font(.system(size: 11, weight: .medium))
                }.buttonStyle(.borderless).frame(width: 57)
                    .disabled(model.actionInFlight != nil)
                    .accessibilityLabel(account.openLabel + " · " + account.name)
                    .help(account.openLabel)
            } else {
                Image(systemName: "chevron.right").font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.tertiary).frame(width: 57).accessibilityHidden(true)
            }
        }
            .padding(.horizontal, 15).padding(.vertical, 17)
            .background(selected ? Palette.accentFill.opacity(0.09) : hovering ? Color.primary.opacity(0.035) : Color.clear)
            .overlay(alignment: .bottom) { Rectangle().fill(Palette.line).frame(height: 0.5) }
            .overlay { if model.changedIDs.contains(account.id) { Rectangle().fill(Color.green.opacity(0.055)).allowsHitTesting(false) } }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: selected)
        .onHover { hovering = $0 }
        .contextMenu {
            Button(account.openLabel) { model.open(account) }
            Button("Refresh usage") { model.refreshUsage(account: account, force: true) }
            if account.isClaude && account.historySharingEnabled {
                Button("Continue local Code work…") { model.confirmHistory = account }
            }
        }
    }
}

struct AccountDetail: View {
    let account: CompanionAccount
    @ObservedObject var model: CompanionModel
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    VStack(alignment: .leading, spacing: 11) {
                        HStack(alignment: .top) {
                            AccountMark(account: account, size: 40)
                            Spacer()
                            Menu {
                                Button("Open account data") { NSWorkspace.shared.open(URL(fileURLWithPath: account.desktopPath)) }
                                if account.isClaude { Button("Open Claude Code in Terminal…") { model.chooseProject(account) } }
                                Divider()
                                Button("Reconnect live usage…") { model.perform(["connect", account.id], account: account) }
                            } label: { Image(systemName: "ellipsis").frame(width: 22, height: 22) }
                            .menuStyle(.borderlessButton).fixedSize().help("Account options")
                        }
                        Text(account.name).font(.system(size: 20, weight: .semibold))
                        Text(account.providerLabel + (account.plan.isEmpty || account.plan.contains("_") ? "" : " · " + account.plan.capitalized))
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                        if !account.email.isEmpty {
                            Text(model.hideEmails ? "Email hidden" : account.email).font(.system(size: 11))
                                .foregroundStyle(.secondary).textSelection(.enabled).lineLimit(2)
                        }
                        StateLabel(account: account)
                    }
                    if account.connection.state != "connected" && account.connection.state != "not_checked" {
                        VStack(alignment: .leading, spacing: 9) {
                            Label(account.connection.needsLogin ? "Enable automatic updates" : "Usage needs attention", systemImage: "info.circle")
                                .font(.system(size: 12, weight: .medium))
                            Text(account.connection.message).font(.system(size: 11)).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                            if account.connection.needsLogin {
                                Button("Connect live usage") { model.perform(["connect", account.id], account: account) }
                                    .controlSize(.small)
                            } else if account.connection.needsSetup {
                                Button("Finish setup") { model.perform(["setup", account.id], account: account) }
                                    .controlSize(.small)
                            } else if account.connection.state == "client_missing" {
                                Link("Install official client", destination: URL(string: account.isClaude ? "https://code.claude.com/docs/en/setup" : "https://developers.openai.com/codex/cli")!)
                            } else {
                                Button("Try refresh") { model.refreshUsage(account: account, force: true) }.controlSize(.small)
                            }
                        }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.orange.opacity(0.055), in: RoundedRectangle(cornerRadius: 8))
                            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.orange.opacity(0.18), lineWidth: 0.5))
                    }
                    if account.usage.meters.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Your limits will appear here").font(.system(size: 13, weight: .medium))
                            Text("Connect the official client once. The companion will then keep usage up to date in the background.")
                                .font(.system(size: 12)).foregroundStyle(.secondary)
                        }.padding(.vertical, 10)
                    } else {
                        VStack(alignment: .leading, spacing: 20) {
                            ForEach(account.usage.meters) { meter in CapacityLine(meter: meter, stale: !account.usage.isFresh) }
                        }
                    }
                    VStack(alignment: .leading, spacing: 7) {
                        if let source = account.usage.source {
                            Label(source, systemImage: account.usage.isFresh ? "checkmark.circle" : "clock")
                                .font(.system(size: 10, weight: .medium))
                            Text("\(account.usage.status == "snapshot" ? "Recorded" : "Updated") \(account.usage.ageLabel)\(account.usage.stale ? " · may be outdated" : "")")
                                .font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                        if !account.isClaude {
                            Text("These are Codex limits on your ChatGPT plan. Other ChatGPT model limits are separate.")
                                .font(.system(size: 10)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    if account.isClaude {
                        Divider()
                        VStack(alignment: .leading, spacing: 8) {
                            Label(account.requiresRemoteControlBlock ? "Shared-account protection" : "Local Code workspace",
                                  systemImage: account.requiresRemoteControlBlock ? "lock.shield" : "folder")
                                .font(.system(size: 11, weight: .medium))
                            Text(account.requiresRemoteControlBlock ? "Remote Control stays blocked for this shared account. Model requests still go to Anthropic." : account.historySharingEnabled ? "Your original local conversations and project files stay in place." : "Local history sharing is off for this account.")
                                .font(.system(size: 11)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
            }
            Divider()
            VStack(spacing: 9) {
                Button { model.open(account) } label: {
                    HStack { Text(account.desktopLoginSaved || !account.isClaude ? account.openLabel : "Sign in to Desktop"); Spacer(); Image(systemName: "arrow.up.right") }
                }.buttonStyle(.borderedProminent).tint(Palette.accentFill).controlSize(.large)
                if account.isClaude && account.historySharingEnabled {
                    Button { model.confirmHistory = account } label: {
                        Label("Continue local Code work…", systemImage: "arrow.triangle.2.circlepath").frame(maxWidth: .infinity)
                    }.buttonStyle(.bordered).controlSize(.regular).disabled(!account.historyReady)
                }
            }.padding(18).disabled(model.actionInFlight != nil)
        }.frame(minWidth: 275, idealWidth: 295, maxWidth: 325)
            .background(Palette.surface)
    }
}

struct AccountsWorkspace: View {
    @ObservedObject var model: CompanionModel
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.demo ? "Example accounts" : "Your subscriptions").font(.system(size: 24, weight: .semibold))
                    Text("Choose the account. Keep the context.").font(.system(size: 12)).foregroundStyle(.secondary)
                }
                Spacer()
                Button { model.refreshUsage(force: true) } label: {
                    HStack(spacing: 6) {
                        if model.isRefreshing { ProgressView().controlSize(.small).scaleEffect(0.8).frame(width: 14, height: 14) }
                        else { Image(systemName: "arrow.clockwise") }
                        Text(model.isRefreshing ? "Updating" : "Refresh usage")
                    }
                }.disabled(model.isRefreshing).keyboardShortcut("r", modifiers: .command)
            }.padding(.horizontal, 24).padding(.top, 24).padding(.bottom, 20)
            HStack(spacing: 12) {
                Picker("Provider", selection: $model.providerFilter) {
                    Text("All accounts").tag("all")
                    Text("Claude").tag("claude")
                    Text("Codex").tag("codex")
                }.pickerStyle(.segmented).tint(Palette.accentFill).labelsHidden().frame(width: 310)
                Spacer(minLength: 10)
                HStack(spacing: 5) {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField("Find account", text: $model.search).textFieldStyle(.plain)
                }.padding(7).frame(width: 155).background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 6))
            }.padding(.horizontal, 24).padding(.bottom, 17)
            Divider()
            if model.accounts.isEmpty && !model.isLoading {
                VStack(alignment: .leading, spacing: 14) {
                    Image(systemName: "person.crop.rectangle.stack").font(.system(size: 32)).foregroundStyle(Palette.accent)
                    Text("All your accounts, one place").font(.title2.weight(.semibold))
                    Text("Import the Claude Desktop account already on this Mac, or add another subscription. Your provider handles sign-in.")
                        .foregroundStyle(.secondary).frame(maxWidth: 420)
                    HStack {
                        Button("Import Claude Desktop") { model.perform(["import-claude"]) }.buttonStyle(.borderedProminent).tint(Palette.accentFill)
                        Button("Add an account") { model.showAdd = true }
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center).padding(35)
            } else {
                HSplitView {
                    VStack(alignment: .leading, spacing: 0) {
                        HStack {
                            Text("ACCOUNT")
                            Spacer()
                            Text("TIGHTEST WINDOW")
                        }.font(.system(size: 9, weight: .medium)).tracking(0.5).foregroundStyle(.secondary)
                            .padding(.horizontal, 16).padding(.top, 15).padding(.bottom, 10)
                        ScrollView {
                            LazyVStack(spacing: 0) {
                                if model.isLoading {
                                    ForEach(0..<3) { _ in RoundedRectangle(cornerRadius: 5).fill(Color.primary.opacity(0.04)).frame(height: 65).padding(8) }
                                } else if model.filteredAccounts.isEmpty {
                                    Text("No accounts match this search.").foregroundStyle(.secondary).padding(24)
                                } else {
                                    ForEach(model.filteredAccounts) { account in AccountRow(account: account, model: model) }
                                }
                            }
                        }
                        VStack(alignment: .leading, spacing: 9) {
                            HStack(spacing: 6) {
                                Image(systemName: "bolt.horizontal.circle").foregroundStyle(Palette.accent)
                                Text("\(model.connectedCount) live \(model.connectedCount == 1 ? "connection" : "connections")")
                                Spacer()
                                Text(model.refreshLabel).foregroundStyle(.secondary)
                            }.font(.system(size: 11))
                            Text("Remaining capacity is based on each account’s most-used reported window. Older readings stay labelled.")
                                .font(.system(size: 10)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }.padding(17).background(Color.primary.opacity(0.018))
                    }.frame(minWidth: 345, maxWidth: .infinity)
                    if let selected = model.selected { AccountDetail(account: selected, model: model) }
                }
            }
            if let message = model.message {
                HStack(spacing: 8) {
                    Image(systemName: "checkmark.circle").foregroundStyle(.green)
                    Text(message).font(.system(size: 11)).lineLimit(2)
                    Spacer()
                    Button { model.message = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain).help("Dismiss message")
                }.padding(12).background(Color.primary.opacity(0.035))
            }
        }
    }
}

struct CompanionSettingsView: View {
    @ObservedObject var model: CompanionModel
    @State private var loginError: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 25) {
                Text("Settings").font(.system(size: 24, weight: .semibold))
                GroupBox {
                    VStack(alignment: .leading, spacing: 18) {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Refresh usage automatically").fontWeight(.medium)
                                Text("Native clients fetch usage while the companion is running.").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Picker("Refresh interval", selection: Binding(get: { model.preferences.refreshSeconds }, set: { model.setPreference("refreshSeconds", $0) })) {
                                Text("Every minute").tag(60)
                                Text("Every 5 minutes").tag(300)
                                Text("Every 15 minutes").tag(900)
                            }.labelsHidden().frame(width: 160)
                        }
                        Divider()
                        Toggle(isOn: Binding(get: { model.preferences.notificationsEnabled }, set: model.setNotifications)) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Capacity alerts").fontWeight(.medium)
                                Text("Notify at 80%, 95% and 100% used, and when capacity returns.").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }.padding(10).tint(Palette.accentFill)
                }
                GroupBox {
                    VStack(alignment: .leading, spacing: 18) {
                        Toggle("Show Dock icon", isOn: Binding(get: { model.preferences.showDockIcon }, set: { model.setPreference("showDockIcon", $0) }))
                        Toggle(isOn: Binding(get: { model.preferences.globalShortcutEnabled }, set: { model.setPreference("globalShortcutEnabled", $0) })) {
                            HStack { Text("Global quick-access shortcut"); Spacer(); Text("⌃ ⌥ Space").foregroundStyle(.secondary) }
                        }
                        Toggle("Hide email addresses", isOn: Binding(get: { model.hideEmails }, set: {
                            model.hideEmails = $0; UserDefaults.standard.set($0, forKey: "hideEmails")
                        }))
                        Toggle("Launch at login", isOn: Binding(get: { SMAppService.mainApp.status == .enabled }, set: { enabled in
                            do {
                                if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                                model.setPreference("launchAtLogin", enabled)
                            } catch { loginError = error.localizedDescription }
                        }))
                        if let loginError { Text(loginError).font(.caption).foregroundStyle(.red) }
                    }.padding(10).tint(Palette.accentFill)
                }
                GroupBox {
                    VStack(alignment: .leading, spacing: 13) {
                        Text("Accounts stay with their providers").font(.system(size: 13, weight: .semibold))
                        Text("SessionPier reads usage through the official Claude Code and Codex clients. It does not extract browser cookies or store copies of provider tokens. Claude Desktop snapshots are a fallback when live usage is not connected.")
                            .font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        HStack {
                            Button("Sync Claude tools") { model.perform(["sync"], diagnostic: true) }
                            Button("Check setup") { model.perform(["doctor"], diagnostic: true) }
                            Spacer()
                        }
                    }.padding(10)
                }
                VStack(alignment: .leading, spacing: 5) {
                    Text("SessionPier \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "2.0")")
                        .font(.system(size: 12, weight: .medium))
                    Text("Independent companion. Not affiliated with Anthropic or OpenAI.")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }.padding(30).frame(maxWidth: 760, alignment: .leading).frame(maxWidth: .infinity).disabled(model.demo)
        }
    }
}

struct CompanionWindow: View {
    @ObservedObject var model: CompanionModel
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 9) {
                    Image(systemName: "rectangle.2.swap").font(.system(size: 20)).foregroundStyle(Palette.accent)
                    Text("SessionPier").font(.system(size: 16, weight: .semibold))
                }.padding(.horizontal, 17).padding(.top, 25).padding(.bottom, 27)
                sidebarItem("Your accounts", systemImage: "person.2", selection: "accounts")
                sidebarItem("Settings", systemImage: "slider.horizontal.3", selection: "settings")
                Spacer()
                Button { model.showAdd = true } label: { Label("Add account", systemImage: "plus").frame(maxWidth: .infinity, alignment: .leading) }
                    .buttonStyle(.plain).padding(12).background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 7)).padding(12)
                VStack(alignment: .leading, spacing: 5) {
                    Text("QUICK ACCESS").font(.system(size: 8, weight: .medium)).tracking(0.6)
                    Text("⌃ ⌥ Space").font(.system(size: 12, weight: .medium))
                }.foregroundStyle(.secondary).padding(.horizontal, 21).padding(.bottom, 24)
            }.frame(width: 165).background(Palette.rail)
            Divider()
            if model.navigation == "settings" { CompanionSettingsView(model: model) }
            else { AccountsWorkspace(model: model) }
        }.frame(minWidth: 955, minHeight: 610)
            .background(Color(nsColor: .windowBackgroundColor)).tint(Palette.accent)
            .alert("Couldn’t complete that action", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
                Button("OK", role: .cancel) { model.error = nil }
            } message: { Text(model.error ?? "") }
            .sheet(isPresented: $model.showAdd) { AddAccountSheet(model: model) }
            .sheet(isPresented: Binding(get: { model.confirmHistory != nil }, set: { if !$0 { model.confirmHistory = nil } })) {
                if let account = model.confirmHistory { HistorySheet(account: account, model: model) }
            }
            .sheet(isPresented: Binding(get: { model.confirmDesktopLogin != nil }, set: { if !$0 { model.confirmDesktopLogin = nil } })) {
                if let account = model.confirmDesktopLogin {
                    VStack(alignment: .leading, spacing: 18) {
                        Text("Sign in to \(account.name)").font(.title2.weight(.semibold))
                        Text("The official Claude app handles your login. First, close the other Claude windows so macOS sends the browser callback to the right account. Stop any running turns before continuing.")
                            .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        HStack {
                            Button("Cancel") { model.confirmDesktopLogin = nil }.keyboardShortcut(.cancelAction)
                            Spacer()
                            Button("Close other windows and sign in") { model.confirmDesktopLogin = nil; model.perform(["sign-in-desktop", account.id], account: account) }
                                .buttonStyle(.borderedProminent).tint(Palette.accentFill)
                        }
                    }.padding(28).frame(width: 490)
                }
            }
            .sheet(isPresented: Binding(get: { model.diagnostics != nil }, set: { if !$0 { model.diagnostics = nil } })) {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Setup details").font(.title2.weight(.semibold))
                    ScrollView { Text(model.diagnostics ?? "").font(.system(size: 11, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                    HStack { Spacer(); Button("Done") { model.diagnostics = nil }.keyboardShortcut(.defaultAction) }
                }.padding(24).frame(width: 650, height: 470)
            }
    }
    private func sidebarItem(_ title: String, systemImage: String, selection: String) -> some View {
        Button { model.navigation = selection } label: {
            Label(title, systemImage: systemImage).font(.system(size: 12, weight: model.navigation == selection ? .medium : .regular))
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 11).padding(.vertical, 9)
                .foregroundStyle(model.navigation == selection ? Palette.accent : Color.primary)
                .background(model.navigation == selection ? Palette.accentFill.opacity(0.11) : .clear, in: RoundedRectangle(cornerRadius: 6))
        }.buttonStyle(.plain).padding(.horizontal, 10).padding(.bottom, 3)
    }
}

struct AddAccountSheet: View {
    @ObservedObject var model: CompanionModel
    @State private var provider = "claude"
    @State private var name = ""
    @State private var shared = false
    @State private var shareHistory = false
    var body: some View {
        VStack(alignment: .leading, spacing: 19) {
            Text("Add an account").font(.title2.weight(.semibold))
            Picker("Provider", selection: $provider) {
                Text("Claude").tag("claude")
                Text("ChatGPT · Codex").tag("codex")
            }.pickerStyle(.segmented).tint(Palette.accentFill)
            TextField("Account label, such as Work", text: $name).textFieldStyle(.roundedBorder)
            if provider == "claude" {
                Toggle("This Claude login is shared with other people", isOn: $shared).tint(Palette.accentFill)
                Toggle("Show my existing local Code history in this account", isOn: $shareHistory).tint(Palette.accentFill)
                Text(shared ? "Shared logins keep Remote Control blocked. Model requests still go to Anthropic." : "Desktop login and live usage each use the official Claude sign-in. Your existing accounts stay saved.")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            } else {
                Text("Connect a ChatGPT subscription through the official Codex CLI. This creates a separate local Codex profile; it does not change your ChatGPT desktop login.")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Button("Cancel") { model.showAdd = false }.keyboardShortcut(.cancelAction)
                Spacer()
                Button("Add account") {
                    var args = ["add", provider, name]
                    if shared { args.append("--shared") }
                    if shareHistory { args.append("--share-history") }
                    model.showAdd = false
                    model.perform(args)
                }.buttonStyle(.borderedProminent).tint(Palette.accentFill).keyboardShortcut(.defaultAction)
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }.padding(28).frame(width: 470)
    }
}

struct HistorySheet: View {
    let account: CompanionAccount
    @ObservedObject var model: CompanionModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label("Continue in \(account.name)", systemImage: "arrow.triangle.2.circlepath").font(.title2.weight(.semibold))
            Text("Finish or stop the current turn in the source account. Also stop any work running in \(account.name).")
                .font(.system(size: 14, weight: .medium)).fixedSize(horizontal: false, vertical: true)
            Text("The companion will refresh and reopen only \(account.name). Then select the same conversation in Code → Local. The source window can stay open, and your login stays saved.")
                .font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("Cancel") { model.confirmHistory = nil }.keyboardShortcut(.cancelAction)
                Spacer()
                Button("Refresh and reopen \(account.name)") {
                    model.confirmHistory = nil
                    model.perform(["refresh-history", account.id], account: account)
                }.buttonStyle(.borderedProminent).tint(Palette.accentFill)
            }
        }.padding(28).frame(width: 490)
    }
}

struct MenuAccountRow: View {
    let account: CompanionAccount
    @ObservedObject var model: CompanionModel
    let inspect: () -> Void
    let launch: () -> Void
    @State private var hovering = false
    var body: some View {
        HStack(spacing: 10) {
            AccountMark(account: account, size: 29)
            Button(action: inspect) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(account.name).font(.system(size: 12, weight: .semibold))
                    StateLabel(account: account)
                }.frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
            }.buttonStyle(.plain)
            VStack(alignment: .trailing, spacing: 3) {
                Text(account.remainingLabel + (account.usage.limitingWindow == nil ? "" : " left"))
                    .font(.system(size: 12, weight: .medium)).monospacedDigit()
                    .foregroundStyle(account.usage.isFresh ? Color.primary : .secondary)
                Text(account.usage.limitingWindow?.label ?? "—").font(.system(size: 9)).foregroundStyle(.secondary)
            }
            Button(action: launch) { Image(systemName: "arrow.up.right").frame(width: 21, height: 23) }
                .buttonStyle(.borderless).help(account.openLabel)
                .disabled(model.actionInFlight != nil)
        }.padding(.horizontal, 15).padding(.vertical, 12)
            .background(hovering ? Color.primary.opacity(0.035) : .clear)
            .onHover { hovering = $0 }
    }
}

struct CompanionMenu: View {
    @ObservedObject var model: CompanionModel
    let showWindow: (String) -> Void
    let dismiss: () -> Void
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("SessionPier").font(.system(size: 14, weight: .semibold))
                    Text(model.demo ? "Example data · preview" : model.isRefreshing ? "Updating usage…" : "\(model.connectedCount) live · \(model.refreshLabel.lowercased())")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                Spacer()
                Button { model.refreshUsage(force: true) } label: {
                    Image(systemName: "arrow.clockwise").font(.system(size: 12)).frame(width: 24, height: 24)
                }.buttonStyle(.borderless).disabled(model.isRefreshing).help("Refresh usage now")
            }.padding(16)
            Divider()
            ScrollView {
                VStack(spacing: 0) {
                    if model.accounts.isEmpty {
                        Text(model.isLoading ? "Loading your accounts…" : "Add your first account in the companion.")
                            .font(.system(size: 12)).foregroundStyle(.secondary).padding(24)
                    }
                    ForEach(model.accounts) { account in
                        MenuAccountRow(account: account, model: model, inspect: {
                            model.select(account); dismiss(); showWindow("accounts")
                        }, launch: {
                            dismiss()
                            if !account.isClaude || !account.desktopLoginSaved { showWindow("accounts") }
                            model.open(account)
                        })
                        if account.id != model.accounts.last?.id { Divider().padding(.leading, 54) }
                    }
                }
            }.frame(height: min(410, CGFloat(max(1, model.accounts.count)) * 67))
            Divider()
            HStack {
                Button { dismiss(); showWindow("accounts") } label: { Label("Open companion", systemImage: "macwindow") }
                    .buttonStyle(.borderless).font(.system(size: 11))
                Spacer()
                Button { dismiss(); showWindow("settings") } label: { Image(systemName: "gearshape") }
                    .buttonStyle(.borderless).help("Settings")
                Button { NSApp.terminate(nil) } label: { Image(systemName: "power") }
                    .buttonStyle(.borderless).help("Quit SessionPier")
            }.padding(14)
        }.frame(width: 370).fixedSize(horizontal: false, vertical: true).background(Palette.surface).tint(Palette.accent)
    }
}

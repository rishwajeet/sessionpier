# Architecture and data

## Native shell

`Accounts.swift` owns the app lifecycle, menu bar, windows and keyboard shortcut. `CompanionViews.swift` renders account identity, reported quota windows, connection repair and settings. `CompanionModel.swift` runs backend work off the main thread. A local read runs every 15 seconds; due network refreshes are considered every 30 seconds. Quitting stops polling.

## Provider adapters

`usage_service.py` uses the unmodified official clients. Claude runs `/usage` in a bounded PTY, safe mode, with hooks and remote MCP disabled. It checks both account UUID and organization UUID against the selected Desktop identity before and after the probe. It does not store terminal output. Codex uses an initialized app-server stdio connection, reads the account, reads rate limits, and checks the account again. No inference turn is started.

`companion.py` isolates caches and locks per account, limits concurrent refreshes to two, keeps a last successful reading on temporary failure, and backs off on errors. A user refresh has a minimum spacing of 15 seconds. Unreported windows are unknown rather than zero. Multiple Codex limit buckets stay distinct; the primary window is not assumed to be a five-hour window.

## Profiles and continuity

`claude_profile.py` retains the original profile implementation. The signed `/Applications/Claude.app` is opened with a separate user-data root for additional accounts. Protected or history-isolated profiles also use their own Code configuration root. Existing local profiles keep their previous sharing behavior; new profiles default to history sharing off through the companion.

When sharing is enabled, CLI history directories point to their original local files. Desktop sidebar records are copied with authentication-related launch fields removed and are indexed under the destination's real account and organization. This operation refuses an active destination and keeps source transcripts in place. It does not merge provider credentials, cloud chat histories or account-scoped connectors.

## Stored data

For backward compatibility, the root is `~/Library/Application Support/Claude Profiles/`. It contains the profile registry, additional Desktop/CLI homes, reversible synchronization backups, a companion settings file, normalized per-account usage caches and a bounded seven-day numeric reading history. The original Desktop and CLI data remain in their normal locations. No network service receives this cache from SessionPier.

## Packaging

The installed `.app` contains the native binary, backend scripts and a relocatable managed Python runtime. It does not depend on a checkout or a virtual environment. Official AI clients are installed separately. The bundle identifier remains stable across the rename from the original private utility, preserving app preferences.

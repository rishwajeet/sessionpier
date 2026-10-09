# Beta verification

Verified on October 10, 2026 (Asia/Kolkata), on an Apple silicon Mac running macOS 27.0.1. This records observed results and the remaining coverage limits.

## Automated and packaging checks

- 41 Python 3.13 regression tests pass. They cover profile isolation, credential exclusions, shared-account protection, history opt-out at creation and resync, destination-only history refresh, quota parsing, account and organization identity, cache freshness, locks, retry backoff and error redaction.
- The three Swift sources compile with a macOS 13 deployment target.
- The installed app includes a relocatable Python 3.13 runtime and backend. Its snapshot command was run successfully from an unrelated working directory with no source-tree dependency. No bundle symlink points outside the app.
- Runtime entrypoints disable Python bytecode writes. The builder imports the backend after signing and then verifies the sealed bundle, guarding against runtime caches invalidating the signature.
- The app passes `codesign --verify --deep --strict` with an ad-hoc signature. This is not Developer ID signing or notarization.

## Observed integration behavior

The official Claude Code `/usage` probe returned session and weekly quota readings and reset text without an inference request. The official Codex app server returned the signed-in account and its rate-limit windows. The parser uses each reported duration: a primary window is not assumed to mean five hours.

With the app running, successive automatically refreshed source timestamps advanced by about 314 seconds for Claude and 314 seconds for Codex. The 1, 5 and 15 minute interval controls are wired to the backend schedule; five minutes is the default. Missing sign-ins remained actionable connection errors and retained explicitly labelled Desktop snapshots where available.

Three existing Claude Desktop logins remained saved through installation and rename. The already-running Desktop profile kept the same process ID. Only one managed SessionPier app remained installed; outgoing managed bundles were kept as verified ZIP archives.

## Native interface

Real app captures cover the account workspace, complete menu bar popover, settings and add-account sheet in dark appearance. Filtering and selected-account details, the quick-access keyboard command, example-data mode and connection guidance were exercised. Public screenshots use only bundled synthetic accounts.

## Remaining coverage and integration limits

- One Claude account and the existing Codex account were live-tested. Two additional Desktop accounts still required separate official CLI sign-in; one provider authorization page left its Authorize button disabled. This beta does not bypass provider authentication or organization policies.
- Adding isolated Codex profiles is implemented, but a second paid Codex subscription was not available for an end-to-end live account-switch test.
- Native notification delivery and launch-at-login behavior are implemented but were not exercised through OS permission and login cycles.
- A clean second Mac, macOS 13 itself, Intel hardware, light appearance and minimum-window-size coverage remain unverified.
- The global shortcut was observed through the app's keyboard command; conflict handling is implemented, but system-wide shortcut behavior in every other application was not exhaustively checked.
- Claude's usage adapter reads a native CLI screen, which can change between provider releases. Failures are reported explicitly with bounded retries.
- ChatGPT integration covers Codex limits and isolated Codex CLI sessions. Other ChatGPT model quotas and ChatGPT Desktop switching are outside this release.

The public release is a beta for these reasons. Existing local-history continuation was exercised before this redesign; this release's synthetic regression tests recheck the privacy and isolation behavior without interrupting ongoing Desktop work.

# Product direction and first release

A macOS companion for people using several AI subscriptions: see current capacity, choose the intended identity, continue local work.

## First release

- Native menu bar with an optional full account window and keyboard access.
- Automatic, bounded refresh through native provider clients; timestamps, reset information, per-account errors and retry backoff.
- Claude usage through the official CLI's built-in /usage, with account identity checked against Desktop. Existing Desktop snapshots are a labelled fallback only.
- Codex usage through the documented app-server account/rateLimits/read method, supporting distinct CLI homes. It is not a meter for all ChatGPT web models.
- Saved account connections, quick launch, local Code history refresh, and clear shared-account protection.
- Per-account usage detail, sensible empty states, connection repair and manual refresh.
- Preferences for refresh interval and optional capacity notifications, with no model requests or automatic paid actions.
- Portable, self-contained app packaging, generic documentation, fixtures and CI suitable for a GitHub release.

## Differentiation

Usage monitors already exist. This product ties capacity to account identity and the actual continuation workflow. Keep the official provider applications doing the AI work; make changing context less painful.

## Later releases

- Workspace-specific account preferences and explicitly selected history-sharing groups.
- Recent-session search and direct continuation when the provider exposes a stable route.
- Longer-term capacity trends and pacing, with enough real samples to avoid invented forecasts.
- Additional providers and Windows/Linux interfaces.
- Additional ChatGPT surfaces only where limits and switching are verifiable.

## Launch facts still to resolve

Developer ID signing/notarization and documented testing on a clean second Mac. SessionPier uses the MIT license. The first release must label any remaining integration limitation honestly.

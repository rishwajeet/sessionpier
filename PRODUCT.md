# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

The first public release is macOS only. The existing implementation uses native SwiftUI and AppKit. Windows and Linux are later, not launch commitments. Mac conventions govern this surface; no mobile layout is implied.

## Users

Power users with multiple Claude subscriptions who need to see available usage and continue local work across accounts. The owner also wants a path to multiple ChatGPT subscriptions.

## Product Purpose

Keep account capacity, identity, and the next useful action one glance away. Reduce the friction of switching accounts while preserving the user's intended local work and privacy boundaries.

## Operating Context

Menu bar first, with a larger window on demand, as accepted by the owner on October 10, 2026. Existing users work in the Code tab of official Claude Desktop. Existing saved accounts, data and running work must survive upgrades.

## Capabilities and Constraints

- Automatic usage updates are a primary requirement. An old local snapshot must never appear as a fresh server reading.
- Preserve saved logins, separate account identity and account-scoped connectors, and local conversation continuity.
- Keep shared-account Remote Control protection. Cross-account conversation access is local and deliberate.
- Never auto-switch a running model request or mix two accounts' credentials.
- Claude limits can be read through the official CLI's built-in usage command without sending a model message. Each profile requires its own native CLI login, verified against Desktop identity.
- Codex exposes account/rateLimits/read through its official app server. Scope those readings to Codex; general ChatGPT message-limit coverage is not yet established.
- GitHub publication is an intended outcome. Public materials must contain generic examples rather than this user's local account identities, client names, transcripts, or paths.

## Brand Commitments

The public product is SessionPier, with an indigo icon and a provider-neutral identity. The owner delegated product improvements and chose building the working native interface directly rather than visual mockups.

## Evidence on Hand

Existing source, 41 passing backend tests, verified cross-account conversation continuation, saved usage snapshots, privacy checks, and native UI captures. Private verification material stays outside public release content. A live official-CLI usage probe on October 10 returned quota percentages and reset information with zero inference tokens.

## Product Principles

1. Account identity is always explicit.
2. Show measured capacity, provenance, and freshness honestly.
3. Preserve work; never interrupt an active conversation to improve a meter.
4. Make the common action immediate, with details available when needed.
5. Keep account credentials with the provider's native authentication flow.

## Open Decisions

SessionPier ships under MIT. Notifications are off by default. Initial binaries are ad-hoc signed; Developer ID signing and notarization remain follow-ups.

---
name: SessionPier
description: A native macOS companion for comparing account capacity and continuing local work.
colors:
  accent-fill: "rgb(36% 38% 83%)"
  accent-foreground-light: "rgb(30% 32% 75%)"
  accent-foreground-dark: "rgb(64% 66% 100%)"
  claude-identity: "rgb(72% 38% 24%)"
  codex-identity: "rgb(12% 53% 43%)"
typography:
  headline:
    fontFamily: "system-ui"
    fontSize: "24pt"
    fontWeight: 600
  title:
    fontFamily: "system-ui"
    fontSize: "20pt"
    fontWeight: 600
  capacity:
    fontFamily: "system-ui"
    fontSize: "18pt"
    fontWeight: 500
    fontFeature: "tnum"
  account:
    fontFamily: "system-ui"
    fontSize: "13pt"
    fontWeight: 600
  body:
    fontFamily: "system-ui"
    fontSize: "12pt"
    fontWeight: 400
  label:
    fontFamily: "system-ui"
    fontSize: "11pt"
    fontWeight: 400
  metadata:
    fontFamily: "system-ui"
    fontSize: "10pt"
    fontWeight: 400
rounded:
  control-well: "6pt"
  attention: "8pt"
spacing:
  compact: "5pt"
  related: "8pt"
  control: "12pt"
  detail: "22pt"
  workspace: "24pt"
  sheet: "28pt"
components:
  button-primary:
    backgroundColor: "{colors.accent-fill}"
  navigation-selected:
    rounded: "{rounded.control-well}"
    padding: "9pt 11pt"
  search-field:
    rounded: "{rounded.control-well}"
    padding: "7pt"
    width: "155pt"
  account-row:
    padding: "17pt 15pt"
  menu-account-row:
    padding: "12pt 15pt"
  attention-panel:
    rounded: "{rounded.attention}"
    padding: "{spacing.control}"
---

# Design System: SessionPier

## Overview

**Creative North Star: "The Quiet Timetable"**

SessionPier uses the rhythm of a timetable: stable account rows, aligned capacity figures, restrained separators, and a clearly associated next action. Its materials are native macOS surfaces and controls. The reference shapes information density and comparison; it does not turn the interface into a literal railway display.

The product is a quiet utility with explicit identity and reading provenance. Indigo marks selection and action, while provider colors identify accounts and semantic colors describe capacity. Compact text and tabular figures make comparisons possible without adding decorative panels. The menu and full window share this vocabulary.

This record is extracted from src/CompanionViews.swift, src/CompanionModel.swift, and src/Accounts.swift. Dark-appearance captures with labelled example data were visually inspected. Light appearance is implemented through adaptive colors but has not been visually verified in this documentation pass. Native geometry is measured in macOS logical points; frontmatter pt values retain the source measurements, not a web layout specification.

**Key Characteristics:**

- Native SF typography and macOS control behavior.
- Stable rows and tabular capacity figures.
- Indigo selection; provider identity and usage status kept independent.
- Explicit unknown, saved, and stale readings.

## Colors

A restrained indigo action palette sits on adaptive macOS neutrals, with earthy provider identities and independent semantic status colors.

### Primary

- **Pier Indigo** (`accent-fill`): the constant fill for prominent actions, segmented controls, and toggles. Its lower-opacity forms mark the selected account row (0.09) and selected sidebar destination (0.11).
- **Readable Indigo** (`accent-foreground-light`, `accent-foreground-dark`): the light- and dark-appearance foreground variants of `Palette.accent`. They color links, borderless actions, selected navigation text, and normal capacity meters. The appearance resolver, not a screenshot sample, chooses the variant.

### Secondary

- **Terracotta Identity** (`claude-identity`): Claude account symbols and their softly tinted wells.
- **Teal Identity** (`codex-identity`): Codex account symbols and their softly tinted wells.

These are provider-level colors in the current implementation. They are not unique account colors and do not express capacity.

### Neutral

Native colors deliberately have no fixed RGB token in the frontmatter:

| Source | Implemented role |
| --- | --- |
| `NSColor.windowBackgroundColor` | Main window background |
| `NSColor.underPageBackgroundColor` | Navigation rail |
| `NSColor.controlBackgroundColor` | Account detail and menu surfaces |
| `Color.primary` | Main text and neutral opacity overlays |
| `.secondary` | Supporting text and unavailable or older readings |
| `.tertiary` | Inactive row chevrons |

`Color.primary` at 0.09 provides row seams; 0.075 provides meter tracks; 0.035 provides row hover and search wells. These stay relative to the current native foreground. The implementation does not define a fixed neutral ramp.

Status uses native `.green`, `.orange`, and `.red`. A fresh reading below 80% used is green; 80% or more is orange; 100% or more is red. Unfresh status is secondary. Capacity bars use indigo below the warning threshold, orange at 80%, and red at 100%. Unknown measurements have no filled segment. Alert panels use orange at 0.055 behind a 0.18 border.

**The Separate Signals Rule.** Use provider tint for identity, indigo for action or selection, and semantic status colors for measured capacity. Keep a text label beside status color.

## Typography

**Interface Font:** the macOS system font, selected through SwiftUI `.system` and native text styles. `system-ui` in the portable frontmatter denotes that native family; it is not an instruction to introduce a web font.

**Figure Treatment:** `.monospacedDigit()` for percentage readouts. The diagnostic sheet alone uses `.system(size: 11, design: .monospaced)`.

**Character:** compact, direct, and legible within macOS utility conventions. Type size and weight establish hierarchy without a separate editorial display face.

### Hierarchy

- **Headline:** workspace and Settings titles use the headline token.
- **Title:** selected-account identity uses the title token. Modal headings use the native `.title2` style with semibold weight; its resolved size is owned by the OS.
- **Capacity:** the main row percentage uses the capacity token. Menu readouts use 12-point medium text with monospaced digits.
- **Account:** main row names use the account token; menu names use 12-point semibold.
- **Body:** supporting explanations use the body token; native settings controls retain platform defaults.
- **Label:** status, reset time, connection information, and row actions use the label token, with medium weight for action or section emphasis.
- **Metadata:** provenance, refresh context, and limiting-window captions use the metadata token. Functional column headings use 9-point medium uppercase text with 0.5-point tracking; this is a local table-label treatment, not a general heading role.

No custom line-height scale is defined. SwiftUI controls text metrics. Long explanatory text in details and sheets can wrap vertically.

**The Native Type Rule.** Use the macOS system font for interface text and SF Symbols for native iconography. Apply monospaced digits to changing capacity figures, not to ordinary prose.

## Layout

The menu is a 370-point-wide native popover. Its account area is a scroll view, sized to 67 points per account and capped at 410 points; its header and footer remain outside the scroll area. Rows keep identity left, capacity right, and the launch control at the far edge. Insets are 15 points horizontally and 12 vertically.

The full window starts with a 1050 × 720-point content rectangle and has a native minimum window size of 955 × 645 points. Its root content minimum is 955 × 610 points. A fixed 165-point navigation rail sits beside the workspace. Within an `HSplitView`, the account list has a 345-point minimum width; the detail pane has a 275-point minimum, 295-point ideal, and 325-point maximum width. These are macOS constraints, not responsive web breakpoints.

The workspace uses 24-point outer header insets and a 310-point provider picker. The search well has a 155-point width. Account rows use 15-point horizontal and 17-point vertical insets, with a 116-point capacity column and a 57-point action slot. The detail body scrolls independently above its fixed action area; its body inset is 22 points and action inset 18 points.

Settings uses a centered content region capped at 760 points with 30-point padding. Account and history sheets use 28-point padding and measured content widths of 470 or 490 points. There is no mobile layout in the implemented system.

Related labels use compact 5–8-point gaps; component groups commonly use 12 points. Detail groups use 22 points, and meter groups use 20 points. Preserve these observed relationships rather than forcing every one-off measurement onto an invented scale.

## Elevation & Depth

No custom shadows are defined in the native view source. Depth comes from different semantic surfaces, half-point row seams, `Divider`, subtle selected or hover fills, and macOS-owned windows, popovers, sheets, and controls. A rounded attention panel is an exception for actionable connection context, not the default wrapper for every content block.

**The Quiet Surface Rule.** Separate regions with native surfaces, hairlines, and low-opacity state fills. Leave window, popover, sheet, and control elevation to macOS.

## Shapes

Controls and status wells use restrained rounding. Search and selected navigation use the control-well token; connection attention panels use the attention token. Account marks scale proportionally: symbol size is 0.44 of the mark size and corner radius is 0.23 of the mark size, with the provider tint at 0.11 behind it. Marks are 29 points in the menu, 34 in account rows, and 40 in details.

Capacity tracks are capsules (5 points high in the detail view). The source also supports a compact 3-point variant, but the inspected surfaces use the standard detail variant. Positive usage has at least a 2-point fill and is capped at the available track width. Prominent button geometry, popover corners, sheet corners, and native field borders belong to macOS and have no fixed custom radius token.

## Components

### Buttons

Native controls with a clear action hierarchy.

- **Primary:** `.borderedProminent`, tinted with `accent-fill`. The detail action uses large control size; sheets retain native standard sizing. Button text, shape, padding, focus, and disabled rendering come from the native control style.
- **Secondary:** `.bordered` for local Code continuation. Eligibility and a global in-flight operation can disable it.
- **Borderless:** compact row, popover, toolbar, and refresh actions use native borderless behavior where specified.
- **Plain:** account selection and sidebar navigation supply their own background states while retaining native button semantics.
- **Busy:** refresh replaces its symbol with a small native progress indicator; in-flight action controls are disabled where implemented. No custom pressed, focus-ring, or hover motion token exists.

### Account Rows

Stable comparison rows rather than floating cards. The selected row receives an indigo fill at 0.09; unselected hover uses primary at 0.035. A half-point lower seam separates rows. Selection reveals an Open action in the fixed trailing slot; unselected rows show a chevron. The selection background animates with a 0.2-second ease-out unless Reduce Motion is enabled.

A new fresh measurement adds a green overlay at 0.055 for 1.2 seconds. This overlay appears and clears without a custom animation. Refresh does not sort rows. Old values remain secondary and their labels indicate missing, saved, or outdated data.

### Capacity Lines

A labelled percentage, capsule track, and reset text form one accessible unit. Fill opacity is 0.85 for fresh measurements and 0.4 for stale ones. Remaining capacity in account rows comes from the most-used reported window; the detail line expresses percentage used. Preserve that distinction in labels. Missing values say “Not reported,” and an elapsed reset says “Reset due · awaiting refresh.”

### Status and Identity

`AccountMark` pairs native SF Symbols with provider tint and hides the redundant decoration from accessibility. `StateLabel` places a 5-point status dot next to 11-point status text. Color never carries the status alone. The local OPEN badge is a running-app state marker, not a promotional label or a reusable heading treatment.

### Attention Panels and Settings Groups

Connection guidance uses the rounded attention panel with a half-point orange stroke and a specific next action. Settings groups use native `GroupBox`, with native toggles, pickers, and separators. Their chrome remains platform-owned.

### Inputs and Navigation

Search uses a plain native text field inside the measured rounded well and a secondary search symbol. The account-name form uses `.roundedBorder`. Segmented provider pickers use native selection behavior with the constant accent fill. No custom focus treatment replaces platform focus.

The sidebar uses 12-point text, medium when selected and regular otherwise. Selected text uses the adaptive accent; the selected background uses the constant fill at 0.11. Each item has 11-point horizontal and 9-point vertical padding. The menu footer uses native borderless controls for the companion window, Settings, and Quit.

### Documentation Preview Boundary

The sidecar's self-contained HTML/CSS previews are illustrative browser translations of these native components. CSS system colors and browser-native control behavior stand in for unresolved macOS semantics; they are not pixel-exact AppKit rendering. Synthesized tonal strips in sidecar metadata are documentation aids, not additional application tokens. Native source remains authoritative.

The captured QUICK ACCESS eyebrow uses 8-point uppercase text. It is a carried craft defect and is excluded from the reusable type ramp. Light appearance, focus traversal, interaction timing, and Reduce Motion behavior have not been visually exercised in this documentation pass; source inspection is not that verification.

## Do's and Don'ts

### Do:

- Do preserve the separation between provider identity, selection, and usage status.
- Do show the limiting window beside remaining capacity and retain reading provenance in account details.
- Do use semantic native surfaces and foreground styles so appearance follows macOS.
- Do keep capacity figures aligned with monospaced digits and keep row order stable during refresh.
- Do retain the measured native spacing and let standard controls own their focus and disabled states.
- Do label example data clearly in public captures and keep account names and addresses generic.

### Don't:

- Don't substitute a sampled dark screenshot color for a semantic NSColor.
- Don't display a missing limit as unused capacity or give an older reading the visual authority of a fresh one.
- Don't repurpose provider identity colors as warning or success states.
- Don't add custom shadows or animated row reordering to this restrained native utility.
- Don't promote the small QUICK ACCESS eyebrow into a reusable heading style.

# DESIGN.md — SIH26189 Intelligence Workspace

Visual system for a criminal-network analysis tool built for law enforcement analysts.
Reference: Palantir Gotham × Bloomberg Terminal. Instrument, not marketing site.

## Color

```
--c-bg:            #070b11   graphite — page base
--c-surface:        #0c1119   panel base, one step up from bg
--c-surface-raised:#111826   raised panel / active row
--c-line:           #1c2531   hairline borders, dividers
--c-line-strong:    #2a3543   emphasized borders (panel headers)
--c-text:           #dde3ec   primary text
--c-text-dim:       #7c8798   secondary / label text
--c-text-faint:     #4c5666   tertiary, disabled
--c-signal:         #4aa6ff   ONLY accent — links, active state, primary data highlight
--c-signal-dim:     #1f3550   signal at low opacity for backgrounds/fills
--c-red:            #d43640   kingpin/boss flag ONLY — never decorative
--c-gold:           #f2c440   kingpin/boss flag ONLY — never decorative
--c-green:          #35b874   positive delta / online state (data semantics only)
--c-overlay:        rgba(13,17,25,0.86)  overlay scrim — drawers, modals, command palette only
```

No gradients. No decorative icon sets. Red/gold never appear except bound to a flagged
entity's kingpin/boss status (badge, row accent, node fill, KPI tied directly to a flagged count).
They never signal generic status (errors, pipeline delay, warnings) — use `--c-text-dim` or
`--c-green` for that; red/gold are reserved exclusively for the criminal-flag semantic.

## Type

- UI labels, nav, buttons, chrome, prose, table cell text: **DM Sans** (400/500/700)
- ALL analytics-derived values — IDs, counts, percentages, timestamps, scores, coordinates:
  **IBM Plex Mono** (300/400/500/600). Zero exceptions — if it was computed or measured, it's mono.
- Scale (px): 11 / 12 / 13 / 15 / 18 / 24 / 36 / 56 — no in-between values.
- **Headline metrics** (KPI values, panel-level totals): IBM Plex Mono, weight **300**, the largest
  step the context allows (36/56px), `letter-spacing: var(--ls-metric)`. Light weight at large size
  reads as precision instrumentation, not a marketing stat — never bold a headline number.
- **Section labels** (panel bezel titles, KPI captions, table-independent group headers only —
  never a caption floating above a heading that already reads fine on its own): 11px, weight 600,
  `text-transform: uppercase`, `letter-spacing: var(--ls-label)`, color `--c-text-dim`. This is the
  one sanctioned use of caps in the system — it marks a structural instrument label, not decorative
  emphasis, and must never be applied to prose, nav item names, or table body text.
- Everything else — nav labels, table headers, body copy, button text — sentence case, DM Sans.

## Spacing

4px base unit. Only these values are permitted anywhere in the app:
```
--sp-1: 4px   --sp-2: 8px   --sp-3: 12px   --sp-4: 16px
--sp-5: 24px  --sp-6: 32px  --sp-7: 48px   --sp-8: 64px
```

## Letter-spacing & motion tokens

```
--ls-label:      0.08em   section labels (uppercase, 11px/600)
--ls-metric:     0.01em   headline metric numbers (mono, weight 300)
--ease-standard: cubic-bezier(0.2, 0, 0, 1)
--dur-fast:      160ms    hover / focus / state changes
--dur-overlay:   220ms    drawer / modal entry
--dur-pulse:     900ms    live-update value pulse
--blur-overlay:  16px     backdrop-filter amount, overlays only

--ease-cinematic: cubic-bezier(0.16, 1, 0.3, 1)   graph-canvas entrance only
--dur-entrance:   220ms   node stagger-in on first layout
--dur-breathe:    5200ms  idle node opacity breathing (unflagged only)
--dur-ping:       3200ms  kingpin/boss expanding radar ring
--dur-glow-aura:  4000ms  kingpin/boss soft halo pulse
--dur-signal:     720ms   traveling pulse along an edge on selection
--dur-flow:       3600ms  dash-creep on edges touching a flagged entity
```

## Structure

- 0 border-radius everywhere, no exceptions. Panels are instrument bezels: 1px `--c-line` border,
  flat fill, a 2px `--c-line-strong` top rule carrying a section label + optional live value/meta.
  KPI tiles use the same bezel grammar (top rule + label) rather than a distinct "card" style —
  there is one panel language in this app, not two.
- No card grids of identical repeated boxes — panel sizes reflect data weight (asymmetric).
- Dense tabular data by default; whitespace is earned, not decorative.
- No hero sections, no centered marketing copy, no blue call-to-action buttons.
- A grid must resolve with no unaccounted space — every row/column track in a workspace grid
  terminates flush against real content, never dead air. If content doesn't fill a track, the
  layout is wrong, not the content.

## Elevation

- Base workspace panels (dashboard tiles, tables, the rail, the top bar) are flat and solid —
  `--c-surface` / `--c-surface-raised`, no blur, no shadow. This is the resting state of the app
  and must stay cheap to render at density.
- `backdrop-filter: blur(...)` is reserved for true overlays that float above the workspace and
  temporarily obscure it: drawers, modals, the command palette, toasts. Overlay surface:
  `--c-overlay` (`rgba(13,17,25,0.86)`) with `--blur-overlay` (16px). Never apply blur to a panel
  that is part of the base layout.

## Motion

- Functional only: state transitions, focus rings, drawer/panel entry, live-data pulses that mark
  a value which just changed. Nothing plays on page load for its own sake.
- Standard transition: `160ms cubic-bezier(0.2, 0, 0, 1)` (`--ease-standard`) for hover/focus/state
  changes. Drawer/overlay entry: `220ms` on the same curve.
- Live-update pulse: a value that changes under a "live" panel briefly takes `--c-signal-dim` as a
  background and fades back over 900ms — long enough to notice, short enough to never be mistaken
  for a persistent state. One pulse per change, never looping.
- Every animated rule is paired with a `prefers-reduced-motion: reduce` override that drops to an
  instant or near-instant (≤1ms) transition. No motion in this app is load-bearing for comprehension.

**Graph canvas exception.** The relationship graph (Network page) is the one surface allowed a
denser motion vocabulary — it's a live surveillance instrument, not a form or a table, and stillness
there reads as broken rather than calm. Rules specific to it:
- Idle "breathing" (unflagged nodes) and the kingpin/boss radar ping/halo loop continuously, but at
  slow, staggered, low-amplitude rates (`--dur-breathe`, `--dur-ping`, `--dur-glow-aura`) — never in
  unison, never fast enough to read as a notification or a screensaver.
- A traveling pulse along an edge (`--dur-signal`) fires once per selection change, staggered per
  edge, never loops.
- Edges touching a flagged entity carry a slow dash-creep (`--dur-flow`) toward the flagged end —
  this is the one place motion substitutes for the gradient-fill "signal flow" look a designer would
  reach for elsewhere; still no gradient function used anywhere in its implementation.
- A vignette and a barely-visible rotating sweep exist as static/near-static atmosphere on the
  canvas only — implemented via `box-shadow` and a flat-opacity rotating `clip-path` wedge
  respectively, specifically to stay inside the no-gradient rule above.
- Every one of these still collapses to a static or ≤1ms equivalent under `prefers-reduced-motion`.

## Layout grammar

Top bar (system status, 40px, mono values) → left rail (nav, mono glyph + sentence-case label,
168px, persistent — not a collapsing icon rail: analysts run this tool for hours across seven
workspaces, and a labeled rail beats memorized glyphs for a tool this dense) → main workspace,
split into asymmetric instrument panels via CSS grid, panel spans set per page by data density,
not by even columns.

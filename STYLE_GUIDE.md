# Style Guide — AI Running Coach

Design system for the frontend. The goal is a tool that looks like serious
software: quiet, dense with information, fast to scan. **No "AI slop"**: no
gradients, no purple, no glows, no glassmorphism, no floating blobs, no emoji as
icons, no marketing-style hero sections inside the app.

## Principles

1. **Utility over decoration.** Every visual choice must aid reading or
   interaction. If a shadow, border, or animation doesn't help, delete it.
2. **Flat and honest.** Solid colors, 1px borders, minimal elevation. The UI is
   a form and a table, not a landing page.
3. **One accent.** Deep blue is the only brand color. Everything else is
   neutral; semantic colors exist only for status and training zones.
4. **Type does the work.** Hierarchy comes from size/weight/spacing, not color
   or boxes-in-boxes.
5. **Both themes, same structure.** Dark mode is a token swap, never a
   redesign.

## Color tokens

Implemented as CSS custom properties on `:root` (light) and
`[data-theme="dark"]`. Components must reference tokens, never raw hex.

### Neutrals

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--bg` | `#FAFAF8` (warm off-white) | `#121417` | App background |
| `--surface` | `#FFFFFF` | `#1A1D21` | Cards, panels, inputs |
| `--surface-2` | `#F2F2EF` | `#22262B` | Subtle fills, table striping, hover |
| `--border` | `#E2E2DC` | `#31363D` | All borders, dividers |
| `--text` | `#1B1D21` | `#E8E9EB` | Primary text |
| `--text-muted` | `#5F6368` | `#9BA1A8` | Secondary text, labels, hints |

### Accent (deep blue)

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--accent` | `#1D4ED8` | `#6C9BF5` | Primary buttons, links, active states, focus rings |
| `--accent-hover` | `#1E40AF` | `#8AB1F8` | Hover on the above |
| `--accent-contrast` | `#FFFFFF` | `#0F1524` | Text/icons on accent fills |
| `--accent-subtle` | `#E8EEFA` | `#1B2A45` | Selected rows, badges, info banners |

### Semantic status

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--success` | `#15803D` | `#4ADE80` | Approved, pushed, valid |
| `--warning` | `#B45309` | `#FBBF24` | Deload, stale data, collision warnings |
| `--danger` | `#B91C1C` | `#F87171` | Fatigue veto, validation errors, destructive actions |

### Training zones (functional, theme-independent)

Zone colors appear in workout steps, badges, and charts. They are the same in
both themes (they encode data, not decoration) and must not be confused with
the accent — Z2 is deliberately teal, not blue.

| Zone | Color | Meaning |
|---|---|---|
| Z1 | `#9CA3AF` gray | Recovery |
| Z2 | `#0D9488` teal | Aerobic base |
| Z3 | `#65A30D` green | Tempo |
| Z4 | `#D97706` amber | Threshold |
| Z5 | `#DC2626` red | VO2max |

Rest days and non-run UI use `--text-muted`.

## Typography

- **Font stack:** `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
  No web fonts for v1 (speed, offline, zero FOUT).
- **Monospace** (`ui-monospace, SFMono-Regular, Menlo, monospace`) for all
  numbers an athlete compares: paces, HR bounds, distances, dates in tables.
  Paces display as `m:ss/km`.
- **Scale:** 12px (labels/hints), 13px (secondary/table dense), 14px (body
  default), 16px (section titles), 20px (page titles), 28px (rare, hero numbers
  like weekly volume).
- **Weights:** 400 regular, 500 medium (labels, table headers), 600 semibold
  (titles, primary button). No light weights, no italics except quotes.
- **Line height:** 1.4 body, 1.2 titles. Letter-spacing 0; uppercase only for
  12px overline labels with `+0.04em`.

## Spacing, radius, borders

- **Spacing scale (4px base):** 4, 8, 12, 16, 24, 32, 48. Page padding 24px;
  card padding 16px; form field gap 12px; section gap 32px.
- **Radius:** 6px on cards/inputs/buttons, 4px on badges/chips, 999px only for
  status dots. Nothing rounder.
- **Borders:** 1px `--border` on cards, inputs, tables. Focus: 2px `--accent`
  outline, offset 1px.
- **Shadows:** none in v1. If elevation is ever unavoidable: `0 1px 2px rgba(0,0,0,0.06)` max.

## Components

- **Buttons.** Primary: solid `--accent`, `--accent-contrast` text, 8px 16px
  padding, weight 600. Secondary: `--surface` fill, `--border` border,
  `--text` text. Danger: `--danger` border + text, transparent fill. Disabled:
  50% opacity, no hover. Height 36px default, 28px compact (tables).
- **Inputs.** `--surface` fill, 1px `--border`, 8px 12px padding, 14px text.
  Label above the field, 12px 500 `--text-muted`. Hints/errors below in 12px
  (`--text-muted` / `--danger`). Checkboxes and day-pickers: 18px squares,
  accent fill when checked.
- **Cards.** `--surface`, 1px `--border`, 6px radius, 16px padding. Optional
  16px-weight title row. No nested cards; use `--surface-2` fill or a divider
  instead.
- **Tables.** 13px, header row 12px 500 uppercase-muted, row height 36px, 1px
  row dividers, zebra striping `--surface-2` only on dense tables. Numbers
  right-aligned in monospace.
- **Badges/chips.** 4px radius, 12px, 2px 8px padding. Zone badges: zone color
  text on a 12%-alpha fill of the same color. Status badges: semantic colors
  (`--success` approved/pushed, `--warning` deload/stale, `--danger` veto,
  `--text-muted` draft).
- **Banners.** Full-width inside content, 1px border + 12%-alpha fill of the
  semantic color, 12px padding. Used for fatigue veto, data staleness, push
  collision warnings.
- **Status dots.** 8px circle, semantic color, inline before text.
- **Icons.** Inline SVG, 16px or 20px, 1.5px stroke, currentColor. Lucide
  icon set (via `lucide-react`) — consistent, neutral, no emoji.
- **Empty states.** One line of `--text-muted` text and a single primary
  action. No illustrations.

## Layout

- Max content width **1040px**, centered, 24px side padding. This is a
  dashboard, not a fluid magazine.
- **Top nav:** 56px, `--surface`, bottom border. Wordmark left ("coach",
  lowercase, 600 weight, `--text` — no logo), nav links center-left, user/sync
  controls right. Active link: `--accent` text + 2px bottom border.
- **Pages:** page title (20px) + optional primary action button right-aligned
  on the same row; content sections separated by 32px.
- **Week view** (the core screen): 7-column grid on desktop (one column per
  day, Mon–Sun), collapsing to a vertical list under 900px. Each day is a card:
  date header, session badge, workout name, duration/distance in monospace,
  zone badges, expand for steps.
- Mobile-responsive (usable at 375px) but desktop-first in information density.

## Motion

- Transitions only: 120ms ease on hover/focus color changes, 150ms on
  expand/collapse. No page transitions, no bounce, no skeleton shimmer —
  skeletons are static `--surface-2` blocks.

## Dark mode

- Toggle in nav (sun/moon Lucide icon), persisted to `localStorage`, respects
  `prefers-color-scheme` on first visit. Pure token swap via
  `[data-theme="dark"]` on `<html>`; zero per-component dark CSS.
- Dark theme is *not* pure black; it follows the neutral ramp above. Borders
  get slightly lighter, fills slightly lighter — never darker than `--bg`.

## Accessibility floor

- Contrast ≥ 4.5:1 for all text (tokens above are chosen to satisfy this in
  both themes — if you change one, re-check).
- Every interactive element reachable and visibly focused via keyboard.
- Form errors announced in text next to the field, never color-only.

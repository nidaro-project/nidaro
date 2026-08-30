# Nidaro Design System

The single source of truth for nidaro's visual language. Every screen reads its
colors, type, spacing, and shapes from the tokens defined here and implemented
in `src/nidaro/web/static/css/tokens.css`. If a value is not in this file or in
`tokens.css`, it does not belong in the UI.

The design-goal mockup this system was built from lives at
[docs/design-goal.png](design-goal.png).

## Principles

1. **Warm, calm, competent.** nidaro is a family assistant. Surfaces feel like
   paper and linen, accents feel like a garden, not a control room.
2. **Content first.** Cards carry real family data. Decoration stays behind the
   content: soft shadows, one accent color, generous whitespace.
3. **Tokens, never literals.** Templates and stylesheets outside `tokens.css`
   never contain hex values, font names, or pixel-based spacing scales. They
   reference semantic tokens (`var(--color-accent)`).
4. **Themeable by contract.** Every color decision is a semantic token. Swapping
   the token values under a theme name re-skins the whole product. That contract
   is what will later make per-user themes in settings a data problem, not a
   CSS problem.

## Token architecture

Three layers, one direction of dependency:

```
primitives (scales: sand, leaf, clay, blue, violet, amber)
      ↓
semantic tokens (--color-*, --font-*, --text-*, --space-*, --radius-*, --shadow-*)
      ↓
components (.card, .btn, .nav … — semantic tokens only)
```

- Primitives are named scales, never used directly by components.
- Semantic tokens are defined once for the default theme (`:root` / `[data-theme="daylight"]`)
  and overridden per theme (`[data-theme="meadow"]`, `[data-theme="dusk"]`).
- Components reference semantic tokens only.

The active theme is the `data-theme` attribute on `<html>`. `base.html` boots it
from `localStorage["nidaro-theme"]` before first paint; the settings page
switches it live. When user accounts arrive, the same attribute gets set
server-side from the user's saved preference, and localStorage becomes the
fallback for anonymous visitors. Nothing in the component layer changes.

## Themes

| Theme | id | Feel |
|---|---|---|
| Daylight | `daylight` | Default. Warm paper, deep leaf green. |
| Meadow | `meadow` | Light with a greener cast; surfaces lean sage. |
| Dusk | `dusk` | Dark, mossy, low-glare; accents lighten for contrast. |

Rules for adding a theme:

1. Add a `[data-theme="<id>"]` block in `tokens.css` overriding **every**
   semantic color token. Type, spacing, radius, and shadow geometry stay put;
   only colors (and shadow color inside the same `--shadow-*` values) change.
2. Check category tokens (`--cat-*`): soft backgrounds must stay readable under
   `--color-text` on both light and dark themes.
3. Register it in `SUPPORTED_THEMES` in `src/nidaro/web/static/js/app.js` and in
   the theme list in `src/nidaro/web/routes/ui.py` (settings page).
4. Verify all three states in Chrome (see the chrome-agent workflow) before
   calling it done.

## Color

### Primitive scales

| Scale | 50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 |
|---|---|---|---|---|---|---|---|---|---|---|
| `sand` (warm paper) | `#FAF7F1` | `#F3EEE3` | `#EAE3D3` | `#DAD0BA` | – | – | – | – | – | – |
| `leaf` (brand green) | `#F1F6EC` | `#E1EDD8` | `#C6DCB8` | `#9DC28D` | `#71A663` | `#4F8A47` | `#3E7539` | `#2F5C2F` | `#274B2A` | `#1E3B23` |
| `clay` (terracotta) | – | `#FAE4DC` | – | – | `#E08A64` | `#D96C4F` | `#BE5A3F` | – | – | – |
| `blue` | – | `#EAEDFB` | – | – | – | `#5B67C7` | `#4C57B2` | – | – | – |
| `violet` | – | `#F0EAFB` | – | – | – | `#7C5CC9` | – | – | – | – |
| `amber` | – | `#FBF0DC` | – | – | – | `#D98E2B` | `#B87417` | – | – | – |

Scales only need the stops a theme actually references. Extend a scale, not the
component layer.

### Semantic tokens (Daylight values)

| Token | Value | Used for |
|---|---|---|
| `--color-bg` | `#FAF7F1` | App and sidebar background |
| `--color-surface` | `#FFFFFF` | Cards, inputs, topbar controls |
| `--color-surface-2` | `#F3EEE3` | Hover fill, inset rows, chips |
| `--color-text` | `#253020` | Primary text, headings |
| `--color-text-2` | `#5B6452` | Secondary text, descriptions |
| `--color-text-3` | `#8C937F` | Muted text: dates, placeholders |
| `--color-line` | `#E8E1D0` | Card borders, dividers |
| `--color-line-strong` | `#D8CDB4` | Input borders, checkbox rims |
| `--color-accent` | `#2F5C2F` | Primary buttons, logo tile |
| `--color-accent-strong` | `#274B2A` | Accent hover/pressed |
| `--color-accent-text` | `#3E7539` | Links, "View … →" affordances |
| `--color-accent-soft` | `#E1EDD8` | Active nav pill, AI badge, tags |
| `--color-on-accent-soft` | `#1E3B23` | Text/icon on accent-soft |
| `--color-accent-contrast` | `#FFFFFF` | Text on solid accent |
| `--color-success` | `#3E7539` | Savings, positive deltas |
| `--color-danger` | `#C4453B` | Errors, notification dot |
| `--color-danger-soft` | `#F9E4E1` | Danger backgrounds |
| `--color-warn` | `#B87417` | Warnings |
| `--focus-ring` | `0 0 0 3px rgb(47 92 47 / 25%)` | `:focus-visible` |

### Category tokens

Domain areas own a foreground/background pair so icons, dots, and tinted rows
stay consistent everywhere. `-fg` rides on `-bg`; contrast is the invariant.

| Category | `-fg` | `-bg` |
|---|---|---|
| `--cat-calendar` | `#5B67C7` | `#EAEDFB` |
| `--cat-meals` | `#B87417` | `#FBF0DC` |
| `--cat-shopping` | `#BE5A3F` | `#FAE4DC` |
| `--cat-school` | `#7C5CC9` | `#F0EAFB` |
| `--cat-family` | `#3E7539` | `#E1EDD8` |
| `--cat-notes` | `#6E5FB0` | `#EDEAF8` |
| `--cat-deals` | `#BE5A3F` | `#FAE4DC` |

Semantic status colors (`success`, `danger`, `warn`) beat category colors when a
row communicates state. Category colors only decorate.

## Typography

One family: **Manrope** (Google Fonts, weights 400–800), fallback
`ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif`. Loaded in
`base.html`; no other font may be introduced without changing this file first.

| Token | Size | Weight | Use |
|---|---|---|---|
| `--text-2xl` | 1.625rem (26px) | 800 | Page greeting |
| `--text-xl` | 1.25rem (20px) | 800 | Promo headline, big stats |
| `--text-lg` | 1rem (16px) | 700 | Card numbers |
| `--text-md` | 0.875rem (14px) | 600 | Nav items, card titles, body lead |
| `--text-base` | 0.8125rem (13px) | 400/600 | Default body, list items |
| `--text-sm` | 0.75rem (12px) | 500 | Captions, meta, chips |
| `--text-xs` | 0.6875rem (11px) | 600 | Badges, kbd |

Line height: `--leading-tight: 1.2` for `--text-xl` and up, `--leading-body: 1.45`
for everything else. Headings never ship below weight 700. Numbers in stats use
weight 800 with `font-variant-numeric: tabular-nums`.

## Spacing

4px base. Components use these tokens only:

`--space-2xs: 2px` · `--space-xs: 4px` · `--space-sm: 8px` · `--space-md: 12px` ·
`--space-lg: 16px` · `--space-xl: 20px` · `--space-2xl: 24px` ·
`--space-3xl: 32px` · `--space-4xl: 40px`

Card interior padding is `--space-xl`; gaps between dashboard cards are
`--space-xl`; page gutter is `--space-3xl`.

## Radius

`--radius-sm: 8px` (chips, inner tiles) · `--radius-md: 12px` (buttons, nav
pills, thumbs) · `--radius-lg: 16px` (cards) · `--radius-xl: 20px` (search bar
uses `--radius-pill`) · `--radius-pill: 999px` (pills, avatars).

## Elevation

Flat by default; borders do the separating.

| Token | Value | Use |
|---|---|---|
| `--shadow-card` | `0 1px 2px rgb(37 48 32 / 4%), 0 12px 32px -20px rgb(37 48 32 / 14%)` | Resting cards |
| `--shadow-pop` | `0 4px 6px rgb(37 48 32 / 6%), 0 16px 40px -16px rgb(37 48 32 / 22%)` | Hover/floating (dropdowns, popovers) |

## Motion

`--dur-fast: 120ms` for hovers/presses, `--dur-med: 220ms` for reveals.
Easing `--ease-out: cubic-bezier(0.2, 0.7, 0.3, 1)`. Animate `opacity`,
`transform`, and colors only. Respect `prefers-reduced-motion`.

## Iconography

Inline SVG, 24×24 viewBox, `stroke="currentColor"`, stroke width 1.7, round
caps and joins, no fills (except the logo leaf). Icons inherit text color, so
they theme automatically. All icons live as Jinja macros in
`src/nidaro/web/templates/components/icons.html` and are placed with
`{{ icon.name() }}`. Never paste raw `<svg>` into a page template; add a macro
instead.

Category-colored icons sit on a `.tile` (40×40, `--radius-md`, category `-bg`
background) and use the category `-fg` color; `.tile--sm` is the 32×32 stat
variant.

## Imagery

Photographic and illustration assets are generated, committed under
`src/nidaro/web/static/img/`, and referenced from CSS (sprite) or `<img>`
(standalone).

| Asset | File | Use |
|---|---|---|
| Meal photos (2×2 sprite) | `img/meal-sprite.jpg` | `.meal-thumb--0…3` quadrants: salmon / tacos / bowl / pasta |
| Family avatars (2×2 sprite) | `img/avatars-sprite.png` | `.avatar--0…3`: parent A / parent B / child A / child B |
| Plant illustration (alpha) | `img/plant.png` | Promo card |

Sprite recipe: `background-size: 200% 200%` and `background-position` of
`0 0`, `100% 0`, `0 100%`, `100% 100%` selects a quadrant. Quadrant indices are
fixed by DESIGN.md; do not reshuffle them in components.

## Layout & shell

- Shell grid: fixed 264px sidebar + fluid main column, full viewport height.
- Sidebar: logo, nav (icon + label, active = accent-soft pill), family card with
  avatar stack and invite button pinned to the bottom.
- Topbar: search (grows, `--radius-pill`, ⌘K hint), "Ask nidaro" ghost button,
  notification bell, account avatar.
- Content column: max-width 1460px, gutter `--space-3xl`, dashboard rows are CSS
  grids (`2.6fr 1fr`, `1.6fr 1fr 1fr 1.25fr`, `1fr 1fr 1.1fr`).
- Breakpoints: <1280px dashboard rows collapse to two columns; <1024px sidebar
  becomes an icon rail; <900px sidebar hides (mobile nav is a known gap until
  the responsive slice).

## Components

The vocabulary (implemented in `app.css`):

- `.card` + `.card__head`/`.card__title`/`.card__body` — the container for
  everything. Optional `.card--inset`, `.card--flush`.
- `.btn` with `--primary` (accent), `--ghost` (surface + border), `--dashed`
  (invite-style) variants; `.icon-btn` for square hit areas (bell).
- `.badge` (pill, accent-soft), `.chip` (surface-2, emoji + label),
  `.tag` (category pill).
- `.tile` + `.tile--<category>` for icon tiles.
- `.check` — round custom checkbox; rows pair it with `.check-row`.
- `.link-more` — the green "View … →" affordance, always `--text-sm`/600.
- `.avatar-stack`, `.avatar--<n>` sprites, `.kbd`, `.dot` (event dots, category
  colored), `.search`, `.divider`.

New components extend `app.css` using only tokens; a component that needs a new
token extends `tokens.css` first and documents it here.

## Interaction model

Server-rendered Jinja2 + HTMX (vendored at `static/js/htmx.min.js`).

- Pages are full documents; interactions (toggling a shopping item, refreshing
  a card) return **partials** — fragments under `templates/partials/` swapped by
  `hx-*` attributes.
- Assistant chat will stream via SSE: an async generator route emits
  `text/event-stream` from the assistant runtime, and the chat pane consumes it
  with `hx-ext="sse"`. Chat components (message bubbles, streaming cursor,
  composer) get designed here before that slice lands.
- No client framework, no build step. `app.js` stays under ~100 lines and only
  does theme state + progressive enhancement.

## Settings & per-user theming

Today: the Appearance section in `/settings` switches `data-theme` live and
persists to `localStorage["nidaro-theme"]` (`app.js` is the only writer).

Planned (user-account slice): store `theme` on the user record, emit
`<html data-theme="…">` server-side, keep the localStorage boot as fallback for
anonymous visitors. The settings endpoint will call the same application-service
boundary as everything else. No component CSS participates in that change —
that is the point of the token contract.

## File map

```
DESIGN.md                                   this document
src/nidaro/web/
  static/css/tokens.css                     primitives + semantic tokens + themes
  static/css/app.css                        reset, shell layout, components
  static/js/app.js                          theme state (SUPPORTED_THEMES)
  static/js/htmx.min.js                     vendored htmx 2.0.4
  static/img/                               generated imagery (see Imagery)
  templates/base.html                       shell: sidebar, topbar, theme boot
  templates/components/icons.html           icon macros
  templates/index.html                      dashboard
  templates/settings.html                   appearance + theme picker
  templates/placeholder.html                not-yet-integrated sections
  templates/partials/                       HTMX fragments (future)
  routes/ui.py                              page routes + nav registry
```

## Quick rules

1. No hex, font names, or raw px spacing outside `tokens.css` (px values inside
   `app.css` are limited to structural one-offs like borders: `1px`).
2. Text contrast stays at WCAG AA against its background in every theme.
3. One accent per screen region; category colors decorate, they don't compete.
4. Every interactive element has hover, focus-visible, and active states.
5. New page → new template extending `base.html`; nav additions happen in the
   `NAV` registry in `routes/ui.py` and nowhere else.

# Design System & App Shell — Requirements

## Overview

595BowersHub is a single React/Vite/TS PWA served at three widths (web · mobile web · installed PWA — there is no native app). It is currently a **half-migrated design system**: newer surfaces (finance pages, chat shell) are cleanly tokenized, but the chrome a user sees first and constantly (admin console, settings, overlays, the global toast) still uses hardcoded `gray-*`/`indigo-*`/`#hex` palettes — roughly 800 raw-palette occurrences (~802 by a fresh grep) across ~40 files. Worse, there is **no consistent app shell**: chat has a left sidebar, finance a horizontal sub-tab bar, dashboard its own tab row, glued by a thin 44px top bar — the app *changes shape per section*, which reads as instability more than any single screen's styling. The owner's feedback: it "looks and feels home built… doesn't feel hearty and stable."

This feature delivers two coupled things, gated by the owner as deliberate work after an earlier ad-hoc visual redesign was reverted:
1. **A primitives + design-token layer** — an owned `components/ui/` library (shadcn-pattern: Radix primitives + hand-rolled presentational components, with React Aria for the hard finance widgets), wired to the existing DB-driven theme tokens, plus the missing non-color design scales (spacing/radius/elevation/motion) that make a UI read as polished.
2. **A unified app shell** — one breakpoint-driven layout that renders every section inside a consistent frame (desktop: collapsible left nav rail + contextual top bar; mobile: bottom tab bar), consuming the existing single-source `navItems.ts`.

It must do this **without** introducing a second source of truth for the theme (NO-HARDCODING rule #1) and **without** visual regressions on already-good surfaces.

### Given inputs — already built, do NOT re-plan (build on these)
These shipped as "chrome quick-wins" (context-log 2026-06-26) and are fixed building blocks the spec consumes, not re-implements:
- `src/lib/navItems.ts` — single source of truth for primary nav (`NAV_ITEMS` + `TOOL_ITEMS`, Lucide icons, optional `feature` gating key). The shell's nav consumes this.
- `src/stores/confirm.ts` + `src/components/ConfirmDialog.tsx` — promise-based themed `confirm()`, mounted once in `main.tsx`. Already tokenized — the prior-art pattern for a Modal primitive.
- Lucide icon migration across TopNav/BottomTabBar/Sidebar; auth-surface token migration (Login/Register/Forgot/Reset); raw-IP and raw-JSON cleanups. Done — not in scope to redo.

---

## Feature 1: Design-token foundation

### R1.1 — One token source of truth (no competing theme system)
Every primitive, shell element, and migrated surface references the existing DB-driven theme tokens (the `--color-*` custom properties injected onto `document.documentElement` by `App.tsx` from `bh_themes.tokens_json`, surfaced as Tailwind utilities `bg-background`/`bg-surface`/`bg-primary`/`text-text`/`text-text-muted`/`border-border`/`bg-danger`/`bg-success`, etc.). The system MUST NOT introduce shadcn's stock `:root` token block, a parallel `--background`/HSL-named vocabulary, or any other competing color/theme authority. Where a vendored shadcn component expects a token name the project doesn't have (`primary-foreground`, `card`, `popover`, `ring`, `muted`, `destructive`), it is wired to an **alias** of an existing token, not a new source of authority.

### R1.2 — Enforce a token contract
The set of color tokens a primitives layer depends on is made an explicit, enforced contract rather than the current free-form `z.record(string,string)` `ThemeTokensSchema`. A theme that omits a required token key is detected (validation and/or a deterministic computed fallback), so a primitive can never resolve a token to `undefined`/transparent at runtime. **Pre-existing defect to fix:** `--color-warning` and `--color-error` exist only as `index.css` defaults — `App.tsx` never injects them and Tailwind exposes neither — so a theme switch leaves them frozen at the default (they fail the "no frozen-palette" acceptance criterion). They are **promoted to real per-theme tokens** (coordinated change across all 10 `bh_themes` rows + the `App.tsx` token map + `tailwind.config.ts`), not documented away, so the contract holds and theme switching restyles them.

### R1.3 — Semantic foreground aliases
Define the `-foreground`/`on-*` token aliases that the shadcn component pattern assumes (a readable text/icon color for every surface: on-primary, on-surface/card, on-muted, on-danger, etc.), mapped onto the existing tokens (`--color-on-primary` is already luminance-computed; the rest map to `text`/`text-muted`/`on-primary`). These aliases are derived from existing tokens, introducing no new theme authority (per R1.1). The current on-primary derivation uses a 0.5 luminance cutoff (`App.tsx`), which is **not** a WCAG contrast computation; the foreground aliases must satisfy the contrast threshold in R2.6, verified across all 10 presets.

### R1.4 — Opacity-composable tokens (committed token-format migration)
**Established fact (verified against compiled CSS):** Tailwind v3 opacity modifiers do **not** compose alpha against the current hex-valued `--color-*` tokens — `bg-primary/20` emits no rule and the existing live call-sites (`MessageList.tsx`, `SearchOverlay.tsx`) silently render at full opacity. The scope brief's "`/10` `/40` confirmed working" note was sampling hardcoded-palette colors, not tokens, and is **wrong**. Therefore this spec **commits** to converting the theme tokens to an alpha-composable format (storing channel triples and mapping `… / <alpha-value>` in `tailwind.config.ts`) so that interactive/layered states — hover/active tints, disabled dimming, overlay scrims, focus rings — render with correct alpha. This is a forward-only DB migration of the `bh_themes` seed values plus the matching `index.css` first-paint defaults and the `App.tsx` injection + luminance math (which currently parses hex), with **no change to the resolved on-screen colors at full opacity**. Verification is a *rendered* alpha check (not class compilation) and explicitly confirms the two currently-broken call-sites now render their intended tint.

### R1.5 — Non-color design scales (the "hearty and stable" tokens)
Introduce consistent, code-level design constants (legitimately in `tailwind.config.ts`/CSS as design constants, **not** user-facing config, **not** DB rows — distinct from the DB-driven *color* tokens) for the dimensions the app currently lacks: a spacing rhythm (4px base / 8px step, used via scale steps only — no ad-hoc arbitrary `px-[14px]`), a unified radius token family, a 3–4 step elevation/shadow scale, motion duration + easing tokens applied to interactive transitions, and a **named z-index / layering scale** (base content < shell chrome [rail/top bar/bottom tab] < dropdown/popover/tooltip portals < modals/dialogs < toasts) to replace the current stacking free-for-all (`z-[9999]`/`z-[10000]`/`z-[998]`/`z-30`/`z-50` scattered across Toaster, ConfirmDialog, db-browser, AppShell). Motion tokens collapse to no-op under `@media (prefers-reduced-motion: reduce)` (the app has zero reduced-motion handling today). Monetary and figure displays use tabular numerals (`font-variant-numeric: tabular-nums`) so digits align. These scales are applied consistently by the primitives so call-sites inherit them.

### R1.6 — Preserve the font-scaling accessibility contract
All primitives and shell elements size **type** with scaling `text-*` utilities (which resolve to `calc(var(--bh-text-base) * ratio)` per the `index.css` override) and size **spacing/layout** with the fixed-rem Tailwind padding/gap utilities, so the user's text-size setting (small/medium/large/extra-large via `--bh-text-base`) keeps working and layout does not outgrow the viewport. No primitive hardcodes a pixel font-size (inline `style={{fontSize}}` remains allowed only where already intentional, e.g. live previews). All four text sizes are exercised in verification.

---

## Feature 2: Primitives layer (`components/ui/`)

### R2.1 — An owned, vendored primitives layer
Create a `components/ui/` library that pages import instead of importing vendor libraries (`@radix-ui/*`, `react-aria-components`) directly. Components are **copied into the repo** (owned, editable by either agent, no version lock), consistent with the dual-agent (Kiro + Claude Code) workflow and the owned-components decision. The layer reuses, and does not duplicate, the existing shared building blocks (`navItems.ts`, `confirm.ts`/`ConfirmDialog`, the toast store with its `action` button).

### R2.2 — Radix-based chrome primitives
Adopt Radix UI primitives for the "hard-accessibility" interactive pieces — at minimum Dialog/AlertDialog, DropdownMenu, Popover, Tooltip, Select, Tabs, Switch, ScrollArea — styled with the project's token utilities. Each is keyboard-accessible and ARIA-correct (focus trap + focus return, ESC to close, scroll-lock, roving tabindex / type-ahead as applicable), replacing the hand-rolled keyboard/focus handling currently duplicated in `AppShell`/`SearchOverlay`/`ConfirmDialog` where consolidation is sensible. Portalled content inherits theme tokens (theme vars are on `documentElement`).

### R2.3 — Hand-rolled presentational primitives
Hand-roll the trivial presentational primitives Radix does not provide — Button, Card, Input, Badge (and the like) — with a small, centralized variant system (e.g. a `cva`-style map) that reads from the token utilities and the R1.5 scales, so variants are consistent and there is one place to change them.

### R2.4 — Themed global toast
Re-skin the global toast (`Toaster.tsx`, currently the only global primitive still using hardcoded `bg-red-600`/`bg-green-600`/`bg-neutral-800`) to the theme tokens, preserving its existing imperative API, queue/auto-dismiss behavior, and the `action` button used by the PWA "new version — Reload" flow. This closes the C6 "global toast" frontend tail.

### R2.5 — React Aria for the hard finance widgets
For the genuinely hard finance inputs — a date-range picker, a locale-aware currency/number field, a combobox/autocomplete, and an editable data grid — adopt React Aria Components, exposed **through the same `components/ui/` boundary** (call-sites import the project's `DatePicker`/`CurrencyInput`/`DataGrid`, never `react-aria-components` directly). React Aria is imported only on the lazy-loaded finance routes to contain bundle cost. Radix and React Aria coexist; neither is required to handle the other's domain. (This realizes the open question from the scope brief: React Aria for finance widgets, Radix for general chrome.)

### R2.6 — State primitives (loading / empty / error / validation)
Make the most-repeated cross-cutting UI patterns into owned primitives so migrated surfaces stop re-inventing them: Spinner, Skeleton, EmptyState, ErrorState (carrying the "couldn't load — Retry" affordance the 2026-06-22 hardening pass spread across stores), and inline form-field validation/error. The existing store `error` fields and Retry affordances are routed through these primitives rather than each surface hand-rolling them.

### R2.7 — Accessibility & test baseline (WCAG 2.1 AA)
Primitives meet **WCAG 2.1 AA**: text contrast ≥ 4.5:1 and UI/graphical contrast ≥ 3:1 (verified for the R1.3 foreground aliases across all 10 presets), full keyboard operability, visible focus indication, and correct ARIA roles/labels. Each new primitive ships with a component test that includes an automated a11y assertion (axe-core, or equivalent) — "passes checks" means a named checker, not a manual claim. Tests **drive** the responsive split (mocking `matchMedia` true *and* false) so both the mobile and desktop branches are exercised, not merely polyfilled (the jsdom default falls back to desktop, hiding the mobile path). The harness gains the `matchMedia` polyfill alongside the existing `ResizeObserver` one; `tsc --noEmit` stays clean.

---

## Feature 3: Unified app shell

### R3.1 — One breakpoint-driven shell layout (single canonical breakpoint)
Introduce a single shell layout that renders the active section via `<Outlet/>`, refactoring the current flat `<Routes>` list in `App.tsx` (where `TopNav`/`BottomTabBar` are loose siblings of `<Routes>`) into a layout route that wraps all authenticated sections. The shell chooses its chrome by **viewport breakpoint**, **not** per route — eliminating the section-by-section shape-shifting that is the diagnosed root cause of the "unstable" feel. **One canonical breakpoint** governs the desktop↔mobile chrome switch and is named explicitly. The codebase is currently inconsistent — primary nav switches at Tailwind `sm` (640px) but the chat sidebar (`AppShell`) switches at `md` (768px), leaving an undefined 640–767px band. The chat sidebar's breakpoint is **re-pointed to the canonical breakpoint** (a reviewed behavior change), so a 700px-wide window (tablet / split-screen) gets one coherent layout, not desktop chat chrome inside mobile shell chrome. The unauthenticated route tree is unaffected.

### R3.2 — Desktop chrome: collapsible left nav rail + contextual top bar
On `≥sm`, the shell presents a persistent **left nav rail** (icon + label, collapsible to icon-only) as primary navigation, plus a **contextual top bar** (page title, page-specific actions, account menu, and the global search entry). The rail's collapsed/expanded state is **persisted** (localStorage/settings, mirroring the existing theme-persistence pattern) and survives reload and PWA install. This replaces the current desktop top-only nav, whose horizontal space does not scale to the app's nav set.

### R3.3 — Mobile chrome: bottom tab bar + secondary nav
On `<sm`, the shell keeps the bottom tab bar (the best-implemented existing piece) for primary navigation and presents section/secondary navigation as a scrollable segmented control or bottom sheet, rather than each section inventing its own sub-nav row.

### R3.4 — Consolidate layout-offset logic
The duplicated, breakpoint-coupled offset code currently copy-pasted across sections — `sm:pt-11` (clear the 44px top bar) and `pb-14` (clear the bottom tab bar) in `FinanceLayout`/`DashboardPage`/`Sidebar`, plus the `.bh-app-shell` `top:44px`/`bottom:52px+safe-area` rules in `index.css` — is consolidated into the shell so individual sections no longer hand-manage chrome offsets. Each section's scroll container behaves correctly (chat's fixed `inset:0` layout, finance/dashboard scroll regions) after consolidation.

### R3.5 — Role-aware navigation from the single source
The shell's navigation is driven entirely by `navItems.ts` and honors the live multi-user authorization: per-item `feature` gating via `isFeatureVisible`/`useFeatures` against `/api/me/features`, the `hidden_nav` payload, and the cosmetic per-user self-hide (`PUT /api/me/settings/nav`). A user only ever sees nav entries they are permitted and have not hidden; nothing in the shell hardcodes a nav list.

### R3.6 — Safe-area & PWA coexistence
The shell respects installed-PWA insets: `viewport-fit=cover` on the viewport meta and `env(safe-area-inset-*)` padding applied to the rail, top bar, and bottom tab bar so chrome is not occluded by notches/home indicators. The shell coexists with the existing service-worker update handshake (the "New version available — Reload" toast) and does **not** take on offline/Workbox/caching work — that remains explicitly out of scope.

### R3.7 — Sections preserved inside the shell
Re-framing each section within the shell preserves its existing function: the chat sidebar/conversation switcher, finance sub-tabs (transactions/ask/insights/retirement/recurring/net-worth/budgets), dashboard tab pages, db-browser, settings, and admin all remain reachable and functional, on both desktop and mobile, with no loss of navigation paths (e.g. the mobile hamburger that reaches the workspace switcher).

### R3.8 — Route/layout refactor as its own revertable step, with chat as a named regression gate
The `App.tsx` route-tree refactor (R3.1) is inherently all-or-nothing (you cannot half-wrap the route tree) and carries the same wholesale blast radius as the previously-reverted visual redesign. It therefore lands as **its own independently revertable step**, separate from the surface migration (R4.4), with an explicit abort path. The **chat surface is the named regression gate**: chat's `position:fixed; inset:0` layout, the `body{overflow:hidden}` scroll lock, the safe-area offsets, and both desktop and mobile rendering must be verified intact before the refactor is considered done.

### R3.9 — Global command/search hotkeys re-homed and de-conflicted
The global hotkeys currently bound inside `AppShell` (Cmd/Ctrl+K → search overlay, today only active on chat routes) and in `App.tsx` (Cmd/Ctrl+Shift+K → QuickCapture) are **moved to the shell** so the promoted global-search entry (R3.2) works on every section. The two bindings remain mutually conflict-free, and both survive the Radix focus-trap consolidation (R2.2) — i.e. Escape and the chord keys behave correctly even when a Radix Dialog/Popover is open.

---

## Feature 4: Surface migration & visual-parity safety

### R4.1 — Migrate the un-tokenized surfaces
Migrate the surfaces still on hardcoded palettes to the token + primitives system: the `pages/admin/*` console tree, the settings/appearance panels (`SettingsPage`, `AppearancePanel`, `ThemeBuilder`, `WorkspaceSettingsPanel`, `VoicePanel`), chat-adjacent overlays (`QuickCaptureOverlay`, `PinnedContextManager`, `ScheduledPromptForm`/`ScheduledPromptsPage`, `SystemPromptEditor`), the `components/db-browser/*` subtree, and any remaining `MorningCard`/`IconUploader` stragglers. Hardcoded buttons/cards/inputs are replaced by the R2 primitives where applicable.

### R4.2 — Remove dead hardcoding
Remove the dead-weight hardcoding the migration exposes — notably the legacy `brand-{50..900}` scale in `tailwind.config.ts` and stray literal `#hex` values — so the token system is the only color authority left in the migrated surfaces.

### R4.3 — Visual-parity gate (no regressions)
Each migrated page is protected by a before/after visual check — baseline screenshots captured at mobile (390px) and desktop (≥1024px) and compared after migration (mirroring the `ai-finance-insights` Phase 4 screenshot-diff precedent) — so already-good surfaces do not visually regress and intended changes are reviewed, not accidental.

### R4.4 — Incremental and revertable
Migration proceeds page-by-page (or small group), each step independently shippable and revertable, rather than a single big-bang visual rewrite. (The prior ad-hoc visual redesign was reverted wholesale; incrementality is a deliberate de-risking requirement.)

---

## Acceptance Criteria

- [ ] A `components/ui/` layer exists; pages import its primitives, and there are **zero** direct `@radix-ui/*` or `react-aria-components` imports outside `components/ui/`.
- [ ] Grep shows no hardcoded color palettes (`#hex`, `gray-*`, `indigo-*`, `red-*`, `bg-neutral-*`, etc.) in the migrated surfaces or in any new primitive/shell code; the `brand-*` Tailwind scale is gone.
- [ ] Switching the active theme (any of the 10 `bh_themes` presets) restyles every primitive, the shell chrome, and all migrated surfaces — including the toast, `warning`, and `error` — with no element stuck on a frozen palette.
- [ ] Opacity-dependent states render with visibly correct alpha in a *rendered* check (not compilation); specifically, the two currently-broken call-sites (`MessageList`, `SearchOverlay`) now render their intended tint, and `bg-primary/<n>` emits an alpha rule in the compiled CSS.
- [ ] Changing the text-size setting across all four levels scales type everywhere without breaking layout or overflowing the viewport; no primitive uses a hardcoded px font-size.
- [ ] One canonical breakpoint governs the chrome switch: at 700px width the layout is coherent (not desktop chat chrome inside mobile shell chrome). On desktop every section renders inside the same shell (left rail + contextual top bar); on mobile every section renders inside the same shell (bottom tab bar + secondary nav). No section renders its own full-page frame.
- [ ] Chat survives the route refactor: `inset:0` fixed layout, scroll lock, and safe-area offsets verified intact on desktop and mobile; the route refactor is revertable as its own step.
- [ ] Cmd/Ctrl+K (search) and Cmd/Ctrl+Shift+K (QuickCapture) work on every section and remain conflict-free with an open Radix Dialog/Popover (Escape behaves correctly).
- [ ] Portalled content (Radix Popover/Tooltip/DropdownMenu) stacks above shell chrome (rail/top bar/bottom tab) and below modals/toasts, per the z-index scale.
- [ ] The nav rail collapse/expand state persists across reload and PWA relaunch.
- [ ] Nav entries reflect the signed-in user's features/role and `hidden_nav`; a viewer/member sees only permitted entries.
- [ ] Installed-PWA chrome clears notch/home-indicator safe areas; the SW "Reload" update toast still appears and works.
- [ ] Motion honors `prefers-reduced-motion: reduce` (transitions collapse); axe-core a11y assertions pass on primitives; foreground aliases meet 4.5:1 / 3:1 contrast across all 10 presets.
- [ ] Per-page visual-parity baselines exist at 390px and ≥1024px; no unintended visual regression on previously-tokenized pages.
- [ ] `npx tsc --noEmit` is clean; `npm test` (vitest) passes, including new primitive/shell tests that drive both responsive branches.

## Non-Functional Requirements

- **No hardcoding (Rule #1):** the DB-driven `bh_themes` token system remains the sole authority for theme color; no primitive, shell element, or migrated surface introduces a competing color/theme source or a hardcoded nav list. Non-color *design constants* (spacing/radius/elevation/motion scales) are code-level config, which is permitted — they are not user-facing configuration.
- **Data safety:** any token-format change (R1.4) or token-key addition (R1.2 warning/error) is a forward-only, auto-applied migration of the `bh_themes` rows, parameterized, with the resolved full-opacity colors unchanged; back up before the DB change.
- **Security / RBAC:** the shell honors the existing capability/feature authorization for nav visibility; no privileged route becomes reachable by virtue of the shell refactor. No secrets in code.
- **Performance / PWA:** React Aria is confined to the lazy-loaded finance chunk (verified by bundle analysis — it must not land in the main chunk); the primitives layer tree-shakes (per-primitive Radix imports); first-paint token defaults in `index.css` keep working so there is no theme flash. Budget: the main-chunk gzip size increase from Radix + CVA + tailwind-merge stays within a stated ceiling (e.g. ≤ ~15 KB gzip) confirmed by bundle analysis, not "materially."
- **Testability:** primitives and shell are unit/component-tested; the visual-parity gate is the migration regression guard.

## Constraints & Assumptions

- The app is **one** React/Vite/TS PWA at three widths (web · mobile web · installed PWA); there is no native app — the shell's responsive behavior *is* the cross-platform story.
- **Tailwind v3.4**, not v4 — design tokens use the `tailwind.config.ts` `theme.extend.colors` mechanism; copied shadcn snippets must not drag in v4-only `@theme`/`oklch` syntax. A Tailwind v4 upgrade is explicitly out of scope.
- Themes are 10 presets in `bh_themes`, each currently seeding 9 token keys; runtime injection is `App.tsx` → `document.documentElement.style`; first-paint defaults live in `index.css`. `--bh-text-base` drives font-scaling; layout spacing stays on fixed 16px rem.
- The "given inputs" in the Overview (navItems.ts, confirm dialog, icon/auth-token quick-wins) are assumed landed; the spec verifies branch state but does not re-implement them.
- Offline/Workbox/caching is out of scope; the existing network-only service worker + update toast stay as-is.
- A prior ad-hoc visual redesign was reverted; this is the deliberate replacement, which is why incremental migration + a visual-parity gate are required.
- **LTR / en-US only.** RTL and i18n/localization are out of scope (React Aria's locale-aware formatting is used for currency/dates but the app ships LTR English).
- **Mandated phase order** (each phase independently shippable, gated on the prior): **(P1)** alpha-composable token-format migration + token contract + non-color scales (R1.1–R1.6); **(P2)** the `components/ui/` primitives layer incl. themed toast and state primitives (R2); **(P3)** the shell + route-tree refactor, landed as its own revertable step with chat as the regression gate (R3); **(P4)** surface migration page-by-page behind the visual-parity gate (R4). The token and routing changes do **not** interleave with the per-surface migration.
- The raw-palette migration target is large — roughly **800** raw-palette occurrences across ~40 files (a fresh grep counts ~802; the "~695" figure from the scope brief understates it). This reinforces the page-by-page approach (R4.4).

## Dependencies

- **New npm packages:** Radix primitives (`@radix-ui/react-*`, per-primitive), `react-aria-components` (finance widgets), and optionally a variant helper (`class-variance-authority`) + `tailwind-merge`/`clsx`. All vendored/owned per R2.1.
- **Existing systems the shell must honor:** `lib/navItems.ts` + `lib/featureNav.ts`, `hooks/useFeatures`/`useHasRole`, `/api/me/features`, `PUT /api/me/settings/nav`, `stores/settings.ts` (theme + persistence pattern), `stores/confirm.ts`/`stores/toast.ts`, the service-worker update flow.
- **DB:** any forward-only migration touches `bh_themes` (R1.2 token keys and/or R1.4 token format); next unused migration number in `bowershub-ai/backend/migrations/`.
- **Tooling:** a screenshot-diff capability (e.g. Playwright) for R4.3, consistent with the `ai-finance-insights` Phase 4 precedent.

## Success Metrics

- **Visual consistency:** 0 hardcoded-palette occurrences in migrated surfaces and new code (from ~800 today); 100% of nav chrome driven by `navItems.ts`.
- **Structural consistency:** 1 shell layout wraps 100% of authenticated sections (from the current 4+ divergent per-section layouts); the per-section offset duplication is removed.
- **Theme integrity:** all 10 presets restyle 100% of UI, including the toast and finance widgets, with no frozen-palette elements.
- **Accessibility:** all 4 text sizes work app-wide with no layout overflow; primitives pass keyboard/focus/ARIA checks.
- **Safety:** 0 unintended visual regressions on previously-tokenized pages, per the 390px/≥1024px parity baselines; each migration step independently revertable.

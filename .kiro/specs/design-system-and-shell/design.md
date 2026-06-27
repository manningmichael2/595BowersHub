# Design System & App Shell — Design

> Satisfies requirements in `requirements.md`. Requirement IDs are referenced inline (e.g. "satisfies R1.2").
> Depth: **deep**. The three tournament lenses (minimal-change / ideal-architecture / risk-first) are not separate documents here because the requirements already pin the architecture; instead each major decision below names which lens won and why (see **Key Trade-off Decisions**).

## Architecture Overview

This is a **frontend-only** feature except for one small, forward-only DB migration to the `bh_themes` seed. Nothing in the FastAPI L1/L2/L3 path, skills, or finance/auth logic changes. The blast radius is `frontend/src/**` plus `migrations/0043_*.sql` and the `App.tsx` token-injection math.

```
                         BEFORE (today)                              AFTER (this feature)
  App.tsx ── injects 9 hex tokens ─► :root            App.tsx ── injects 11 channel-triple tokens ─► :root
  <TopNav/>            (loose siblings)                <ShellLayout>  (one layout route via <Outlet/>)
  <Routes> … 4+ per-section layouts                       ├─ desktop: <NavRail/> + <TopBar/>
  <BottomTabBar/>     (loose siblings)                    ├─ mobile:  <BottomTabBar/> + secondary nav
                                                          └─ <Outlet/> → every authenticated section
  hardcoded gray-*/#hex on ~40 surfaces               components/ui/* primitives (Radix + React-Aria + hand-rolled)
  ~802 raw-palette occurrences                        surfaces migrated page-by-page behind a parity gate
```

**Reused, not rebuilt** (per requirements "Given inputs"): `lib/navItems.ts` (nav source), `stores/confirm.ts` + `ConfirmDialog.tsx` (Modal prior-art), `stores/toast.ts` (re-skinned, API preserved), `hooks/useFeatures`/`useHasRole`, `/api/me/features`, `PUT /api/me/settings/nav`, the `--bh-text-base` font-scaling override, the SW update handshake, and the existing `App.tsx` luminance helper for `on-primary`.

**New:** the `components/ui/` library, a `<ShellLayout>` layout route, a `useBreakpoint` hook, a token-contract Zod schema, non-color design scales in `tailwind.config.ts`, and a `matchMedia` test polyfill.

---

## Key Trade-off Decisions (the tournament, synthesized)

1. **Token format: convert hex → channel-triple at injection time; the DB keeps hex.** *(minimal-change won over ideal-architecture.)*
   The ideal-arch lens says "store channel triples in `bh_themes.tokens_json`." But that breaks `ThemeBuilder`'s hex color pickers and the on-primary luminance math (which parses hex), and makes the DB rows unreadable. Instead: **`tokens_json` stays hex** (human-editable, ThemeBuilder untouched, luminance math untouched), and `App.tsx` converts each hex value to a space-separated `"R G B"` triple before `setProperty`. The CSS custom property holds the triple; `tailwind.config.ts` maps every color to `rgb(var(--color-x) / <alpha-value>)`. This satisfies R1.4's literal requirement (the *token* — the CSS var — is alpha-composable) at a fraction of the blast radius. **Consequence (the real cost):** every place that consumes `var(--color-x)` *directly as a color* (outside Tailwind's `rgb()` wrapper) must be wrapped in `rgb(...)`, because `var(--color-surface)` now resolves to `26 26 46`, not `#1a1a2e`. These consumers are finite and greppable (see R1.4 mechanics) and migrating them is a P1 sub-task with a grep gate.
   *Therefore no DB format migration is needed* — only the R1.2 key-addition migration (warning/error). This is recorded because the requirements' parenthetical ("storing channel triples … forward-only DB migration of the seed values") reads as if the DB stores triples; this design consciously diverges to inject-time conversion and the full-opacity colors are provably unchanged (`rgb(26 26 46 / 1)` === `#1a1a2e`).

2. **Shell as a React-Router *layout route*, not a wrapper component manually placed in each page.** *(ideal-architecture won.)*
   `App.tsx` currently renders `<TopNav/>`, `<Routes>`, `<BottomTabBar/>` as loose siblings (`App.tsx:176-224`). The shell becomes a parent `<Route element={<ShellLayout/>}>` whose children render through `<Outlet/>`. This is the only structurally honest way to make the chrome breakpoint-driven instead of per-section, and it is the diagnosed root-cause fix (R3.1).

3. **Route refactor lands as its own revertable commit; chat is the named regression gate.** *(risk-first won.)*
   The previous ad-hoc redesign was reverted wholesale. The route-tree rewrite is all-or-nothing and has the same blast radius, so it is isolated as one commit, ahead of and separate from surface migration, with chat (`position:fixed; inset:0` + scroll-lock + safe-area) as the explicit verify-before-done gate (R3.8).

4. **One canonical breakpoint constant, single source.** *(risk-first.)* Today primary nav switches at `sm` (640px) but `AppShell` chat sidebar switches at `md` (768px) (`AppShell.tsx:55`), leaving an undefined 640–767px band. A single exported constant (`BREAKPOINT_DESKTOP`) + a `useBreakpoint()` hook governs the whole switch; the chat sidebar is re-pointed to it (reviewed behavior change, R3.1).

---

## Components

### Token injection + contract (`App.tsx`, new `lib/themeTokens.ts`)
- **Responsibility:** Convert DB hex tokens to channel triples, inject all **11** keys (+ derived aliases), and validate the token contract.
- **Location:** `frontend/src/App.tsx` (injection effect, currently `:42-110`), new `frontend/src/lib/themeTokens.ts` (token key list, `hexToTriple`, contract schema, computed fallbacks).
- **Inputs/Outputs:** in: `effectiveTheme.tokens_json` (hex); out: `--color-*` triples on `document.documentElement`.
- **Reuses:** the existing sRGB luminance helper for `--color-on-primary` (`App.tsx:101-110`), unchanged math, now emitting a triple.
- **Details:**
  - `REQUIRED_TOKENS` = `background, surface, primary, accent, text, text_muted, border, danger, success, warning, error` (was 9; **+warning +error**, R1.2). Replaces `z.record(z.string(), z.string())` with `z.object({...})` (each `z.string().regex(hex)`), `.passthrough()` so custom themes can carry extras. A missing required key triggers a **deterministic computed fallback** (e.g. `warning`→`#eab308`, `error`→`danger`) so a primitive never resolves to `undefined`/transparent (R1.2).
  - `hexToTriple('#1a1a2e') → '26 26 46'`. Applied to every injected color incl. `surface-light`/`surface-dark` and the computed `on-primary` (`#111111`/`#ffffff` → triples).
  - **Foreground aliases (R1.3):** set `--color-on-surface: var(--color-text)`, `--color-on-muted: var(--color-text-muted)`, `--color-on-danger`, `--color-on-success`, `--color-on-warning`, `--color-on-error` (dark/light chosen by the same luminance helper, reused per token), `--color-on-primary` already exists. Aliases are *derived*, introducing no second authority (R1.1).

### `components/ui/` primitives library (new)
- **Responsibility:** the owned primitive layer every page imports instead of vendor libs.
- **Location:** `frontend/src/components/ui/`.
- **Reuses:** `confirm.ts`/`ConfirmDialog` pattern for Modal; `toast.ts` for Toaster; `cn()` util (new, `clsx`+`tailwind-merge`).
- **Inventory:**
  - **Hand-rolled (R2.3):** `Button`, `Card`, `Input`, `Textarea`, `Badge`, `Label`, `Separator` — `cva` variant maps reading token utilities + R1.5 scales. One `variants.ts` per component.
  - **Radix-based (R2.2):** `Dialog`/`AlertDialog`, `DropdownMenu`, `Popover`, `Tooltip`, `Select`, `Tabs`, `Switch`, `ScrollArea` — vendored shadcn-pattern wrappers, restyled to token utilities, `forwardRef`, portalled content gets the theme (vars live on `documentElement`, so portals inherit). `AlertDialog` becomes the engine under the existing `confirm()` store (consolidating the hand-rolled focus trap in `ConfirmDialog`/`SearchOverlay`/`AppShell`).
  - **State primitives (R2.6):** `Spinner`, `Skeleton`, `EmptyState`, `ErrorState` (the "couldn't load — Retry" affordance the 2026-06-22 pass scattered across stores), `FieldError`. Store `error` fields route through `ErrorState`.
  - **Toast (R2.4):** `Toaster.tsx` re-skinned off `bg-red-600`/`bg-green-600`/`bg-neutral-800` to `bg-danger`/`bg-success`/`bg-surface` + `on-*` foregrounds; **imperative API, queue, auto-dismiss, and `action` button (PWA reload) preserved**.
  - **React Aria (R2.5), finance-only, lazy:** `DatePicker`/`DateRangePicker`, `CurrencyInput` (locale-aware via React Aria `NumberField`), `Combobox`, `DataGrid` — exposed through `components/ui/` so finance call-sites import the project name, never `react-aria-components`. Imported only from lazy finance routes to keep React Aria out of the main chunk (verified by bundle analysis, NFR Performance).
- **Boundary rule (acceptance):** zero direct `@radix-ui/*` or `react-aria-components` imports outside `components/ui/` (greppable gate).

### `<ShellLayout>` + nav chrome (new)
- **Responsibility:** the one breakpoint-driven frame wrapping every authenticated section (R3.1).
- **Location:** `frontend/src/components/shell/{ShellLayout,NavRail,TopBar,SecondaryNav}.tsx`; `frontend/src/hooks/useBreakpoint.ts`; reuse existing `BottomTabBar.tsx`.
- **Inputs/Outputs:** consumes `navItems.ts` + `useFeatures`/`useHasRole` + `hidden_nav`; renders `<Outlet/>`.
- **Behavior:**
  - `useBreakpoint()` reads `matchMedia('(min-width: <BREAKPOINT_DESKTOP>px)')` (test-mockable, R2.7). `BREAKPOINT_DESKTOP` exported from one module; `AppShell` chat sidebar re-points to it (R3.1).
  - **Desktop (R3.2):** persistent `<NavRail/>` (icon+label, collapsible to icon-only; collapsed state persisted via the `settings` store pattern, survives reload/PWA) + `<TopBar/>` (page title, page actions slot, account menu, global-search entry).
  - **Mobile (R3.3):** `<BottomTabBar/>` (kept as-is) + `<SecondaryNav/>` (scrollable segmented control / sheet) replacing per-section sub-nav rows.
  - **Offset consolidation (R3.4):** the `sm:pt-11`/`pb-14` duplicated across `FinanceLayout`/`DashboardPage`/`Sidebar` and the `.bh-app-shell` `top:44px`/`bottom:52px` rules in `index.css` move into the shell; sections drop their offset code. Chat keeps `inset:0` (the shell yields full area to chat).
  - **Nav gating (R3.5):** entries filtered by `isFeatureVisible`/`useFeatures` + `hidden_nav`; nothing hardcoded.
  - **Hotkeys (R3.9):** Cmd/Ctrl+K (search) and Cmd/Ctrl+Shift+K (QuickCapture) move from `AppShell`/`App.tsx` (`App.tsx:149-162`, `AppShell.tsx:32`) into the shell so they work on every section; both survive the Radix focus-trap consolidation (ESC + chords correct with a Dialog open).

---

## Data Flow

**Theme switch (R1.2/R1.4):** user picks theme → `settings` store sets `effectiveTheme` → `App.tsx` effect validates contract (Zod) → for each of 11 keys, `hexToTriple` → `setProperty('--color-x', 'R G B')` → derive `on-*` aliases → Tailwind utilities resolve `rgb(var(--color-x) / <alpha>)` → **every** primitive/shell/surface restyles, including toast, warning, error, and `/20`-style tints (R1.4 acceptance).

**Render (R3.1):** request → `App.tsx` `<Routes>` → `<Route element={<ShellLayout/>}>` → `useBreakpoint()` picks chrome → `<Outlet/>` renders the section → section inherits offsets/scroll from shell.

---

## Data Model / Migrations

- **Changed table:** `public.bh_themes` — add `warning` + `error` keys to `tokens_json` for all 10 preset rows (R1.2). No schema/column change (it's a `jsonb` value update); parameterized; full-opacity resolved colors unchanged.
- **Migration file:** `bowershub-ai/backend/migrations/0043_theme_warning_error_tokens.sql` (next unused number; 0042 is the latest). Forward-only, auto-applied. Per-row `UPDATE … SET tokens_json = tokens_json || '{"warning":"…","error":"…"}'::jsonb` with per-preset values chosen to match each theme (not a blanket default). **Back up `bh_themes` before apply** (NFR Data safety).
- **DB-driven config rows:** none added (nav/skills/models unaffected). The non-color design scales (R1.5) are **code-level design constants in `tailwind.config.ts`/`index.css`, deliberately not DB rows** — they are not user-facing config, so this does not violate NO-HARDCODING (NFR + R1.5 explicitly carve this out).

## API / Interfaces

- **No backend endpoints added or changed.** The shell consumes existing `/api/me/features` and `PUT /api/me/settings/nav`. RBAC/capability behavior is unchanged — the shell only *reads* feature visibility; no privileged route becomes reachable via the refactor (NFR Security).

### `tailwind.config.ts` additions (R1.5, design constants)
- `colors`: add `warning`, `error`, and the `-foreground`/`on-*` aliases; convert all color entries to `rgb(var(--color-x) / <alpha-value>)`; **delete the `brand-{50..900}` scale** (R4.2).
- `borderRadius`: unified `sm/md/lg/xl` family off a base.
- `boxShadow`: `elevation-1..4`.
- `transitionDuration` + `transitionTimingFunction`: motion tokens; paired with a global `@media (prefers-reduced-motion: reduce)` collapse in `index.css` (R1.5).
- `zIndex`: **named scale** — `base < shell < dropdown < modal < toast` — replacing the `z-[9999]`/`z-[10000]`/`z-[998]`/`z-30`/`z-50` free-for-all (Toaster/ConfirmDialog/db-browser/AppShell). Portals land between shell and modal (acceptance: popover above chrome, below modals/toasts).
- spacing stays on the 4px base (already default); lint/grep discourages arbitrary `px-[14px]`.
- `fontVariantNumeric` tabular-nums utility for monetary/figure displays.

## Technology Choices

- **Radix UI (per-primitive `@radix-ui/react-*`)** for hard-a11y chrome — tree-shakeable, headless, themes via our tokens; no competing theme system (R1.1, R2.2).
- **React Aria Components** for finance widgets only — best-in-class date/number/grid/combobox a11y + locale formatting; **lazy-loaded in the finance chunk** to protect the main bundle (R2.5, NFR Performance).
- **`class-variance-authority` + `tailwind-merge` + `clsx`** for the variant system and class de-duplication (R2.3). New `package.json` deps: `@radix-ui/react-*` (per primitive), `react-aria-components`, `class-variance-authority`, `tailwind-merge`, `clsx`.
- **Tailwind v3.4** (`theme.extend.colors`, `rgb(var() / <alpha-value>)`) — **no v4 `@theme`/`oklch`**; vendored shadcn snippets are scrubbed of v4 syntax (Constraint).
- **`@axe-core/react` (or `jest-axe`/`vitest-axe`)** for the automated a11y assertion each primitive ships (R2.7).
- **Playwright** screenshot-diff for the visual-parity gate, mirroring the `ai-finance-insights` Phase 4 precedent (R4.3).

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Channel-triple switch breaks every direct `var(--color-x)` color consumer (index.css `.bh-*` rules, inline `style` in `App.tsx` Suspense fallbacks, etc.) | P1 grep `var(--color-` across `src/` + `index.css`; wrap each in `rgb(...)`; rendered alpha check (not class compilation) is the gate. Full-opacity color provably unchanged. |
| Route-tree rewrite repeats the reverted-redesign blast radius | Land R3.1 as its own revertable commit, separate from surface migration; chat is the named regression gate (R3.8); abort path = revert that one commit. |
| React Aria leaks into the main bundle, blowing the size budget | Import only from lazy finance routes; bundle-analysis check that React Aria is absent from the main chunk and total main-chunk gzip increase ≤ ~15 KB (NFR). |
| jsdom defaults `matchMedia` to desktop, hiding the mobile branch in tests | Add a `matchMedia` polyfill to the test harness (beside `ResizeObserver`); tests mock it **true and false** to drive both branches (R2.7). |
| 640–767px "tablet band" renders mixed chrome | Single `BREAKPOINT_DESKTOP`; re-point AppShell sidebar to it; explicit 700px acceptance assertion. |
| Theme migration corrupts `bh_themes` | Forward-only parameterized `jsonb` merge, per-preset values, back up first, full-opacity colors unchanged, boot self-check / contract validation catches a malformed row. |
| Surface migration regresses already-good pages | Page-by-page + per-page 390px/≥1024px parity baselines (R4.3/R4.4); each step revertable. |

## Open Questions / Critic Findings (adversarial pass)

1. **Global-search scope (needs owner input).** Today `SearchOverlay` searches the chat domain only — `GET /api/search?q=…&type=…` over conversations/knowledge/artifacts (`SearchOverlay.tsx:43,72`). R3.2/R3.9 promote the search *entry* + hotkey to every section. This design promotes **reachability** (the existing chat/knowledge search becomes openable from anywhere) without changing search *scope* — making search cross-section (e.g. "find a transaction") is a separate feature, not assumed here. **Confirm that "global search everywhere" = the existing search reachable everywhere, not a new cross-domain index.** (Leaning: yes, keep scope; expand later.)
2. **Custom (non-preset) themes rely on the R1.2 fallback, by design.** The `0043` migration backfills `warning`/`error` only into the 10 **preset** rows. Users can create custom themes via `ThemeBuilder` (currently 9 keys); those resolve `warning`/`error` through the deterministic contract fallback (R1.2) rather than stored values — acceptable and intended, noted so it is not a surprise. (Optionally, `ThemeBuilder` gains `warning`/`error` fields so new custom themes store them — small add, flagged for the tasks phase.)
3. **`ThemeBuilder` is a migration surface (R4.1), independent of the token-format switch.** Its live-preview pane applies *working* tokens via scoped inline hex styles (no global `setProperty`), so the channel-triple switch does not affect preview correctness. It still carries hardcoded palette (`text-gray-200`, `ThemeBuilder.tsx:377`) and is migrated in P4 like the other appearance panels.

## Test Strategy

- **Token contract (R1.2):** unit test the Zod schema (missing key → fallback, not undefined); test `hexToTriple`; test all 10 presets inject 11 keys.
- **Alpha (R1.4):** *rendered* alpha assertion (computed style), explicitly covering the two known-broken call-sites (`MessageList`, `SearchOverlay`) + `bg-primary/<n>` emits a rule.
- **Contrast (R1.3/R2.7):** automated WCAG check (4.5:1 text / 3:1 UI) for `on-*` aliases across all 10 presets.
- **Primitives (R2.7):** each ships a component test with an axe-core assertion + keyboard/focus/ARIA coverage; `tsc --noEmit` clean.
- **Responsive (R2.7):** `matchMedia` mocked true *and* false so both shell branches run.
- **Font scaling (R1.6):** exercise all four `--bh-text-base` levels; no overflow; no hardcoded px font-size in primitives.
- **Shell (R3):** chat regression gate (inset:0, scroll-lock, safe-area, desktop+mobile), 700px coherence, hotkeys-on-every-section + ESC-with-Dialog-open, nav gating by feature/role/hidden_nav, rail-collapse persistence across reload.
- **Visual parity (R4.3):** Playwright baselines at 390px/≥1024px per migrated page; diff is the regression guard.
- **No real DB needed** for any of the above (the one migration is verified by the existing from-empty boot apply + boot self-check).

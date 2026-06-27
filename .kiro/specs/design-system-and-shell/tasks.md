# Design System & App Shell — Tasks

> Each task traces to one or more requirements. Work them top-to-bottom; respect dependencies.
> Phases are the mandated order from `requirements.md` (P1 tokens → P2 primitives → P3 shell → P4 migration); **each phase is independently shippable and gated on the prior.** Do not interleave P4 surface migration with the P1/P3 structural changes.

---

## Phase 1 — Token foundation

## Task 1: Alpha-composable token format (inject-time hex→triple) + preserve font-scaling
- **Effort:** L
- **Dependencies:** none
- **Requirements:** R1.1, R1.4, R1.6
- [x] Add `hexToTriple()` + `setColorVar()` to a new `frontend/src/lib/themeTokens.ts`; keep `bh_themes.tokens_json` as **hex** (no DB format migration).
- [x] **Revised approach (Strategy B).** Implementation found **837 direct `var(--color-*)` usages across 59 files** — too large/risky to wrap in place. Instead of converting `--color-X` to a triple, keep `--color-X` as the full color (hex) and *additionally* inject a derived `--color-X-rgb` triple. So existing direct consumers need **zero edits** (they still read a full color), and Tailwind reads the `-rgb` triple. The triple is derived from the same `bh_themes` hex at injection (R1.1: a representation, not a second authority — like the existing `on-primary`/`surface-light` derivations).
- [x] In `App.tsx` injection effect, set both vars per token via `setColorVar(root, cssVar, value)` (incl. `surface-light`/`surface-dark` and the luminance-computed `on-primary`).
- [x] In `tailwind.config.ts`, map every `colors` entry to `rgb(var(--color-x-rgb) / <alpha-value>)`; add the `-rgb` triple first-paint defaults to `index.css` `:root` (Dark Navy), full-color hex defaults retained.
- [ ] Confirm primitives/shell size **type** with scaling `text-*` (resolving to `--bh-text-base`) and **layout** with fixed-rem utilities; no hardcoded px font-size (R1.6).
- [ ] **Tests:** unit `hexToTriple`; a **rendered** alpha assertion (computed style, not class compilation) proving `bg-primary/<n>` now renders its tint and the two known-broken call-sites (`MessageList`, `SearchOverlay`) render correctly; full-opacity color unchanged (`rgb(R G B / 1)` === old hex); exercise all four `--bh-text-base` levels for no overflow. `npx tsc --noEmit` clean.

## Task 2: Token contract + warning/error promotion + foreground aliases
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R1.2, R1.3
- [x] Replaced the free-form `z.record(string,string)` `ThemeTokensSchema` with a `z.object({...})` of the **11** keys (core required, `warning`/`error` optional), `.catchall(z.string())` (not `.passthrough()` — keeps the inferred type string-indexable instead of `unknown`). `normalizeThemeTokens()` (lib/themeTokens.ts) is the runtime fallback half: missing key → `TOKEN_FALLBACKS`, `error`→`danger`, so no token is ever `undefined`. (`parseLoose` already never throws, so a strict object is safe.)
- [x] Added `warning`/`error` to the `App.tsx` token map, `tailwind.config.ts`, and the store `FALLBACK_THEME`.
- [x] Derived `on-*` aliases injected in `App.tsx`: text-based (`on-background`/`on-surface`/`on-muted` → `text`) and **computed via `readableForeground()`** (max-WCAG-contrast black/white) for `on-primary`/`on-accent`/`on-danger`/`on-success`/`on-warning`/`on-error`. Added to tailwind + index.css first-paint defaults. **Note:** indigo-500 `#6366f1` could only reach 4.70:1 (black) — white-on-indigo (4.47) missed AA-normal. Resolved by migration `0044`: Dark Navy & OLED Black primary → indigo-600 `#4f46e5`, giving white-on-primary 6.29:1 (conventional look, AA-clean).
- [x] **Migration:** `0043_theme_warning_error_tokens.sql` — forward-only per-preset `jsonb` merge (`error`=theme's danger; `warning`=theme-native amber where available). Scoped to `is_preset` so custom themes are untouched (they rely on the contract fallback).
- [x] **Tests:** `themeContract.test.ts` (14 tests) — contract fallback incl. `error`→`danger`; all 10 presets resolve 11 keys; WCAG **≥4.5:1** for every computed `on-*` alias across all 10 presets (worst case 4.63). Migration verified applying 0001→0043 on a from-empty throwaway `pgvector/pgvector:pg16` (all 10 presets carry warning/error).

## Task 3: Non-color design scales (spacing/radius/elevation/motion/z-index/tabular)
- **Effort:** M
- **Dependencies:** Task 1
- **Requirements:** R1.5
- [x] Added to `tailwind.config.ts` (code-level constants): single-knob radius family (`sm/md/lg/xl` off `--radius`, shadcn-pattern; lg/md/xl match prior Tailwind defaults so only `rounded-sm` shifts 2→4px), `boxShadow` `elevation-1..4`, `transitionDuration` (`fast/base/slow`) + `transitionTimingFunction` (`standard/emphasized`), and the named `zIndex` scale (`base 0 < shell 30 < dropdown 40 < modal 50 < toast 60`). `tabular-nums` is a built-in Tailwind utility — no config; applied at call-sites.
- [x] Added the global `@media (prefers-reduced-motion: reduce)` collapse in `index.css` (app had none); near-0 durations so `transitionend`/`animationend` still fire. Added `--radius: 0.5rem` base var.
- [x] Spacing stays on the 4px base (Tailwind default); no scale override.
- [x] **Tests:** `designScales.test.ts` (7 tests) — imports `tailwind.config.ts` and asserts z-index strict ordering, elevation/radius/motion keys present; reads `index.css` and asserts the reduced-motion collapse + `--radius`. `tsc --noEmit` clean; 282 frontend tests; build compiles the radius family.
- [Note] Legacy `z-[9999]`/`z-[10000]`/etc. call-sites are migrated onto the named scale in P2/P3 (where the portals/modals/toasts are rebuilt); T3 only establishes the scale.

---

## Phase 2 — Primitives layer (`components/ui/`)

## Task 4: Library scaffold + hand-rolled presentational primitives
- **Effort:** M
- **Dependencies:** Task 3
- **Requirements:** R2.1, R2.3
- [x] Created `frontend/src/components/ui/` with `cn()` (`clsx`+`tailwind-merge`) + barrel `index.ts`; added deps `class-variance-authority@0.7.1`, `tailwind-merge@3.6.0`, `clsx@2.1.1`. Owned/vendored.
- [x] Hand-rolled `Button` (cva: primary/secondary/outline/ghost/danger × sm/md/lg/icon), `Card` (+Header/Title/Description/Content/Footer), `Input`, `Textarea`, `Badge` (cva), `Label`, `Separator` — all on token utilities (`bg-primary`/`text-on-*`/`bg-surface`/`border-border`) + R1.5 scales (`rounded-md/lg`, `shadow-elevation-1`, `duration-base`/`ease-standard`, tokenized focus ring).
- [x] **Tests:** `primitives.test.tsx` (11 tests) — render, variant/size classes, ref forwarding, disabled, `cn` dedupe, className-override-wins. `tsc --noEmit` clean; 293 frontend tests; build compiles the newly-used token utilities (elevation-1, on-success/danger/warning). Native DOM assertions (project doesn't wire jest-dom). **Note:** no call-sites migrated yet (that's P4), so the "zero direct vendor imports outside components/ui/" check is trivially true today and re-checked as surfaces migrate.

## Task 5: Radix chrome primitives
- **Effort:** L
- **Dependencies:** Task 4
- **Requirements:** R2.2
- [x] Vendored Radix wrappers styled to tokens + z-index/elevation scales: `Dialog`, `AlertDialog`, `DropdownMenu`, `Popover`, `Tooltip`, `Select`, `Tabs`, `Switch`, `ScrollArea` (per-primitive `@radix-ui/react-*` deps). Portalled content inherits theme (vars on `documentElement`); content uses `z-modal` (dialogs) / `z-dropdown` (menus/popover/tooltip/select). No animation plugin → no entrance animations (motion polish deferred; reduced-motion already satisfied).
- [x] Re-pointed `ConfirmDialog` onto Radix `AlertDialog` (confirm store API unchanged) — Radix now provides the focus trap/return, ESC, and scroll-lock that were hand-rolled. (Folding `SearchOverlay`/`AppShell` Cmd+K handling happens in P3 when those move to the shell.)
- [x] **Tests:** `radix.test.tsx` (6) — confirm() resolves true/false/ESC via AlertDialog, Dialog opens from trigger, Switch toggles, Tabs structure/active-panel. Added test-harness shims to `src/test/setup.ts`: `matchMedia` (+ `setMatchMedia` helper, R2.7), pointer-capture, `scrollIntoView`. tsc clean; 299 tests; build green. (Per-primitive axe assertions + portal-stacking land in T9.)

## Task 6: Themed global toast
- **Effort:** S
- **Dependencies:** Task 4
- **Requirements:** R2.4
- [x] Re-skinned `Toaster.tsx` off `bg-red-600`/`bg-green-600`/`bg-neutral-800` to `bg-danger`/`bg-success`/`bg-surface` + `on-*` foregrounds + Lucide status icons; action/close buttons tinted via alpha-composable `on-*` tokens. Imperative API, queue/auto-dismiss, and `action` button (PWA "Reload") preserved; layers at `z-toast`. Closes the C6 global-toast tail.
- [x] **Tests:** `Toaster.test.tsx` (3) — tokenized container (asserts no `bg-(red|green|neutral)-*`), action fires + dismisses, close removes. 302 tests; build compiles the `on-danger/20`-style alpha utilities.

## Task 7: State primitives (loading / empty / error / validation)
- **Effort:** M
- **Dependencies:** Task 4
- **Requirements:** R2.6
- [x] Added `Spinner` (role=status, reduced-motion aware), `Skeleton`, `EmptyState` (icon/title/description/action), `ErrorState` (the "couldn't load — Retry" affordance, reuses `Button`), `FieldError` (renders null when empty). All tokenized.
- [x] **Tests:** `statePrimitives.test.tsx` (6) — Spinner label, Skeleton pulse, EmptyState content, ErrorState retry fires / omitted when no handler, FieldError empty-vs-populated. (Routing the existing store `error` fields through `ErrorState` happens during P4 surface migration; axe assertions added in T9.)

## Task 8: React Aria finance widgets (lazy, finance-chunk only)
- **Effort:** L
- **Dependencies:** Task 4
- **Requirements:** R2.5
- [x] Added `react-aria-components` + `@internationalized/date`; built `CurrencyInput` (locale-aware NumberField), `Combobox`, `DatePicker`/`DateRangePicker`, `DataGrid` (config-driven over RA Table). Exposed through a **separate** `components/ui/finance/` barrel, **deliberately NOT re-exported from `components/ui`** so React Aria can't leak into the main bundle.
- [x] **Bundle isolation confirmed:** `react-aria-components`/`@internationalized` are absent from the entire build (nothing app-side imports the finance barrel yet; they land in the lazy finance chunk when P4 wires them). Main-chunk size unchanged (well within the ≤~15 KB ceiling — the actual ceiling check re-runs once a finance route imports them in P4).
- [x] **Tests:** `financeWidgets.test.tsx` (4) — CurrencyInput formats `$1,234.50`, Combobox renders labelled `role=combobox`, DatePicker renders group+trigger, DataGrid renders columns + row cells. tsc clean; 312 tests. (Inline-cell editing layered on at P4 integration; per-widget axe in T9.)

## Task 9: Accessibility & test baseline (matchMedia + axe)
- **Effort:** M
- **Dependencies:** Task 5, Task 6, Task 7, Task 8
- **Requirements:** R2.7
- [ ] Add a `matchMedia` polyfill to the test harness (beside `ResizeObserver`); every primitive ships an axe-core (or equivalent named checker) assertion + keyboard/focus/ARIA coverage; responsive tests mock `matchMedia` **true and false** to drive both branches.
- [ ] **Tests:** WCAG 2.1 AA (4.5:1 / 3:1) verified for foreground aliases across all 10 presets; `tsc --noEmit` clean; `npm test` green.

---

## Phase 3 — Unified app shell (lands as its own revertable step)

## Task 10: Shell layout route + canonical breakpoint + route-tree refactor
- **Effort:** L
- **Dependencies:** Task 9
- **Requirements:** R3.1, R3.8
- [ ] Add `frontend/src/hooks/useBreakpoint.ts` reading `matchMedia('(min-width: <BREAKPOINT_DESKTOP>px)')`; export `BREAKPOINT_DESKTOP` from one module and **re-point the chat `AppShell` sidebar breakpoint** (currently `md`, `AppShell.tsx:55`) to it.
- [ ] Refactor `App.tsx` (`:176-224`) from loose `<TopNav/>`/`<Routes>`/`<BottomTabBar/>` siblings into a parent `<Route element={<ShellLayout/>}>` wrapping all authenticated sections via `<Outlet/>`; unauthenticated route tree unaffected.
- [ ] Land this as **its own revertable commit**, separate from P4; abort path = revert this commit.
- [ ] **Tests (chat is the named regression gate):** chat `position:fixed; inset:0`, `body{overflow:hidden}` scroll-lock, and safe-area offsets verified intact on **both** desktop and mobile; a **700px-width** assertion proves coherent chrome (no desktop chat chrome inside mobile shell). Refactor is revertable.

## Task 11: Desktop chrome (nav rail + contextual top bar) + offset consolidation
- **Effort:** L
- **Dependencies:** Task 10
- **Requirements:** R3.2, R3.4
- [ ] Build `shell/NavRail.tsx` (icon+label, collapsible to icon-only; collapsed state persisted via the `settings` store pattern, survives reload/PWA) + `shell/TopBar.tsx` (page title, page-actions slot, account menu, global-search entry).
- [ ] Move the duplicated `sm:pt-11`/`pb-14` offsets (`FinanceLayout`/`DashboardPage`/`Sidebar`) and the `.bh-app-shell` `top:44px`/`bottom:52px` `index.css` rules into the shell; sections drop their offset code; each section's scroll container still behaves (chat full-area, finance/dashboard scroll regions).
- [ ] **Tests:** rail collapse/expand persists across reload; offsets correct per section; no double-offset regression.

## Task 12: Mobile chrome (bottom tab bar + secondary nav)
- **Effort:** M
- **Dependencies:** Task 10
- **Requirements:** R3.3
- [ ] On `<BREAKPOINT_DESKTOP`, keep `BottomTabBar` for primary nav and add `shell/SecondaryNav.tsx` (scrollable segmented control / bottom sheet) replacing per-section sub-nav rows.
- [ ] **Tests:** mobile branch (matchMedia false) renders bottom tabs + secondary nav; section sub-nav reachable.

## Task 13: Nav gating, safe-area/PWA, sections preserved, global hotkeys
- **Effort:** M
- **Dependencies:** Task 11, Task 12
- **Requirements:** R3.5, R3.6, R3.7, R3.9
- [ ] Drive shell nav entirely from `navItems.ts` honoring `useFeatures`/`isFeatureVisible` + `/api/me/features` + `hidden_nav` + the cosmetic self-hide (`PUT /api/me/settings/nav`); nothing hardcoded (R3.5).
- [ ] Apply `viewport-fit=cover` + `env(safe-area-inset-*)` to rail/top bar/bottom tab; coexist with the SW "New version — Reload" toast; no offline/Workbox work (R3.6).
- [ ] Verify every section (chat sidebar/switcher, finance sub-tabs, dashboard tabs, db-browser, settings, admin, mobile hamburger→workspace switcher) remains reachable/functional desktop+mobile (R3.7).
- [ ] Move Cmd/Ctrl+K (search) and Cmd/Ctrl+Shift+K (QuickCapture) from `AppShell`/`App.tsx` into the shell so they work on every section; keep them conflict-free and correct with an open Radix Dialog/Popover (ESC behaves). **Global search = existing chat/knowledge search made reachable everywhere (scope unchanged)** unless owner requests cross-domain search (R3.9).
- [ ] **Tests:** viewer/member sees only permitted + non-hidden nav; hotkeys work on a non-chat route and ESC-with-Dialog-open behaves; safe-area padding applied.

---

## Phase 4 — Surface migration & visual-parity safety (page-by-page)

## Task 14: Visual-parity harness (baselines at 390px & ≥1024px)
- **Effort:** M
- **Dependencies:** Task 13
- **Requirements:** R4.3
- [ ] Stand up a Playwright screenshot-diff capability (mirroring the `ai-finance-insights` Phase 4 precedent); capture per-page baselines at mobile 390px and desktop ≥1024px to gate each migration step.
- [ ] **Tests:** baseline capture + diff runs in CI/local; a deliberate change is caught by the diff.

## Task 15: Migrate un-tokenized surfaces + remove dead hardcoding (incremental)
- **Effort:** L
- **Dependencies:** Task 14
- **Requirements:** R4.1, R4.2, R4.4
- [ ] Migrate page-by-page (each step independently shippable + revertable, R4.4): `pages/admin/*`, settings/appearance (`SettingsPage`, `AppearancePanel`, `ThemeBuilder`, `WorkspaceSettingsPanel`, `VoicePanel`), chat overlays (`QuickCaptureOverlay`, `PinnedContextManager`, `ScheduledPromptForm`/`ScheduledPromptsPage`, `SystemPromptEditor`), `components/db-browser/*`, and `MorningCard`/`IconUploader` stragglers — replacing hardcoded buttons/cards/inputs with the R2 primitives.
- [ ] Remove dead hardcoding (R4.2): delete the legacy `brand-{50..900}` scale from `tailwind.config.ts` and stray literal `#hex`.
- [ ] **Tests:** per-page visual-parity diff (Task 14) shows no unintended regression; grep shows zero hardcoded palettes (`#hex`, `gray-*`, `indigo-*`, `red-*`, `bg-neutral-*`) in migrated surfaces; `brand-*` gone; `tsc --noEmit` clean; `npm test` green.

---

## Definition of Done

- [ ] All tasks complete; every requirement in `requirements.md` is satisfied (validator clean).
- [ ] A `components/ui/` layer exists; **zero** direct `@radix-ui/*` / `react-aria-components` imports outside it; zero hardcoded palettes in migrated surfaces/new code; `brand-*` removed.
- [ ] All 10 theme presets restyle every primitive, the shell chrome, the toast, `warning`, and `error` with no frozen-palette element; `bg-primary/<n>` renders correct alpha.
- [ ] One shell wraps 100% of authenticated sections (desktop rail+top bar / mobile bottom tabs); 700px coherent; chat regression gate intact; route refactor revertable as its own step.
- [ ] All four text sizes work app-wide without overflow; axe-core assertions pass; foreground aliases meet 4.5:1 / 3:1 across all 10 presets; reduced-motion honored.
- [ ] No hardcoded config introduced (theme color stays DB-driven; nav from `navItems.ts`; non-color scales are code constants, not DB rows). React Aria confined to the lazy finance chunk (bundle-verified, ≤ ~15 KB main-chunk increase).
- [ ] Migration `0043` applies forward-only on a from-empty DB with the boot self-check green; `bh_themes` backed up before apply.
- [ ] Tests pass (`PYTHONPATH=. .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit` + `npm test`), including new primitive/shell tests driving both responsive branches; per-page parity baselines exist.
- [ ] `context-log.md` updated with a dated entry.

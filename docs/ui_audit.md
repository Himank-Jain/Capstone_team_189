# Frontend UI audit and design-system migration

## Scope and audit outcome

The audit covers all 14 authenticated application routes, the standalone login
page, the live demo control panel, onboarding, incident/RCA views, shared
components, and the chart styling contract. The goal was to make the product
read as one security-operations workspace without changing its API contracts or
replacing the existing mock-mode workflows.

Before the migration, the application mixed navy/blue and green palettes,
different type treatments, spacing and card/button styles, and inconsistent
empty/loading/error presentation. Components also had direct color literals;
the incident detail page had inline layout styles. The new design uses one
dark, forest-and-lime theme, shared UI primitives, a common authenticated shell,
and semantic styles for severity, status, and confidence.

## Route inventory

| Route | Page | Current shared-system coverage |
|---|---|---|
| `/` | SOC overview | AppShell, PageHeader, StatCard, Card, Skeleton, EmptyState, SeverityBadge, Toast |
| `/select-org` | Organization selection | AppShell, PageHeader, Card, Button, Skeleton, EmptyState, Toast |
| `/alerts` | Live alert feed | AppShell, PageHeader, Card, Skeleton, EmptyState, SeverityBadge, Toast |
| `/analytics` | Analytics | AppShell, ModulePage, PageHeader, Card, EmptyState |
| `/entities/:entityId` | Entity profile | AppShell, ModulePage, PageHeader, Card, EmptyState |
| `/demo` | Live demo control | AppShell, Stepper, shared cards/buttons/forms, Toast, ConfirmDialog, StatCard |
| `/settings` | Settings | AppShell, ModulePage, PageHeader, Card, EmptyState |
| `/users` | Tenant users | AppShell, ModulePage, PageHeader, Card, EmptyState |
| `/system-health` | System health | AppShell, ModulePage, PageHeader, Card, EmptyState |
| `/model-health` | Model health | AppShell, ModulePage, PageHeader, Card, EmptyState |
| `/onboarding` | Onboarding wizard | AppShell, shared Stepper, FormField, Button, Card, PageHeader |
| `/connections` | Cloud connections | AppShell, PageHeader, Card, Skeleton, EmptyState, StatusBadge, Toast |
| `/incidents` | Incident list | AppShell, PageHeader, Card, Skeleton, EmptyState, confidence/severity badges, Toast |
| `/incidents/:incidentId` | Incident/RCA detail | AppShell, PageHeader, Cards, Skeleton, EmptyState, Tabs, badges, Toast |
| `/login` | Demo login | Standalone login layout using Card, PageHeader, FormField, Button, Toast |

The analytics, entity, settings, users, system-health, and model-health routes
are currently honest, linked empty states because those dashboard data sources
are not exposed to the UI. They do not make unnecessary loading requests.

## Inconsistency matrix

| Area | Before | Current design / status |
|---|---|---|
| Colors | Several unrelated page palettes and direct hex colors | One dark forest palette; surfaces, text, borders, brand, severity, status, confidence, and overlay colors live in `src/theme.css` |
| Typography | Page-specific heading, label, and body treatments | Shared sans/display font tokens, page headers, eyebrow and label styles |
| Spacing | Different page padding and component gaps | Shared page spacing, component gaps, and responsive layout rules in `src/app/phase3.css` |
| Buttons | Inconsistent filled, outlined, and text controls | Shared Button variants; common link-button treatments retained where routing is needed |
| Badges | Raw status and severity labels had differing treatments | Semantic SeverityBadge, StatusBadge, ConfidenceBadge, and shared Badge |
| Cards | Different backgrounds, borders, and corner radii | Shared Card/StatCard and common panel surface/border/radius tokens |
| Loading | Loading treatment varied by data page | Shared Skeleton used on asynchronous dashboard, alert, tenant, connection, and incident views |
| Empty | Page-specific or missing no-data states | Shared EmptyState; static, unwired modules now present linked explanations instead of fabricated metrics |
| Errors | Some fetch failures were not presented consistently | Shared Toast for async and form errors; API errors remain visible rather than being converted to successful empty data |
| Forms | Different field spacing and labels | Shared FormField and common input/control styling; onboarding and login use the common treatment |
| Charts | Chart colors were not represented by a shared contract | `components/ui/chartTheme.ts` exposes token-backed grid, axis, tooltip, and series colors; no new chart dependency was introduced |
| App navigation | Pages had different navigation context and hierarchy | Authenticated pages use one sidebar/topbar AppShell; login remains intentionally standalone |
| Responsive layout | Page-specific widths and wrapping | Shared shell and layout breakpoints cover laptop and narrow-screen navigation/content |

## Component inventory

### Shared primitives (`src/components/ui/`)

| Component / module | Use |
|---|---|---|
| `Button` | Primary, secondary, danger, and ghost actions |
| `Card` | Common bordered surface |
| `PageHeader` | Shared page title, description, eyebrow, and action layout |
| `StatCard` | KPI presentation with semantic tone |
| `DataTable` | Typed table with a common empty state |
| `Badge` | Base badge treatment |
| `SeverityBadge` | LOW/MEDIUM/HIGH/CRITICAL indication |
| `StatusBadge` | OPEN/ACKNOWLEDGED/RESOLVED/REGRESSION indication |
| `ConfidenceBadge` | HIGH/MEDIUM/LOW confidence indication |
| `EmptyState` | Accessible no-data and not-yet-connected state |
| `Skeleton` | Shared loading placeholder |
| `Stepper` | Shared onboarding and demo progress indicator |
| `FormField` | Label, hint, and control wrapper |
| `ConfirmDialog` | Destructive/reset confirmation |
| `Toast` | Inline accessible success/error notification |
| `Tabs` | Shared tab selection treatment |
| `ModulePage` | Standard shell for intentionally unwired module pages |
| `chartTheme.ts` | Token-backed Recharts visual settings, exported separately from component code |

### Other shared/application components

| Component | Use |
|---|---|
| `AlertResponseCard` | Shared alert/RCA response display |
| `DemoStatusCard` | Existing demo status wrapper around shared stat styling |
| `widget-registry.ts` | Existing dashboard widget registry |
| `AppLayout` in `app/routes.tsx` | Sidebar, tenant context, breadcrumb, and navigation shell |

## Literal-style audit

The `lint` script runs `scripts/check-ui-tokens.mjs`, which scans frontend
TS/TSX/CSS source and fails on hardcoded hex/RGB/HSL colors or arbitrary
Tailwind values outside the token file.

Current scan results:

- Hardcoded colors outside `src/theme.css`: **0**
- Arbitrary Tailwind values in `className`: **0**
- Inline React style props in TSX: **0**
- Focus indicator: shared `:focus-visible` outline uses the accent token.

The two inline style objects found on the incident/RCA detail view were
replaced by named CSS classes. `theme.css` is the sole intentional color-literal
source. The detector is a targeted guard for color and arbitrary utility
literals; it is not a general CSS-value or contrast analyzer.

## Mock-mode and route smoke coverage

`VITE_MOCK_MODE=true` provides local fixtures for tenants, recent alerts, login,
demo operations, and Phase 3 incident/RCA views. Static modules remain
informative empty states until corresponding APIs exist. The Playwright smoke
suite visits every route in the inventory (including a high-confidence
incident/RCA detail fixture), asserts the route heading, checks for browser
page errors, and writes full-page screenshots to `frontend/artifacts/ui-smoke/`
by default.

The standalone Vitest suite continues to cover the Incident/RCA structured
explanation, fallback, and escaped-text rendering contracts. Browser coverage
complements those rendering tests; it does not replace them.

## Validation and screenshot gate

Final validation:

| Command | Result |
|---|---|
| `npm run lint` | Passed; ESLint and UI-token guard |
| `npm run typecheck` | Passed |
| `npm test` | Passed; 2 files, 5 tests |
| `npm run build` | Passed; TypeScript build and Vite production bundle |
| `npm run test:e2e` | Passed; 15 routes, no browser page errors, 15 screenshots |

TypeScript validation initially identified ES2020-incompatible array/string
methods and a duplicate alert contract; these were corrected by using
compatible operations and the canonical alert type. The lint pass also
identified a React effect state-update pattern in incident loading; loading is
now derived from the incident ID that completed. Vitest is scoped to source
tests so the Playwright suite runs only through its dedicated command.

Post-migration screenshots:

| Page | Committed-base reference | After migration |
|---|---|
| Onboarding | [onboarding-before-committed-base.png](../frontend/artifacts/ui-before-committed-base/onboarding-before-committed-base.png) | [onboarding.png](../frontend/artifacts/ui-smoke/onboarding.png) |
| Demo control panel | [demo-before-committed-base.png](../frontend/artifacts/ui-before-committed-base/demo-before-committed-base.png) | [demo.png](../frontend/artifacts/ui-smoke/demo.png) |
| Incident/RCA detail | [incident-detail-before-committed-base.png](../frontend/artifacts/ui-before-committed-base/incident-detail-before-committed-base.png) | [incident-detail.png](../frontend/artifacts/ui-smoke/incident-detail.png) |

The before column is an approximate reference captured from the last committed
revision (`2f79304`), isolated in a detached worktree and labeled accordingly.
The working tree already contained uncommitted Phase 3 and UI-related changes,
so this is not an exact image of the immediate pre-WP-E working state. The
after column is from the current implementation, captured by the 15-route
Playwright run in mock mode. No current or stale browser render is represented
as a before-image.

The dependency installation reported 10 npm audit advisories (5 moderate,
3 high, 2 critical). No automatic audit fix was applied; dependency upgrades
are outside this UI-only scope and could change application behavior.

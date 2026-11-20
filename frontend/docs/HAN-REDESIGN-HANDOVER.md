# HAN frontend redesign handover

## Summary

This change redesigns the existing HAN frontend as a dark, premium, futuristic workspace using a midnight-purple foundation, restrained violet illumination and champagne-gold accents. It is an adaptation of the supplied `han-main` application, not a replacement application.

## Scope completed

- Reworked the authenticated application shell into a persistent desktop navigation rail, compact top bar, mobile navigation, user identity area and product footer.
- Added a subtle digital-grid atmosphere and low-contrast ambient lighting.
- Replaced the light palette with dark surfaces, violet active states and gold highlights.
- Restyled the shared buttons, inputs, labels, cards, tabs, tables, status surfaces and focus states.
- Added responsive behavior for smaller screens and a reduced-motion accommodation.
- Applied the same visual system to translator, administration, operations, audit and sign-in pages through shared layout and global styles.
- Updated the HAN metadata description and shared page-title hook.

## Files changed

- `components/AppShell.tsx`
- `app/globals.css`
- `tailwind.config.ts`
- `components/ui.tsx`
- `app/layout.tsx`

## Existing functionality deliberately preserved

- `lib/api.ts` and all existing API methods and request/response contracts
- `lib/auth.tsx` and role-based navigation visibility
- All project, chat, quick-translation and CAT/workspace components
- Translation editing, immutable version history, review, approval and rejection flows
- Translation Memory, terminology and QA behavior
- Administration, operations and audit data loading/actions
- Backend routes, database models, provider adapters, model routing and security controls

No backend files have been changed. No new runtime dependencies have been added.

## Confidentiality and access boundaries

The redesign does not add any engine/provider fields to translator-facing components and does not change the public API serializers. Operational model registry and routing screens remain under the existing technical-administrator navigation/access controls. The backend remains the authority for authorization; hiding a link in the frontend is not treated as security.

Continue to keep provider/model identifiers, routing rationale, provider traces, credentials and internal costs out of translator-facing payloads and views. Preserve the existing engine-confidentiality UI tests and backend leakage/access-control tests.

## Validation

Dependencies were not installed in this environment, so a production build, TypeScript check and automated tests have not been executed here.

Run from `han-main/`:

```bash
npm ci
npm run typecheck
npm test
npm run build
```

The package currently defines `lint` as `next lint`; if the installed Next.js version no longer supports that command, use the repository's supported ESLint command without changing application behavior.

## Manual QA checklist

1. Sign in as a translator and verify only permitted navigation links appear.
2. Open a project and test HAN Chat, Quick Translate, Translation Workspace, editing, saving, version history and review.
3. Verify a translator cannot see Operations, model registry or routing diagnostics.
4. Sign in as a technical administrator and verify Administration, Operations and Audit access still works.
5. Check project/user/terminology/readiness administration forms and operational tables.
6. Check sign-in, desktop, tablet and mobile widths.
7. Verify keyboard focus visibility and reduced-motion behavior.
8. Re-run frontend engine-confidentiality tests and backend leakage/access-control tests.
9. Confirm the browser network payloads still match the existing API contract; do not add client-side provider/model diagnostics.

## Notes for the next implementation pass

This pass establishes the shared visual foundation and shell while preserving the existing screen logic. It does not introduce new product workflows, animation libraries, dashboard metrics or API capabilities. The next pass should be visual QA against real authenticated data, followed by targeted refinements to dense CAT workspace layouts and any specific admin tables that need column-level responsive treatment.

---

## Implementation notes (HAN engineering)

The package above was applied as the visual specification. The request that accompanied it also asked for a **toggleable navigation
menu**, **menu items that open separate pages**, and for the **fixed multi-column layouts to be replaced by page-style layouts**.
The package itself keeps the single-page tabs and column layouts (see "Notes for the next implementation pass"), so those parts are an
extension built on the package's design tokens, not a departure from them.

### Applied exactly as supplied
`tailwind.config.ts`, `app/layout.tsx`, `components/ui.tsx` and `app/globals.css` (design tokens, atmosphere, sidebar, top bar, buttons,
cards, inputs, tables, alerts, focus and reduced-motion rules). The `AppShell` structure (atmosphere, brand mark, product tag, "Human-led
by design" note, profile block, top bar labels, footer) is kept.

### Extended
- **Toggleable menu** (`components/AppShell.tsx`, `lib/nav.ts`): the menu button collapses the sidebar to an icon rail on desktop (remembered in
  `localStorage`) and opens/closes an off-canvas drawer on phones (Escape, backdrop and navigation close it; `aria-expanded`/`aria-controls`
  set; the closed drawer is `inert`). The supplied always-visible rail is the default state. The supplied phone-only horizontal link strip and
  top-bar sign-out button were replaced by the drawer (sign-out lives in the profile block).
- **Menu items are pages**: `/projects`, `/projects/<id>` (overview), `/chat`, `/quick`, `/workspace`, `/admin/users`, `/admin/projects`,
  `/admin/terminology`, `/admin/readiness`, `/admin/ops`, `/admin/audit` (`/admin` redirects to users). A project section appears in the menu
  while inside a project. Role-based visibility is unchanged and remains a convenience: the backend enforces access.
- **Page layouts**: the former project tabs and side column became the overview + three pages; the Translation Workspace is a single column
  (new-job form, job cards, full-width segments that expand in place) instead of three columns; chat scrolls with the page and keeps its
  composer pinned. Component logic (API calls, versions, approval, QA, TM) is unchanged.
- **Colours the supplied overrides did not cover**: status chips, tier badges, version labels (now dark-native in `lib/labels.ts`) and the
  info/success alert text and borders (`globals.css`, "Extension" section).
- **Tests**: `tests/nav.test.tsx` (role gating, project section, active-link rules, collapse/drawer behaviour). `scripts/ui_check.mjs` (in the
  `hanapi` repo) drives the whole journey in a real browser, including the toggle, drawer and in-place segment expansion.

### Build output folder
`HAN_DIST_DIR` selects the Next.js output folder, so a release can be built and tested without touching the one being served.

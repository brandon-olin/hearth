# CLAUDE.md — web/

Next.js frontend for Life Dashboard. See the root `CLAUDE.md` for product vision and cross-cutting principles.

---

## Stack

- **Next.js 15** — App Router, React Server Components where practical, client components where state/hooks are needed
- **TypeScript** — strict mode; no `any` except where unavoidable (e.g. JSONB passthrough)
- **Tailwind CSS v4** — utility-first; CSS variables for theming
- **shadcn/ui** — component primitives in `src/components/ui/`
- **TanStack Query v5** — server state, via `openapi-react-query` wrapper
- **openapi-fetch** — typed API client generated from the FastAPI OpenAPI schema
- **BlockNote** — rich text editor for the Documents feature
- **JSZip** — zip parsing for the Notion/markdown import feature

---

## Project layout

```
src/
  app/
    (auth)/login/         Login page (unauthenticated route group)
    (protected)/          All authenticated routes; wrapped by Shell
      documents/          Page tree + BlockNote editor
      todos/              Task list
      habits/             Habit tracker
      goals/              Goal tracking
      recipes/            Recipe library
      grocery-lists/      Shopping lists
      workouts/           Workout log
      contacts/           Address book
      calendar/           Calendar view
      settings/           App settings (theme, sidebar, account)
    api/
      [...path]/          Catch-all proxy to FastAPI backend
      documents/bulk-import/  Dedicated route for multipart-safe import
  components/
    shell/                App shell: sidebar nav, mobile header, command palette
    documents/            Page tree (collapse state persisted in module-level Set), document editor, Notion import dialog
    ui/                   shadcn/ui primitives (auto-generated, don't edit manually)
    [domain]/             Domain-specific UI components
  lib/
    api/
      client.ts           openapi-fetch instance; auth middleware; error-throwing middleware
      query.ts            openapi-react-query wrapper ($api)
      schema.ts           Auto-generated TypeScript types from FastAPI OpenAPI JSON
    auth/
      context.tsx         AuthContext — current user, login/logout, token refresh
      token.ts            In-memory access token store; getAccessToken()
    theme/
      context.tsx         ThemeCustomizerContext — active palette config
      presets.ts          All palette definitions; isThemeDark() helper
    hooks/
      use-resizable-panel.ts  Drag-to-resize panels with localStorage persistence
    sidebar/
      context.tsx         SidebarConfigContext — visible items, order, hidden items
```

---

## API client

All data fetching goes through `$api` from `src/lib/api/query.ts`:

```typescript
import { $api } from "@/lib/api/query";

// Queries
const { data, isLoading } = $api.useQuery("get", "/documents", {
  params: { query: { include_archived: false } },
});

// Mutations
const { mutateAsync } = $api.useMutation("patch", "/documents/{doc_id}");
await mutateAsync({ params: { path: { doc_id: id } }, body: { title } });
```

The client middleware in `client.ts` automatically:
- Attaches the `Authorization: Bearer <token>` header from the in-memory token store
- Throws on non-2xx responses (so React Query surfaces errors instead of returning `undefined` data)
- Exempts `/api/auth/` routes from the error-throw middleware (auth 401s are control flow, not errors)

For operations that need full control over headers or method (e.g. file import, delete-all), use plain `fetch("/api/...")` with `getAccessToken()` directly.

---

## Next.js API proxy

`src/app/api/[...path]/route.ts` proxies all requests to the FastAPI backend. The `API_URL` environment variable in `.env.local` controls where the backend lives:

```
API_URL=http://192.168.68.58:8000   # NAS (production)
API_URL=http://localhost:8000        # local dev
```

Switching `API_URL` to `localhost:8000` and running FastAPI locally is the fastest dev loop — no NAS rebuild needed.

Dedicated route handlers exist for paths that need special handling (e.g. `api/documents/bulk-import/route.ts`).

---

## Theming

The app uses a palette-based theme system. Palettes are defined in `lib/theme/presets.ts` — each has a `category` of `"light"` or `"dark"` and sets all CSS custom properties. Selecting a palette calls `applyThemeConfig()` which toggles the `.dark` class on `<html>` and writes all `--variable` values.

**Do not** use `useTheme()` from `next-themes` to determine dark/light — it follows system preference, not the selected palette. Use `useThemeCustomizer()` + `isThemeDark(config)` instead.

BlockNote is themed by targeting `.bn-root` directly in `globals.css` and passing `theme={bnTheme}` to `<BlockNoteView>`.

---

## Conventions

**Client vs server components:** default to server components. Add `"use client"` only when you need hooks, browser APIs, or event handlers. Layouts that use `useResizablePanel` or other hooks must be client components.

**Forms and mutations:** use `$api.useMutation` with `mutateAsync` for typed mutations. Invalidate relevant query keys after mutations: `qc.invalidateQueries({ queryKey: ["get", "/documents"] })`.

**Error handling:** the API client throws on non-2xx, so wrap mutations in try/catch. Don't silently swallow errors — surface them in UI state.

**Scrollbars:** themed via CSS variables in `globals.css` — thin, using `--border` / `--muted-foreground`. Don't override per-component.

**Resizable panels:** use the `useResizablePanel` hook with a unique `storageKey`. Drag handles are `<div>` elements with `onMouseDown={startResize}` and `cursor-col-resize` styling.

**Schema updates:** when the FastAPI schema changes, regenerate `src/lib/api/schema.ts`:
```bash
cd web
npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api/schema.ts
```

---

## Documents

**Page tree collapse state** is stored in a module-level `Set<string>` in `page-tree.tsx` (outside the React component). This survives layout unmounts when navigating between routes (e.g. /todos → /documents). The collapse-all action clears the set before forcing a remount.

**Document icons** — each document has an optional `icon` field (single emoji). The page tree renders it in place of the `FileText` icon when present. Icons are extracted from Notion HTML exports (`class="page-icon"` element) or from a leading emoji-only line in MD files during import.

**Notion import** (`notion-import-dialog.tsx`) — prefers HTML over markdown when both exist for the same page stem in the zip. HTML pages are parsed via a singleton `BlockNoteEditor.create()` instance calling `tryParseHTMLToBlocks()`, which correctly maps Notion's `<details>/<summary>` toggles to `toggleListItem` blocks. The result is stored as `editor_json`. MD pages keep the existing behavior (`source_markdown` + inter-page link rewriting). Use **"Export as HTML"** from Notion (not "Markdown & CSV") to get correct toggle lists and icons.

Known issue: checkbox items nested inside toggle blocks trigger a BlockNote `blockContainer` parse error — fix pending.

---

## Running locally

```bash
cd web
npm install
npm run dev   # starts on http://localhost:3000
```

Set `API_URL` in `.env.local` to point at your backend. The dev server proxies all `/api/*` requests.

---

## Building for production (Docker)

The web app is built as a standalone Next.js output inside a Docker image. To rebuild after web changes:

```bash
cd /volume1/docker/life-dashboard/infra
sudo docker compose build web && sudo docker compose up -d
```

# CLAUDE.md — web/

Next.js frontend for Hearth. See the root `CLAUDE.md` for product vision and cross-cutting principles.

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
      todos/              Task list with recurrence support
      habits/             Habit tracker with streaks and completion rates
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
    documents/            Page tree, document editor, Notion import dialog
    habits/               habit-sheet.tsx, habit-row.tsx
    todos/                todo-sheet.tsx, todo-row.tsx, quick-add.tsx
    ui/                   shadcn/ui primitives (do not edit manually)
    [domain]/             Domain-specific UI components
  lib/
    api/
      client.ts           openapi-fetch instance; auth middleware; error-throwing middleware
      query.ts            openapi-react-query wrapper ($api)
      schema.d.ts         TypeScript types from FastAPI OpenAPI — see "Schema updates" below
    auth/
      context.tsx         AuthContext — current user, login/logout, token refresh, impersonation, locale auto-detect
      token.ts            In-memory access token store; getAccessToken()
    theme/
      context.tsx         ThemeCustomizerContext — active palette config
      presets.ts          All palette definitions; isThemeDark() helper
```

---

## Before implementing anything UI

Check these in order before writing new UI code:

1. Is there an existing component in `components/ui/`?
2. Is there a utility class in `globals.css`?
3. Grep for a similar pattern elsewhere in the codebase and copy it — don't invent.

---

## UI primitives — use these, do not reinvent

| Need | How | Source |
|---|---|---|
| Checkbox | `className="checkbox-themed"` on `<input type="checkbox">` | `globals.css` |
| Tooltip | `<TooltipProvider>` / `<Tooltip>` / `<TooltipTrigger>` / `<TooltipContent>` | `components/ui/tooltip.tsx`; usage example: `shell.tsx:223` |
| Badge | `className="badge badge-{colour}"` — see badge table below | `globals.css` |
| Sheet/drawer | `<Sheet>` / `<SheetContent>` / `<SheetHeader>` etc. | `components/ui/sheet.tsx` |
| Select | `<Select>` | `components/ui/select.tsx` |
| Button | `<Button variant="..." size="...">` | `components/ui/button.tsx` |
| Input | `<Input>` | `components/ui/input.tsx` |
| Label | `<Label>` | `components/ui/label.tsx` |
| Textarea | `<Textarea>` | `components/ui/textarea.tsx` |

### Badge colour variants

Always combine `.badge` with exactly one colour variant. Add `.badge-faded` for archived/disabled states. Variants use CSS variables — they automatically follow the user's selected theme and light/dark mode.

| Class | Semantic meaning | Use for |
|---|---|---|
| `badge-primary` | theme primary color | active, selected, current |
| `badge-neutral` | muted/gray | backlog, paused, default/unknown |
| `badge-warning` | amber tones | on deck, caution |
| `badge-progress` | violet tones | in progress |
| `badge-success` | green tones | complete, success |
| `badge-error` | red tones | blocked, error, urgent |
| `badge-faded` | opacity modifier | archived, disabled — add alongside a colour variant |

```tsx
// Status badge from a Record map (canonical pattern — see projects/page.tsx)
const STATUS_BADGE: Record<ProjectStatus, string> = {
  active:      "badge-primary",
  backlog:     "badge-neutral",
  on_deck:     "badge-warning",
  in_progress: "badge-progress",
  complete:    "badge-success",
  archived:    "badge-neutral badge-faded",
};

<span className={cn("badge", STATUS_BADGE[project.status])}>
  {STATUS_LABEL[project.status]}
</span>

// Static badge
<span className="badge badge-success">Complete</span>
<span className="badge badge-neutral badge-faded">Archived</span>
```

Color values for `badge-warning`, `badge-progress`, `badge-success`, and `badge-error` are defined as CSS variables (`--badge-*-bg`, `--badge-*-fg`) in the `:root` and `.dark` blocks of `globals.css` — the only place those colors appear in the codebase.

---

## Colour and theming principle

**Always use CSS variables for colours — never hard-code color values in components.**

The app has a palette-based theme system. Users can switch palettes and the whole UI re-colours automatically — but only if components reference CSS variables rather than hard-coded values.

- ✅ `bg-primary`, `text-muted-foreground`, `border-border`, `var(--primary)` — all theme-aware
- ❌ `bg-blue-100`, `text-amber-700`, `#3b82f6`, `oklch(0.5 0.2 250)` inline in JSX — all break theme switching

When a colour has no existing semantic variable, define it in the `:root` and `.dark` blocks of `globals.css` as a new `--variable-name`, then reference it from a CSS class. The badge system is the canonical example: `--badge-warning-bg` is defined once in `globals.css`, used by `.badge-warning`, and never appears in any component file.

---

## Anti-patterns — do not do these

- **Do not** hard-code colors in JSX or component CSS — add a CSS variable to `globals.css` and reference it by class instead.
- **Do not** write inline badge styles (raw `bg-*/text-*` color combos for status chips) — use `badge badge-{variant}` from `globals.css`.
- **Do not** use `title` attribute on `<span>` for tooltips — browsers only show native tooltips on interactive elements. Use the Radix `<Tooltip>` components.
- **Do not** use `accent-primary`, `border border-input`, or any inline `appearance` overrides on checkboxes — use `className="checkbox-themed"`.
- **Do not** add `cursor-pointer` to `<button>` or `<a>` elements — `globals.css:138` already applies it globally via `button, [role="button"], a { cursor: pointer }`.
- **Do not** use `useTheme()` from `next-themes` to check dark/light — it follows system preference, not the selected palette. Use `useThemeCustomizer()` + `isThemeDark(config)`.
- **Do not** write scrollbar styles per-component — they are themed globally in `globals.css`.
- **Do not** derive active state from a phantom `is_active` field — it doesn't exist on `HabitWithStats`. Always use `status === "active"`.

---

## API client

All data fetching goes through `$api` from `src/lib/api/query.ts`:

```typescript
import { $api } from "@/lib/api/query";

// Queries
const { data, isLoading } = $api.useQuery("get", "/habits", {
  params: { query: { limit: 100 } },
});

// Mutations
const { mutateAsync } = $api.useMutation("patch", "/habits/{habit_id}");
await mutateAsync({ params: { path: { habit_id: id } }, body: { name } });

// Invalidate after mutations
qc.invalidateQueries({ queryKey: ["get", "/habits"] });
```

The client middleware automatically attaches `Authorization: Bearer <token>` and throws on non-2xx responses.

**Raw `fetch()` calls — always use `apiBaseUrl`, never hardcode `/api/`.**  
In Tauri static builds there is no Next.js proxy, so `/api/...` resolves to `tauri://localhost/api/...` (dead end). Import `apiBaseUrl` from `client.ts` instead:

```typescript
import { apiBaseUrl } from "@/lib/api/client";

const res = await fetch(`${apiBaseUrl}/uploads`, { method: "POST", ... });
```

`apiBaseUrl` is `http://localhost:1338` in Tauri builds and `/api` in web builds — the same value `$api` uses internally.

**Upload/media URLs — always use `resolveMediaUrl`.**  
The API stores upload paths as relative strings (e.g. `/uploads/foo.jpg`). In Tauri these must be prefixed with the API origin to be fetchable. Use `resolveMediaUrl` from `client.ts` wherever an upload URL appears in an `<img src>`:

```typescript
import { resolveMediaUrl } from "@/lib/api/client";

<img src={resolveMediaUrl(recipe.cover_image_url) ?? ""} />
```

It's a no-op in web builds (relative URLs work via the proxy) and prepends `http://localhost:1338` in Tauri builds.

---

## Schema updates

Types in `src/lib/api/schema.d.ts` are generated from the FastAPI OpenAPI schema. When the API schema changes, regenerate:

```bash
cd web
npx openapi-typescript http://localhost:1338/openapi.json -o src/lib/api/schema.d.ts
```

**When the API is not running** (e.g. sandbox environments running Python < 3.12), edit `schema.d.ts` manually. Add new schemas to the `components > schemas` section and update the relevant path response types. Always regenerate from the live API before committing if possible.

---

## Habits domain

### Types
- `HabitWithStats` extends `HabitResponse` with `current_streak: number`, `completion_rate_7d: number | null`, `completion_rate_30d: number | null`
- `null` rates mean the habit is newer than the measurement window — display as `—`, not `0%`

### Cadence JSONB
The `cadence` field is a JSONB blob. Read it as `(habit.cadence ?? {}) as Record<string, unknown>`. Sub-fields:
- `days_of_week: number[] | null` — Python weekday values (Mon=0…Sun=6), sorted
- `times_per_period: number | null` — for weekly/monthly when no specific days chosen
- `start_date: string | null` — ISO date; monthly habits repeat on this day-of-month
- `link: { path: string; label: string } | null` — optional link to an app page; see AppLinkPicker below
- `preferred_time` — removed; do not use

### Day-of-week display convention
Backend stores Mon=0…Sun=6 (Python `weekday()`). UI displays Sun-first:
```typescript
const DAY_DISPLAY_ORDER = [6, 0, 1, 2, 3, 4, 5]; // maps display index → backend value
```
Use `DAY_DISPLAY_ORDER[i]` as the actual value when iterating over pill buttons.

### Frequency options
Supported: `daily`, `weekly`, `monthly`. `custom` was removed — it had no backend logic. Show day-of-week picker only for `daily` and `weekly`. Hide `times_per_period` when specific days are selected (the count is implied by the selected days).

### frequencyLabel
`frequencyLabel()` in `habit-row.tsx` checks `cadence.days_of_week` first. If set, displays day names (e.g. "Mon, Thu") or "Weekdays" for Mon–Fri. Falls back to frequency string otherwise.

### AppLinkPicker
`components/ui/app-link-picker.tsx` — a controlled combobox for selecting an internal app page. Used in the habit sheet's "Link to page" field.

```tsx
import { AppLinkPicker, type AppLinkValue } from "@/components/ui/app-link-picker";

<AppLinkPicker
  value={form.link}           // AppLinkValue | null
  onChange={(v) => set("link", v)}
/>
// AppLinkValue = { path: string; label: string }
```

Shows all nav sections by default; searches documents, projects, and recipes as you type (≥2 chars). Returns `{ path, label }` — store both so the label can be displayed without re-fetching.

### Two-affordance pattern (habits with links)
When a habit has `cadence.link` set, the name and the completion circle are separate tap targets:
- **Circle** → toggles completion (`e.stopPropagation()` prevents row click)
- **Name + link icon** → `router.push(habitLink.path)`

This pattern is implemented in both `habit-row.tsx` (table page) and `habits-widget.tsx` (dashboard). Replicate it anywhere habits are listed.

---

## Todos domain

### Recurrence
Recurring todos store a rule in the `recurring` JSONB field. When a recurring todo is marked done, the service auto-creates the next instance. The `recurring` field shape (see `todo-sheet.tsx`):
```typescript
{
  frequency: "daily" | "weekdays" | "weekly" | "monthly_date" | "monthly_weekday" | "yearly",
  interval: number,          // e.g. 2 = every 2 weeks
  days_of_week: number[],    // for weekly frequency
  end_date: string | null,   // ISO date or null
}
```

### Todo row indicators
`todo-row.tsx` shows a `<Repeat2>` icon (lucide-react) in the meta chip row when `todo.recurring` is set.

---

## Theming

Palettes are defined in `lib/theme/presets.ts`. Each palette sets all CSS custom properties. Selecting one calls `applyThemeConfig()` which toggles `.dark` on `<html>` and writes all `--variable` values.

BlockNote is themed by targeting `.bn-root` in `globals.css`. The `checkbox-themed` class in `globals.css` uses `var(--foreground)` for the border, `var(--primary)` for checked fill, and `var(--primary-foreground)` for the checkmark — it inherits the active theme automatically.

---

## Auth context

`src/lib/auth/context.tsx` exposes `useAuth()`. Full interface:

```typescript
interface AuthContextValue {
  user: User | null;          // includes .role ("owner" | "admin" | "member" | "viewer" | null)
  isLoading: boolean;
  impersonating: boolean;
  localeAutoDetected: boolean;
  dismissLocaleNotice: () => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  impersonateUser: (targetUserId: string) => Promise<void>;
  stopImpersonating: () => void;
}
```

**Impersonation (dev only):** `impersonateUser(id)` saves the current session to a React ref (`savedSessionRef`), POSTs to `POST /households/dev/impersonate/{id}`, and swaps in the new access token + user. `stopImpersonating()` restores from the ref. The ref is intentionally not persisted — impersonation is cleared on page reload. The shell shows an amber banner and amber avatar when `impersonating` is true.

**Locale auto-detection:** on first load, if `user.timezone` is null the context reads `Intl.DateTimeFormat().resolvedOptions().timeZone` and PATCHes `/auth/me`. `localeAutoDetected` is then set to `true` so the `LocaleDetectedBanner` (`components/locale-detected-banner.tsx`) shows once. Call `dismissLocaleNotice()` to clear it.

**Role-gating pattern:**
```typescript
const ADMIN_ROLES = new Set(["owner", "admin"]);
const isAdmin = ADMIN_ROLES.has(user?.role ?? "");
```
Use this pattern for any UI that should be visible only to admins. Do not add a separate `is_admin` field to `UserResponse`.

---

## Conventions

**Client vs server components:** default to server components. Add `"use client"` only when you need hooks, browser APIs, or event handlers.

**Forms and mutations:** use `$api.useMutation` with `mutateAsync`. Wrap in try/catch — the middleware throws on non-2xx. Invalidate relevant query keys after success.

**Error handling:** surface errors in UI state; don't swallow them silently.

**Resizable panels:** use the `useResizablePanel` hook with a unique `storageKey`. Drag handles are `<div>` elements with `onMouseDown={startResize}`.

---

## Recipes

The recipes list page (`app/(protected)/recipes/page.tsx`) is fully server-side filtered and paginated:

- **Search** — debounced 300ms via `useDebounce`; passed as `search` query param to `GET /recipes`
- **Tag filter** — multi-select combobox (`TagFilter` component, self-contained in the page file); passes `tag_ids[]` to `GET /recipes`; OR logic (recipes matching any selected tag); active tags sort to top of dropdown
- **Pagination** — 24 per page (`PAGE_SIZE = 24` — divisible by 2, 3, and 4 for even grid rows); `limit`/`offset` params
- Any filter/search change resets to page 0

Tag options are derived from two sources merged by id: `GET /tags` (all household tags) and tags extracted from the unfiltered recipe list (catches tags that exist on recipes before being created as standalone tags). The `TagFilter` combobox is right-anchored to avoid overflowing the viewport.

**Project progress ring** (`src/lib/projects/progress.ts`) — recursive fetch that computes completion as a 0–1 ratio. Has a module-level in-memory cache with 60s TTL (`progressCache`). Call `invalidateProgressCache(projectId)` after saving todos or sub-projects. Uses `apiBaseUrl` for raw fetch calls (Tauri-safe).

---

## Shared hooks

| Hook | Location | Purpose |
|---|---|---|
| `useSegmentId` | `lib/hooks/use-segment-id.ts` | Tauri-safe replacement for `useParams<{ id: string }>()` on dynamic routes |
| `useDebounce` | `lib/hooks/use-debounce.ts` | Delays a value update by N ms; use for search inputs before firing API calls |
| `useResizablePanel` | `lib/hooks/use-resizable-panel.ts` | Drag-to-resize panel with `localStorage`-persisted width |

---

## Documents

**Page tree collapse state** is stored in a module-level `Set<string>` in `page-tree.tsx` (outside the React component) — survives layout unmounts when navigating between routes.

**Document icons** — optional `icon` field (single emoji). Extracted from Notion HTML exports (`class="page-icon"`) or leading emoji-only line in MD files during import.

**Notion import** (`notion-import-dialog.tsx`) — prefers HTML over markdown when both exist. HTML parsed via `BlockNoteEditor.create()` calling `tryParseHTMLToBlocks()`. Use **"Export as HTML"** from Notion (not "Markdown & CSV") for correct toggle lists and icons.

Known issue: checkbox items nested inside toggle blocks trigger a BlockNote `blockContainer` parse error — fix pending.

---

## Tauri static export

The desktop app uses `next build` with `output: "export"` and `trailingSlash: true`. There is no Next.js server — the static files are served by Tauri's asset server from `web/out/`.

### Dynamic routes and `useSegmentId`

`generateStaticParams` for every dynamic route (`[id]`) returns only `[{ id: "index" }]` — a sentinel pre-render. This means:

- **Hard navigation** to `/recipes/<uuid>` causes Tauri to serve `recipes/index/index.html` (wrong HTML); `useParams()` returns `"index"` instead of the real UUID.
- **Client-side navigation** to `/recipes/<uuid>` triggers a RSC payload fetch at `tauri://localhost/recipes/<uuid>/__next.*.txt`; that file doesn't exist, so Next.js falls back to `/`.

Both are fixed:

1. **`useSegmentId`** (`src/lib/hooks/use-segment-id.ts`) — drop-in replacement for `useParams<{ id: string }>()` on all dynamic-route pages. Falls back to `window.location.pathname.split("/")[1]` when params are stale. Use this on every `[id]` route page.

2. **`TauriRscPatch`** (`src/components/tauri-rsc-patch.tsx`) — mounted once in `layout.tsx`. Patches `window.fetch` in Tauri builds to rewrite same-origin RSC payload fetches for UUID paths to their pre-generated `index` equivalents. **Critical:** only intercepts same-origin (`tauri://localhost`) requests — API calls to `http://localhost:1338` are explicitly excluded to avoid corrupting resource IDs.

### Building for Tauri

```bash
make desktop-web   # runs from repo root; sets NEXT_PUBLIC_TAURI=true and NEXT_PUBLIC_API_BASE_URL=http://localhost:1338
```

Do not run `npm run build` directly for the desktop build — the env vars must be set by the build script.

### React Query defaults for desktop

`providers.tsx` sets `staleTime: 30_000` and `refetchOnWindowFocus: false` globally. In a desktop app, window focus fires constantly (alt-tab); disabling it prevents a wave of redundant requests on every context switch. The 30s stale time means navigating back to a recently visited page serves from cache.

### Prefetching on hover

Warm both the RSC payload and the React Query cache when the user hovers a navigation target:

```typescript
function handlePrefetch(id: string) {
  router.prefetch(`/recipes/${id}`);
  queryClient.prefetchQuery({
    queryKey: ["get", "/recipes/{recipe_id}", { params: { path: { recipe_id: id } } }],
    queryFn: () => apiClient.GET("/recipes/{recipe_id}", { params: { path: { recipe_id: id } } })
      .then(r => { if (r.error) throw r.error; return r.data!; }),
    staleTime: 30_000,
  });
}
```

The query key format is `[method, path, params]` — match exactly what `$api.useQuery` generates or the cache won't be shared.

---

## Next.js API proxy

`src/app/api/[...path]/route.ts` proxies all requests to FastAPI. `API_URL` in `.env.local` controls the backend:

```
API_URL=http://localhost:1339   # local dev (make api runs on 1339; launchd service uses 1338)
API_URL=http://192.168.x.x:8000  # NAS
```

---

## Running locally

```bash
cd web && npm install && npm run dev   # starts on http://localhost:1337
```

---

## Building for production (Docker)

```bash
cd /volume1/docker/life-dashboard/infra
sudo docker compose build web && sudo docker compose up -d
```

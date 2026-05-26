---
description: Next.js/React conventions for Hearth's web frontend. Activated when editing web/src files.
paths:
  - "web/src/**"
---

# Frontend Rules

## API client — always use `$api`, never raw fetch to `/api/`

All server state goes through `$api` from `src/lib/api/query.ts`. Raw `fetch()` calls must use `apiBaseUrl` from `client.ts` — never hardcode `/api/` as the base path. The Tauri desktop build has no Next.js proxy; `/api/...` resolves to a dead end.

```typescript
// WRONG
const res = await fetch("/api/habits");

// CORRECT
const { data } = $api.useQuery("get", "/habits", { params: { query: { limit: 100 } } });

// For raw fetch (uploads, streaming), use apiBaseUrl:
import { apiBaseUrl } from "@/lib/api/client";
const res = await fetch(`${apiBaseUrl}/uploads`, { method: "POST", ... });
```

verify: Grep("fetch\(['\`]/api/", path="web/src/") → 0 matches

## Upload URLs — always `resolveMediaUrl`

API-stored upload paths are relative strings (`/uploads/foo.jpg`). In Tauri they must be prefixed. Use `resolveMediaUrl` from `client.ts` wherever an upload URL appears in `<img src>`:

```typescript
import { resolveMediaUrl } from "@/lib/api/client";
<img src={resolveMediaUrl(recipe.cover_image_url) ?? ""} />
```

verify: Grep("<img src=\{(?!resolveMediaUrl)", path="web/src/") → manual review

## Colors — CSS variables only, never Tailwind color scale in JSX

Hard-coded color utilities (`bg-blue-100`, `text-amber-700`, hex values, oklch inline) break theme switching. Always use semantic Tailwind classes or the badge system.

Status chips → `badge badge-{variant}` (see web/CLAUDE.md for variants)
New semantic colors → define in `:root` / `.dark` blocks of `globals.css`, reference via a CSS class

verify: Grep("className=.*bg-(red|blue|green|amber|violet|indigo|pink|orange|yellow|teal|cyan|purple|rose|lime|sky|fuchsia|slate|zinc|neutral|stone|gray|emerald)-", path="web/src/") → 0 matches

## UI primitives — do not reinvent

Before writing UI code, check in this order:
1. `components/ui/` — shadcn primitives (Button, Input, Select, Sheet, Tooltip, etc.)
2. `globals.css` utility classes — `checkbox-themed`, `badge badge-{variant}`
3. Grep for a similar pattern in the codebase and copy it

Specific anti-patterns from web/CLAUDE.md:
- Do NOT use `title` attribute on `<span>` for tooltips — use Radix `<Tooltip>` components
- Do NOT add `cursor-pointer` to `<button>` or `<a>` — `globals.css` applies it globally
- Do NOT use `accent-primary` or inline `appearance` overrides on checkboxes — use `className="checkbox-themed"`
- Do NOT use `useTheme()` from `next-themes` for dark/light detection — use `useThemeCustomizer()` + `isThemeDark(config)`

## Client vs server components

Default to server components. Add `"use client"` only when you need hooks, browser APIs, or event handlers. If a component uses `useState`, `useEffect`, `$api.useQuery`, or any event handler, it must be a client component.

## Dynamic routes — `useSegmentId` not `useParams`

On all dynamic route pages (`[id]`), use `useSegmentId` from `src/lib/hooks/use-segment-id.ts` instead of `useParams`. The Tauri static export serves a sentinel `index.html` for all UUIDs; `useParams()` returns `"index"` on hard navigation. `useSegmentId` falls back to `window.location.pathname`.

verify: Grep("useParams<", path="web/src/app/(protected)/") → 0 matches

## Mutations — disable during flight, invalidate after

```typescript
const { mutateAsync, isPending } = $api.useMutation("post", "/todos");

// Disable submit while in-flight
<Button disabled={isPending} onClick={handleSubmit}>Save</Button>

// Invalidate after success
qc.invalidateQueries({ queryKey: ["get", "/todos"] });
```

Never fire the same mutation twice by relying on disabling. Never optimistically insert new entities before server confirmation (optimistic updates are fine for status flips like completing a todo).

## Idempotency key — generate once when form opens

```typescript
const idempotencyKey = useRef(crypto.randomUUID());
// Use idempotencyKey.current as a stable header on POST requests
// Re-generating on every submit defeats its purpose
```

## Active state derivation

Do not derive active state from a phantom `is_active` field. For habits, always use `status === "active"`. For todos, check `completed_at === null`. Do not add computed boolean fields to response schemas unless the computation cannot be done client-side.

## Schema updates

When the API schema changes, regenerate:
```bash
cd web && npx openapi-typescript http://localhost:1338/openapi.json -o src/lib/api/schema.d.ts
```

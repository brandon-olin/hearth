# AGENTS – Life Dashboard (Logseq‑First Architecture)

This file explains the architecture and conventions for my Logseq‑based life dashboard so AI coding agents can act consistently.

Key principles:
- Logseq is the **primary UI and knowledge engine**.
- Data is stored as Markdown files on my NAS, not in third‑party clouds.
- The AI agent and backend services **augment** Logseq rather than replace it.

---

## Core Components

- **Logseq graphs**
  - `household` graph → `/data/logseq/household-graph/`
  - `brandon-private` graph → `/data/logseq/brandon-private/`
  - (Future) `partner-private` graph → `/data/logseq/partner-private/`

- **NAS**
  - Hosts the Logseq graph directories.
  - Runs Postgres (`postgres-1`) for structured data (tasks, events, feeds, AI artifacts, etc.).
  - Runs backend services/APIs that integrate Logseq data and AI workflows.

- **Gaming PC**
  - Runs the local LLM server (e.g., Ollama/LM Studio/custom container).
  - Accessible from the NAS and other devices via Tailscale.
  - The AI "agent" uses this model to process and transform data via tools/APIs.

Agents should assume:
- Logseq graphs are the source of truth for unstructured knowledge.
- Postgres and backend services are the source of truth for structured data and automations.
- All write operations happen through clear, well‑defined APIs or file operations, not ad‑hoc hacks.

---

## Graph Boundaries and Privacy

### 1. `household` graph
- Path: `/data/logseq/household-graph/`
- Scope: Shared, long‑term household knowledge, including:
  - groceries, pantry, and shopping lists;
  - chores and home maintenance;
  - household projects (repairs, renovations, planning);
  - family logistics and shared routines;
  - shared travel planning.

**Rules for agents:**
- Treat this as *shared* content.
- It is safe to surface, summarize, and use this data in shared dashboards or outputs that might be visible to multiple household members.
- When deciding where to put a new shared note, default to the `household` graph.

### 2. `brandon-private` graph
- Path: `/data/logseq/brandon-private/`
- Scope: Personal information, including:
  - journals and reflections;
  - career notes, job search, and life planning;
  - deep technical notes and research;
  - any sensitive personal material.

**Rules for agents:**
- Treat this as *private to Brandon*.
- Do **not** surface content from this graph in any UI or output intended for multiple users (e.g., shared household dashboards).
- It is acceptable to:
  - use this content for private summaries, dashboards, and analyses;
  - create tasks or structured data in Postgres linked to pages here, as long as outputs remain private.

### 3. Future: `partner-private` graph
- Path (planned): `/data/logseq/partner-private/`
- Scope: Partner's personal notes and journal.
- Rules mirror `brandon-private`:
  - private to partner,
  - not surfaced in Brandon's private views, except in explicitly shared contexts.

---

## Access Model (for Agents and Code)

When designing code or workflows:

1. **Do not assume a single graph.**
   - Always know which graph you are reading/writing.
   - Backend services should accept a graph identifier or path for operations.

2. **Honor the caller's context.**
   - "Household dashboard" views → read from `household` (and maybe some public/derived structured data).
   - "Brandon private dashboard" views → read from `brandon-private` (+ optionally household where appropriate).
   - Future partner flows → read from `partner-private` (+ household).

3. **Avoid cross‑leakage.**
   - Do not mix private graph content into shared outputs.
   - If a feature aggregates across graphs, require explicit configuration and enforce filters in code.

---

## Backend & Database Conventions

- **Postgres (`postgres-1`)**
  - Used for:
    - tasks and reminders,
    - events and schedules,
    - RSS/news/feed items,
    - AI‑generated summaries/insights,
    - other structured objects.
  - Tables should include:
    - references to Logseq pages/blocks (e.g., page name, block ID),
    - the graph name or ID (`household`, `brandon-private`, etc.).

- **Backend services**
  - Provide HTTP/JSON APIs for:
    - querying notes (via an index or precomputed views),
    - managing tasks/events,
    - triggering AI workflows (e.g., summarization, weekly reviews).
  - Frontend UIs (including Logseq plugins) should use these APIs instead of talking directly to Postgres.

- **AI agent**
  - Connects to the local LLM server on the gaming PC.
  - Exposes tools that:
    - read notes from specific graphs,
    - call backend APIs for structured data,
    - write back summaries or extracted tasks into:
      - Logseq (as pages/blocks), and/or
      - Postgres (as structured rows).

---

## Logseq Usage and Extensions

### Dashboards
- Dashboards should be **Logseq pages**, e.g.:
  - `[[Household Dashboard]]` in the `household` graph.
  - `[[Brandon Dashboard]]` in the `brandon-private` graph.
- Use Logseq features for dashboards:
  - `{{query}}` blocks to surface tasks, notes, and entries.
  - Properties and tags to structure data for queries.
  - Templates for recurring patterns (weekly review, project pages, etc.).

### Plugins
When a feature goes beyond what native pages/queries can do:
- Implement it as a **Logseq plugin** (ClojureScript/JS + React, consistent with Logseq's ecosystem) that:
  - adds sidebar items, commands, or custom views;
  - integrates with backend APIs and AI tools;
  - operates within a specific graph or set of graphs.

Agents should:
- Prefer extending Logseq via plugins and configuration over building an entirely separate UI.
- Keep plugin UI aligned with Logseq's defaults and patterns.

### Themes / Custom CSS
- Styling customizations should use Logseq theming and custom CSS.
- Avoid heavy front‑end frameworks or design systems unless there is a clear, justified need.

---

## Data Migration Context

- Notion data is being migrated via export (Markdown + CSV) and conversion scripts into Logseq.
- Split:
  - household‑level content → `household` graph.
  - personal content → `brandon-private` graph.
- Agents modifying migration code should:
  - preserve page names where possible,
  - keep backlinks and references consistent,
  - document any renaming or restructuring rules.

---

## AI‑Assisted Development Guidelines

When acting as a coding assistant on this project:

1. **Reinforce the Logseq‑first approach.**
   - Use Logseq graphs, queries, and plugins as primary tools.
   - Only propose external UIs when Logseq cannot reasonably support a requirement.

2. **Be explicit about graph usage.**
   - In design docs / comments, always state which graph(s) a feature touches.
   - When writing backend code, include clear parameters for graph selection.

3. **Optimize for maintainability.**
   - Prefer small, composable plugins and services over monolithic systems.
   - Avoid introducing unnecessary infrastructure or dependencies.

4. **Respect privacy and boundaries.**
   - Double‑check that private graph data never leaks into shared outputs.
   - If unsure, ask for clarification or default to *not* including private data.

---

## Priorities

If choices conflict, prioritize in this order:

1. **Data safety and privacy** – no accidental leaks between private and shared graphs.
2. **Local‑first, self‑hosted** – avoid new external SaaS dependencies.
3. **Simplicity** – favor straightforward, inspectable code and configurations.
4. **Good architecture over flashy UI** – this is a portfolio piece; design decisions should make sense to a senior engineer reviewing the repo.

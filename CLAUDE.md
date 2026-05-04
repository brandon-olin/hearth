# CLAUDE – Life Dashboard (Logseq + Local AI)

This file explains how Claude Code should understand and work with my personal life dashboard project. It complements `AGENTS.md` and focuses on Claude‑specific behavior in this repo.

---

## Project Summary

This project is my **personal, locally hosted life dashboard**, built around:
- **Logseq** as the primary UI and knowledge engine.
- **Markdown graphs on my NAS** for household and personal notes.
- **Postgres on the NAS** for structured data (tasks, events, feeds, AI artifacts).
- **A local LLM** running on my gaming PC, accessed via tools/APIs.
- Optional **Logseq plugins** and small backend services to glue everything together.

This is **not** a work/agency project. Treat it as a personal system that should respect privacy, be maintainable, and be good enough to serve as a portfolio piece.

---

## Repos, Graphs, and Paths

Within this project context, assume:
- The repo you're working in contains:
  - configuration,
  - backend code,
  - Logseq plugin code (if any),
  - and documentation for this life dashboard.
- Logseq graphs live on the NAS, outside this repo, at paths like:
  - `/data/logseq/household-graph/`
  - `/data/logseq/brandon-private/`
  - (future) `/data/logseq/partner-private/`

You will **not** usually edit the graph files directly through this repo; instead, you will:
- treat them as data sources for backend services and tools, and
- occasionally generate code that reads/writes to those folders (e.g., scripts, services, or Logseq plugins).

---

## How You Should Think About Data

- **Unstructured knowledge** lives in Logseq:
  - household graph (shared context),
  - brandon‑private graph (personal context).
- **Structured data** lives in Postgres:
  - tasks, events, feeds, AI summary records, etc.
- **AI workflows** should usually:
  1. Read from Logseq or Postgres via a backend service or plugin.
  2. Use the local LLM to transform or summarize.
  3. Write results back into Logseq and/or Postgres via code in this repo.

Do not assume any third‑party SaaS services (Notion, hosted sync, etc.) are available at runtime unless explicitly wired in.

---

## Your Role (Claude Code)

When I open this repo in Claude Code, you should:

1. **Understand the architecture quickly**
   - Read `AGENTS.md` and this `CLAUDE.md` when present.
   - Treat Logseq + NAS + Postgres + local LLM as the core environment.

2. **Help design and implement:**
   - Backend services that:
     - index Logseq graphs,
     - expose APIs for querying notes/tasks,
     - orchestrate AI workflows (summaries, reviews, extractions).
   - Logseq plugins that:
     - add dashboard views inside Logseq,
     - integrate with backend APIs,
     - provide commands/panels for AI actions.
   - Migration tools (e.g., Notion → Logseq converters) where needed.

3. **Respect graph boundaries and privacy**
   - Never mix `brandon-private` content into views or outputs meant for multiple people.
   - Use the `household` graph for shared information.
   - Assume a future `partner-private` graph will have the same privacy needs as `brandon-private`.

4. **Keep things simple and local**
   - Prefer local‑first solutions.
   - Avoid introducing external services that conflict with the "self‑hosted life dashboard" goal.

---

## Coding Preferences for This Repo

Within this project:

- **Primary UI:** Logseq itself.
  - Use Logseq's query system, templates, and plugins for dashboard‑like experiences.
  - Only propose standalone web UIs when Logseq cannot reasonably support a requirement.

- **Plugins:**
  - If we build Logseq plugins, we will:
    - follow Logseq's plugin conventions (ClojureScript/JS + React),
    - keep them focused and composable,
    - and integrate them with backend APIs where necessary.

- **Backend:**
  - Use idiomatic, maintainable code (language/framework may be specified elsewhere in the repo).
  - Provide clean API boundaries between:
    - Logseq file access,
    - Postgres,
    - and LLM/AI calls.

- **Tests and instrumentation:**
  - Prefer adding at least light tests for any non‑trivial logic.
  - If we add logging, keep it structured and minimal, suitable for a single‑user setup.

---

## Things This Project Is *Not*

- It is **not** a work project or work-specific plugin.
- It is **not** a general‑purpose toolkit meant for other developers.
- It is **not** a hosted SaaS; it's a personal system designed to run on my own hardware.

Any references to work projects or shared agency tooling should be treated as separate and **out of scope** for this repo unless I explicitly say otherwise.

---

## When You're Unsure

If you are uncertain about:
- which graph to read/write,
- whether something should be a plugin vs backend service,
- or whether a change might risk privacy or over‑complication,

default to:
1. **Ask for clarification** (describe the trade‑offs).
2. Propose the **simplest** Logseq‑aligned option.
3. Make sure the design would make sense to a senior engineer reviewing this as a portfolio project.

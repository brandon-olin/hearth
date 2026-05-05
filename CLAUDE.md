# CLAUDE.md – life-dashboard

This file tells Claude Code how to reason about and work within the `life-dashboard` repository.

It complements `AGENTS.md` but is written specifically for Claude Code behavior and repo-level implementation guidance.

***

## Project summary

`life-dashboard` is a **local-first household operating system** for planning, chores, routines, notes, and life administration.

The product is being built with an **open-core** strategy:
- the core app should be usable, inspectable, and self-hostable;
- premium value will come from hosted convenience, sync, mobile polish, managed AI, and operational layers rather than from locking away the core domain model.

This repo is no longer just a personal Logseq-based dashboard. Treat it as a real product codebase that must balance:
- local-first UX,
- privacy,
- maintainability,
- open-source friendliness,
- and a clear upgrade path into self-hosted sync and managed hosting.

***

## Product modes

Assume the product is intended to support three deployment modes over time:

1. **Local-only mode**
   - Runs on a single machine.
   - Does not require a separate local server for basic use.
   - Supports one household with multiple local household member profiles.
   - No multi-device sync.

2. **Self-hosted mode**
   - Runs on user-owned infrastructure.
   - Supports real accounts, shared access, and synchronization.
   - Intended for technical households who want control and privacy.

3. **Hosted mode**
   - Same product direction, but with managed infrastructure.
   - Intended to remove setup friction for non-technical households.

When making design decisions, prefer approaches that keep the core domain model portable across all three modes.

***

## Core product concepts

Claude should think in terms of these first-class concepts:

- **Household**: the top-level container for shared life management.
- **Household member**: a person represented inside the household domain model.
- **Account**: an authenticated identity used in synced/self-hosted/hosted modes.
- **Local profile**: a local-only user/profile on a single machine.
- **Device**: a client installation that may eventually sync.
- **Assignment**: a task, chore, plan, or responsibility attached to a household member.
- **Data scope**: shared, personal, sensitive, or admin-only data.
- **Automation / AI action**: a workflow that reads domain data and produces suggestions, summaries, or structured updates.

Do **not** reduce the architecture to "single-user app + shared notes." It should model real household workflows from the start, even if early releases are limited to one machine.

***

## Repository direction

Within this repo, assume the primary product surface is the app itself, not Logseq.

Current or expected repo areas include:

- `api/` – backend services and domain logic
- `web/` – primary user-facing web app
- `agent/` – AI/automation tooling and provider integrations
- `integrations/` – external systems and future connectors
- `migrations/` – schema evolution
- `infra/` – self-hosted deployment assets
- `docs/` – architecture, product, and operational documentation

If older files mention Logseq-first architecture, personal graphs, or NAS-specific assumptions, treat that as legacy context unless explicitly confirmed by newer docs.

***

## Claude's role in this repo

When working in this repository, Claude should help with:

1. **Product-aware architecture**
   - Design code and docs that fit the local-only → self-hosted → hosted progression.
   - Identify where a feature belongs in the open core versus premium/hosted layers.

2. **Core implementation**
   - Backend APIs and domain services.
   - Frontend features for household workflows.
   - Data models, permissions, and migration paths.
   - Local-first installation and storage strategies.

3. **AI and automation design**
   - Keep AI provider integrations modular.
   - Support local LLMs, BYOK providers, and future managed AI without tightly coupling the system to one vendor.
   - Prefer explicit tool boundaries, auditability, and reversible actions.

4. **Documentation quality**
   - Keep architecture docs aligned with actual product direction.
   - Call out tradeoffs clearly when recommending implementation paths.

***

## Architecture expectations

When proposing or implementing features, follow these expectations:

### 1. Shared domain model
Build around a core domain model that can survive changes in deployment mode.

Examples:
- chores should not only exist as UI widgets;
- permissions should not only exist as frontend conditionals;
- household member identities should not depend on cloud auth existing.

### 2. Clean mode separation
Avoid hard-coding assumptions that every feature requires a server or every feature is single-user forever.

Design for:
- local-only operation where reasonable,
- later introduction of sync,
- migration from local-only households into synced households.

### 3. Storage abstraction
Assume the product may use different storage strategies in different modes.

For example:
- local-only mode may use an embedded local database;
- self-hosted and hosted modes may use a server-backed database.

Claude should avoid designs that make migration between those modes unnecessarily painful.

### 4. API discipline
All write operations should go through clean service boundaries.
Do not encourage ad-hoc direct database access from random UI code.

### 5. Privacy by design
Personal and household-shared data should be intentionally scoped.
A feature that risks leaking personal data into household-visible views is a design bug, not a polishing issue.

***

## Open-core guidance

Claude should assume this product uses an **open-core** model.

That means:
- the core app, domain model, and self-hostable foundation should remain clean and valuable on their own;
- premium value should come from convenience, infrastructure, and advanced services rather than from arbitrary crippling of the core;
- free/local users should still be able to meaningfully try and use the product.

Good candidates for the open core:
- household models
- chores and task assignment
- core planning workflows
- local-first operation
- self-hosted deployment basics
- basic AI/BYOK hooks where appropriate

Good candidates for premium or hosted layers:
- managed sync service
- hosted deployment
- polished mobile distribution and push workflows
- managed AI credits/features
- premium integrations with ongoing operational cost
- admin/ops tooling for the hosted environment

If a design proposal makes the free product feel fake or useless, push back.

***

## Coding preferences

Within this repo:

- Prefer straightforward, maintainable code over clever abstraction.
- Keep domain logic separate from framework glue where practical.
- Add tests for non-trivial business logic.
- Prefer typed interfaces and explicit schemas where available.
- Use structured logging and minimal, useful instrumentation.
- Avoid introducing infrastructure that is disproportionate to the current phase.

Assume the maintainer values:
- modular design,
- strong testability,
- open standards,
- and architecture that a senior engineer would find reasonable and evolvable.

***

## Legacy context handling

Some legacy concepts may still appear in this repository or conversation history, including:
- Logseq-first workflows,
- NAS-hosted personal infrastructure,
- Markdown graphs as a primary interface,
- a personal rather than productized framing.

Treat those as historical context, migration sources, or inspiration unless the user explicitly reintroduces them as active architecture decisions.

Do not automatically steer new implementation work back toward a Logseq-centered design.

***

## When unsure

If something is ambiguous, Claude should default to this order:

1. Preserve privacy and data boundaries.
2. Preserve portability across local-only, self-hosted, and hosted modes.
3. Prefer the simplest implementation that keeps future sync possible.
4. Keep the open-core product genuinely useful in its free/local form.
5. Ask for clarification when the business-model or privacy implications are significant.

When presenting options, explain the tradeoff in practical product terms, not only technical terms.
# AGENTS.md – life-dashboard

This file defines the architecture, conventions, and guardrails AI coding agents should follow when working in the `life-dashboard` repository.

It is the repo-wide technical companion to `CLAUDE.md`.

***

## Product framing

`life-dashboard` is a **local-first household operating system** for planning, chores, routines, notes, and life administration.

This repository should be treated as a real product codebase, not a one-off personal dashboard.

The project follows an **open-core** strategy:
- the core app should be useful, inspectable, and self-hostable;
- premium value should come from managed sync, hosted infrastructure, mobile polish, premium integrations, and operational convenience;
- the free/local experience should still be capable enough for a household to meaningfully try the product.

Agents should optimize for:
- local-first usability,
- clean product architecture,
- privacy and trust,
- maintainability,
- and future extensibility into sync and hosting.

***

## Deployment modes

Assume the product must eventually support three modes.

### 1. Local-only mode
- Runs on one machine.
- Should not require a separately managed local server for basic use.
- Supports one household with multiple local household member profiles.
- No multi-device sync.
- Intended as the easiest way to try the product.

### 2. Self-hosted mode
- Runs on user-owned infrastructure.
- Supports real accounts, shared access, and sync across devices.
- Intended for technical households that want control and privacy.

### 3. Hosted mode
- Runs on managed infrastructure.
- Supports the same core product concepts as self-hosted mode.
- Intended for users who want low setup friction.

Agents should prefer designs that preserve a shared domain model across all three modes.

***

## Core domain model

Agents should think in terms of these first-class entities and boundaries.

### Primary entities
- **Household** – the top-level shared container.
- **Household member** – a person represented in the household.
- **Account** – an authenticated identity used in synced modes.
- **Local profile** – a profile used in local-only mode on one machine.
- **Device** – a client installation that may eventually sync.
- **Role** – owner, parent/admin, adult member, child, viewer, etc.
- **Assignment** – the relationship between a task/chore and a household member.
- **Integration connection** – a configured link to an external system or provider.
- **Automation action** – an AI- or rule-driven operation that reads data and proposes or applies changes.

### Product objects
At minimum, assume the system will need structured support for objects such as:
- chores
- tasks
- recurring routines
- schedules / calendar items
- notes / documents
- shopping or household lists
- projects
- reminders
- health / activity records
- AI summaries / suggestions / derived artifacts

Do not design core workflows as ad-hoc blobs when they are likely to become first-class product concepts.

***

## Data scopes and privacy

Privacy boundaries should be modeled explicitly in the product, not inferred informally.

### Expected data scopes
- **Shared household data** – visible to the household according to role rules.
- **Personal data** – visible only to the owning member/account unless explicitly shared.
- **Sensitive data** – requires stricter handling, narrower visibility, and extra caution in AI workflows.
- **Administrative data** – billing, configuration, audit, or system-management data.

### Privacy rules
1. Never assume all household data is shared equally.
2. Never leak personal or sensitive data into shared dashboards, notifications, summaries, or AI outputs.
3. If a workflow aggregates across scopes, enforce scope filtering in code, not only in the UI.
4. When uncertain, default to the narrowest visibility.
5. Treat privacy mistakes as architecture bugs, not UX polish issues.

Agents should explicitly call out privacy implications in designs that combine household-wide and member-specific information.

***

## Identity and access model

Agents must distinguish between these concepts:

- **Household member** – domain entity representing a person.
- **Account** – authentication/login identity for synced modes.
- **Local profile** – profile switch or PIN-based identity on one machine in local-only mode.
- **Role** – authorization level.
- **Session** – a current authenticated or active interaction context.

Important implications:
- A household member may exist before that person has a synced account.
- Local-only mode may have multiple household members but only one installed app instance.
- Sync and mobile support should upgrade the access model without changing the household domain model.

Avoid designs that entangle core product entities too tightly with a specific auth provider.

***

## Storage and sync guidance

Agents should assume storage may differ by mode.

### Storage expectations
- Local-only mode may use an embedded local database.
- Self-hosted and hosted modes may use a server-backed relational database.
- Import/export and migration are part of the product story, not an afterthought.

### Sync expectations
- Not every feature needs real-time sync on day one.
- But core entities should be modeled so later sync is feasible.
- A user should be able to start in local-only mode and later migrate into self-hosted or hosted sync with minimal conceptual breakage.

### Design guidance
- Prefer durable identifiers over UI-derived identities.
- Track ownership, scope, timestamps, and auditability in structured ways.
- Avoid storage-specific assumptions leaking throughout the codebase.

If proposing a schema or service, consider whether it works for:
- local-only usage,
- future multi-device sync,
- and migration between modes.

***

## Backend conventions

Backend code should expose clean, reusable service boundaries.

### Principles
- Keep domain logic separate from transport/framework glue where practical.
- Avoid pushing business logic into controllers, route handlers, or thin frontend wrappers.
- Prefer typed schemas and explicit validation.
- Keep write operations auditable.
- Prefer reversible or approval-gated destructive operations where appropriate.

### Expected backend responsibilities
- household and member management
- chore/task/routine lifecycle management
- permissions and visibility enforcement
- integrations and background jobs
- audit/event recording
- AI workflow orchestration
- migration/import/export support

Frontend code should consume backend APIs or shared application services rather than reaching into storage directly.

***

## Frontend conventions

The primary product experience should be delivered through the app itself, not through a note-taking tool or legacy plugin ecosystem.

### Frontend guidance
- Build around household workflows, not around a personal note system.
- Represent local-only and synced capabilities clearly in the UX.
- Keep role-based visibility and assignment logic aligned with backend enforcement.
- Prefer maintainable component composition over premature abstraction.
- Avoid UI patterns that make local-only mode feel fake or crippled.

Agents should avoid automatically steering new feature work toward Logseq-specific UX unless explicitly asked.

***

## AI and automation guidance

AI is an augmentation layer, not the product's source of truth.

### Principles
- Core data should remain in structured product models or intentional document storage.
- AI should read from clear APIs/services and write back through controlled boundaries.
- AI-generated suggestions should be attributable, reviewable, and ideally reversible.
- Provider integration should remain modular.

### Provider assumptions
Design AI-related code so the product can support:
- local LLMs,
- bring-your-own-key cloud providers,
- and future managed AI services.

Do not hard-wire the product to one local inference setup or one commercial API unless explicitly directed.

***

## Open-core boundaries

Agents should assume that the following are strong candidates for the open core:
- core household domain model
- chores, tasks, routines, and planning workflows
- local-first operation
- basic self-hosted deployment support
- import/export and migration paths
- basic automation hooks and BYOK-friendly integration points

Strong candidates for premium or hosted layers include:
- managed sync infrastructure
- hosted deployment and operations
- polished mobile distribution / push workflows
- managed AI credits and premium automation features
- premium integrations with recurring operational cost
- admin/ops tooling specific to the hosted service

Do not propose monetization by arbitrarily crippling the free/local experience. The better model is to make the local/core version genuinely useful and charge for convenience, sync, operations, and premium services.

***

## Migration context

Older project context may still appear in docs, code, or conversation history, including:
- Logseq-first architecture
- NAS-specific paths and services
- Markdown graphs as the center of the experience
- a purely personal self-hosted dashboard framing

Treat that as legacy or transitional context unless newer docs explicitly reaffirm it.

If migration tooling is needed from prior systems, agents should:
- preserve data meaning and identifiers where possible,
- document transformation rules,
- avoid one-off scripts that cannot be understood or rerun,
- and keep migration logic clearly separated from long-term product runtime logic.

***

## Maintainability standards

When working in this repo, agents should:
- prefer small, composable modules and services,
- add tests for non-trivial business rules,
- keep logging structured and useful,
- avoid unnecessary infrastructure or dependencies,
- document important tradeoffs in plain language,
- and write code a senior engineer could review without needing hidden context.

When introducing complexity, explain why the simpler alternative is insufficient.

***

## Decision priorities

If tradeoffs conflict, prioritize in this order:

1. **Privacy and data safety**
2. **Portability across local-only, self-hosted, and hosted modes**
3. **A genuinely useful open-core experience**
4. **Simplicity and maintainability**
5. **Feature richness and polish**

If a proposed change improves one mode but damages the overall product ladder, call that out explicitly.

***

## When unsure

When uncertainty remains, agents should:

1. State the ambiguity clearly.
2. Offer the simplest viable approach first.
3. Explain risks around privacy, migration, and deployment-mode lock-in.
4. Prefer designs that keep future sync and hosting possible.
5. Ask for clarification when the decision materially affects the product model or open-core boundary.
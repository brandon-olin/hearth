# life-dashboard

Open-source, local-first household operating system for planning, chores, routines, notes, and automation.

`life-dashboard` is being designed as a privacy-respecting household platform that works in three modes:

1. **Local-only** — one device, no server required, ideal for trying the product.
2. **Self-hosted** — shared household data with sync across devices on your own infrastructure.
3. **Hosted** — the same product experience without the self-hosting overhead.

The goal is to let people start small, keep ownership of their data, and upgrade to sync and multi-device collaboration only when they need it.

## Product direction

This project is evolving from a personal self-hosted dashboard into a reusable product with a strong open-source core.

Core principles:

- **Local-first**: the app should remain useful without a permanent network connection or managed backend.
- **Household-aware**: chores, routines, calendars, tasks, and dashboards should support multiple household members.
- **Privacy-respecting**: personal and shared data should be modeled explicitly and kept separate by design.
- **Open-source core**: the core product should be inspectable, hackable, and usable by individuals and self-hosters.
- **Upgradeable collaboration**: sync, mobile access, notifications, backups, and hosted convenience are premium layers, not prerequisites.

## Planned modes

| Mode | Primary use case | Storage | Accounts | Sync |
|---|---|---|---|---|
| Local-only | One household using one computer | Local on-device database | Local household profiles | No |
| Self-hosted | Technical households who want shared access | Server database on user infrastructure | Real user accounts | Yes |
| Hosted | Non-technical households | Managed cloud database | Real user accounts | Yes |

The local-only mode is especially important: someone should be able to install the app, create a household, assign chores, and explore the product without first setting up Docker, Postgres, reverse proxies, or a NAS.

## Scope

The long-term product vision includes:

- Household dashboards
- Chores and recurring routines
- Task assignment by household member
- Shared and personal planning
- Notes and lightweight documentation
- Health / activity integrations
- AI-assisted summaries and automation
- Home and life administration workflows

The near-term focus is narrower:

- Define the core household domain model
- Build the API and web app around that model
- Support a credible local-only experience
- Keep the architecture compatible with later sync and hosted deployment

## Architecture

The repository is structured around a shared domain model that should eventually support all deployment modes.

```text
life-dashboard/
├── api/                # FastAPI backend
├── web/                # Next.js frontend
├── agent/              # AI/automation client and tools
├── integrations/       # External integrations
├── infra/              # Self-hosting configs
├── migrations/         # Database migrations
└── docs/               # Product, architecture, and operational docs
```

### Current stack

- **Backend**: FastAPI
- **Frontend**: Next.js
- **Database**: Postgres today; local mode may also require an embedded local database such as SQLite
- **Migrations**: SQL / Alembic-compatible migrations
- **AI layer**: local and hosted provider support planned

### Architectural goals

- Keep the domain model independent from deployment mode.
- Separate household members, accounts, devices, and permissions cleanly.
- Support migration from local-only mode to synced mode later.
- Avoid coupling core product logic to one specific AI provider or one specific hosting model.

## Open-source plan

This repository is intended to be published as open source with a permissive core.

Planned baseline repository files:

- `LICENSE`
- `README.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`

A license is required if you want others to legally use, modify, and share the code. If you choose MIT, others may also use the code commercially as long as they retain the copyright and license notice.

## Roadmap

| Phase | Status | Focus |
|---|---|---|
| 0 | in progress | Core schema, multi-user model, audit, permissions groundwork |
| 1 | pending | FastAPI backend with household-aware CRUD and auth |
| 2 | pending | Next.js web app for household workflows |
| 3 | pending | Local-only installation path and migration flow into sync |
| 4 | future | AI provider abstraction, automations, integrations |
| 5 | future | Self-hosted sync and managed hosting |

## Contributing

Contribution guidelines are not finalized yet. For now, the project is still in active architecture and product-definition mode.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
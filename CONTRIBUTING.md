# CONTRIBUTING.md

Thanks for your interest in contributing to `life-dashboard`.

This project is still early and the architecture is actively evolving, so the most helpful contributions are usually small, focused, and easy to review.

## Before you start

Please read these files first:

- `README.md` for the project direction and deployment model
- `CLAUDE.md` for Claude-specific repo guidance
- `AGENTS.md` for architecture conventions and guardrails

The short version is:
- this is a **local-first household product**,
- it follows an **open-core** model,
- and changes should preserve a path from local-only use to self-hosted and hosted sync later.

## What kind of contributions are welcome

Good early contributions include:

- bug fixes
- documentation improvements
- tests for existing behavior
- schema and domain-model improvements
- UX improvements that fit the local-first product direction
- refactors that simplify the code without changing product intent

Please avoid large speculative rewrites before discussing them first.

## Please discuss first

Open an issue or start a discussion before working on:

- major architecture changes
- database model rewrites
- authentication / authorization redesigns
- sync engine changes
- monetization-related changes
- major dependency swaps
- large UI rewrites

This helps avoid wasted effort and keeps the product direction coherent.

## Product guardrails

When contributing, please keep these principles in mind:

- Preserve **privacy boundaries** between shared, personal, and sensitive data.
- Avoid designs that only work in one deployment mode.
- Keep the **open-core** version genuinely useful.
- Prefer straightforward, maintainable code over clever abstractions.
- Avoid introducing infrastructure that is too heavy for the current stage of the project.

## Development expectations

When possible:

- keep pull requests focused and reasonably small
- add or update tests for non-trivial logic
- update docs when behavior or architecture changes
- explain important tradeoffs in the PR description

If a change affects privacy, permissions, migration, or future sync behavior, call that out explicitly.

## Pull request guidelines

A good pull request usually includes:

- a clear summary of what changed
- the reason for the change
- screenshots or recordings for UI changes, if relevant
- notes about schema, migration, or compatibility impact, if relevant
- follow-up work that is intentionally out of scope

Small, well-scoped PRs are much more likely to be merged quickly than large ones.

## Issues

When filing an issue, please include:

- what you expected to happen
- what actually happened
- steps to reproduce the problem
- environment details if relevant
- screenshots or logs if they help

For feature requests, explain the user problem first and the proposed solution second.

## Code style

There is not yet a fully formalized style guide for every part of the repo, but in general:

- prefer readable, explicit code
- keep domain logic separate from framework glue where practical
- avoid one-off hacks that make future sync or migration harder
- follow existing patterns unless there is a strong reason to improve them

## AI-assisted contributions

AI-assisted work is fine, but please review it carefully before submitting.

If you use AI tooling to help with code or docs:
- make sure the result matches the repo's actual architecture
- remove stale assumptions from older project directions
- verify migrations, permissions, and privacy-sensitive logic manually

Generated code that ignores the local-first or open-core direction is unlikely to be accepted.

## License

By contributing to this repository, you agree that your contributions will be licensed under the repository's license.

## Early-stage note

Because this project is still taking shape, not every good idea will be merged right away. Sometimes the right answer will be "not yet" rather than "no".

Thanks again for taking the time to contribute.
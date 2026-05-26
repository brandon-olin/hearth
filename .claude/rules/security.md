---
description: Security rules for auth, domain services, and API routers. Activated when editing auth code, domain services, or route handlers.
paths:
  - "api/src/life_dashboard/auth/**"
  - "api/src/life_dashboard/domains/**"
  - "api/src/life_dashboard/households/**"
  - "api/src/life_dashboard/main.py"
---

# Security Rules

## Authentication and authorization

The `get_current_user` dependency handles JWT verification. Every authenticated route must declare it via `Depends(get_current_user)`. Never inline token parsing in a route handler.

Role-gating uses the `role` attribute injected onto the user object by the dependency — it is a string value of `MembershipRole` (e.g. `"owner"`, `"admin"`, `"member"`, `"viewer"`). The `_ADMIN_ROLES` set in each router (`{MembershipRole.owner, MembershipRole.admin}`) is the single source of truth for admin-only checks. Do not add a `role` column to the `users` table.

For any endpoint accepting a resource ID, verify the authenticated user owns or belongs to the resource's household **in the service layer**, not the router. IDOR (insecure direct object reference) is the most common web app vulnerability — a user who guesses a UUID must not be able to access another household's data.

## Database — parameterized queries only

SQLAlchemy's `select()` API is inherently parameterized. Never use string formatting or f-strings to build query conditions:

```python
# WRONG — SQL injection risk
query = f"SELECT * FROM todos WHERE household_id = '{household_id}'"

# CORRECT — parameterized via SQLAlchemy
stmt = select(Todo).where(Todo.household_id == household_id)
```

When building dynamic filters (search, sorting, tag filtering), whitelist the allowed field names before using them as column references. Never pass user input directly as a column name.

## Input validation

All request bodies are Pydantic v2 schemas. Pydantic validates shape and types. You are still responsible for:
- String length limits on user-controlled fields (prevent memory exhaustion / DB column overflow)
- Numeric range checks (prevent overflow on integer fields)
- Enum validation (Pydantic handles this if you use `Enum` types — always use them for status fields)

Never trust `Content-Type` headers for file uploads. Validate actual file content, not just the extension.

## Secrets and PII

`.env` and `.env.*` files are off-limits. Settings come from `core/settings.py` (`pydantic-settings`). If you encounter a hardcoded secret during a session, flag it immediately — do not just note it.

Never log PII (email addresses, passwords, tokens, household member names). Use structured logging (`logger.info`, not `print`). Error responses to clients must not expose stack traces, SQL errors, file paths, or internal service names.

## CORS and middleware

CORS configuration lives in `main.py`. Do not modify allowed origins without understanding the deployment tier (local dev allows localhost; production will be tighter). Never add a wildcard `*` origin in non-development environments.

## Soft deletes — prefer over hard deletes

Use `archived_at: datetime | None` rather than `DELETE` for user-generated content that should be recoverable. Hard deletes are appropriate only for join table rows (taggings, memberships) where no audit trail is needed.

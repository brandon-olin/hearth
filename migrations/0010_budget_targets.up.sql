-- budget-006: Monthly envelope budgeting — per-category targets.
--
-- Two-layer target system (YNAB-inspired):
--   1. budget_categories.default_monthly_amount — the standing monthly target
--      that applies to every month unless overridden.
--   2. budget_targets — per-month overrides keyed by (category_id, year, month).
--      NULL amount in budget_targets is not meaningful; delete the row to revert
--      to the default.
--
-- Effective target resolution (handled in the service layer):
--   override row (year, month) → default_monthly_amount → NULL (no target set)

-- ── 1. Default monthly target on categories ───────────────────────────────────

ALTER TABLE budget_categories
    ADD COLUMN default_monthly_amount NUMERIC(12, 2) NULL;

-- ── 2. Per-month override table ───────────────────────────────────────────────

CREATE TABLE budget_targets (
    id           UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    household_id UUID         NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    category_id  UUID         NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    year         INTEGER      NOT NULL,
    month        INTEGER      NOT NULL CHECK (month BETWEEN 1 AND 12),
    amount       NUMERIC(12, 2) NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT budget_targets_unique UNIQUE (category_id, year, month)
);

CREATE INDEX idx_budget_targets_household_month
    ON budget_targets (household_id, year, month);

CREATE INDEX idx_budget_targets_category
    ON budget_targets (category_id);

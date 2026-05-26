-- budget-008: Month-to-month rollover for underspent categories.
--
-- Design:
--   budget_categories.rollover_enabled      — opt-in flag per category.
--   budget_rollover_amounts                  — dedicated table for computed
--                                             carry-forward amounts per
--                                             (category, year, month).
--
-- Keeping rollover separate from budget_targets avoids ambiguity: a targets
-- row requires an explicit user-set amount (NOT NULL), while a rollover row
-- exists purely to carry a balance forward.  The analytics layer combines
-- them: effective_target = base_target + rollover_amount.
--
-- Rollover semantics:
--   effective_target(M) = base_target(M) + rollover_amount(M)
--   rollover_amount(M)  = effective_target(M-1) - actual_spending(M-1)
--                         (can be negative when M-1 was overspent)
--
-- Rollover amounts are computed by POST /budget/rollover?year=&month= and
-- stored here.  Recomputing is idempotent.  The frontend calls this endpoint
-- automatically when the user navigates to a new month.

-- ── 1. Opt-in flag on categories ─────────────────────────────────────────────

ALTER TABLE budget_categories
    ADD COLUMN rollover_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- ── 2. Stored carry-forward table ────────────────────────────────────────────

CREATE TABLE budget_rollover_amounts (
    id           UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    household_id UUID         NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    category_id  UUID         NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    year         INTEGER      NOT NULL,
    month        INTEGER      NOT NULL CHECK (month BETWEEN 1 AND 12),
    -- Positive = unspent balance carried forward (adds to target).
    -- Negative = overspend carried forward (reduces effective target).
    rollover_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    computed_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT budget_rollover_amounts_unique UNIQUE (category_id, year, month)
);

CREATE INDEX idx_budget_rollover_household_month
    ON budget_rollover_amounts (household_id, year, month);

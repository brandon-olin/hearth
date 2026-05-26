-- budget-005: Category groups for collapsible budget category sections.
-- Adds budget_category_groups and a group_id FK on budget_categories.
-- Default groups are seeded here to match the YNAB-inspired taxonomy described
-- in feature_list.json (budget-005). Any household that already has categories
-- will have those categories left ungrouped (group_id = NULL), which the UI
-- renders under the implicit "Other" bucket.

-- ── 1. Groups table ───────────────────────────────────────────────────────────

CREATE TABLE budget_category_groups (
    id           UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    household_id UUID         NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    name         VARCHAR(100) NOT NULL,
    sort_order   INTEGER      NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_budget_category_groups_household
    ON budget_category_groups (household_id, sort_order);

-- ── 2. FK on budget_categories ────────────────────────────────────────────────

ALTER TABLE budget_categories
    ADD COLUMN group_id UUID REFERENCES budget_category_groups(id) ON DELETE SET NULL;

CREATE INDEX idx_budget_categories_group
    ON budget_categories (group_id);

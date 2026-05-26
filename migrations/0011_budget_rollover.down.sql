-- Reverse of 0011_budget_rollover.up.sql

DROP TABLE IF EXISTS budget_rollover_amounts;

ALTER TABLE budget_categories
    DROP COLUMN IF EXISTS rollover_enabled;

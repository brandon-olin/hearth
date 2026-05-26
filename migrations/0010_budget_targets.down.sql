-- Reverse of 0010_budget_targets.up.sql

DROP TABLE IF EXISTS budget_targets;

ALTER TABLE budget_categories
    DROP COLUMN IF EXISTS default_monthly_amount;

-- Reverse migration for 0009_budget_category_groups

ALTER TABLE budget_categories DROP COLUMN IF EXISTS group_id;

DROP TABLE IF EXISTS budget_category_groups;

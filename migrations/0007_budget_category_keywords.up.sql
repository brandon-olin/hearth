-- Add keywords array to budget_categories for auto-categorization
ALTER TABLE budget_categories
    ADD COLUMN keywords JSONB DEFAULT NULL;

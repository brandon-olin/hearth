-- Add is_transfer flag to budget_transactions.
-- Transfers between internal accounts are excluded from income/expense aggregates.
ALTER TABLE budget_transactions ADD COLUMN is_transfer BOOLEAN NOT NULL DEFAULT FALSE;

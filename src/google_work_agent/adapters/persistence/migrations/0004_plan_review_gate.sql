-- Migration 0004: durable post-modify plan review gate.
ALTER TABLE plans
ADD COLUMN review_status TEXT NOT NULL DEFAULT 'PASSED'
CHECK (review_status IN ('PASSED', 'REQUIRED', 'REVISE', 'RETRIEVE_MORE', 'BLOCKED'));

ALTER TABLE plans
ADD COLUMN review_version INTEGER NOT NULL DEFAULT 0
CHECK (review_version >= 0);

-- Forward-only adoption marker for the exact supported pre-squash v18 baseline.
-- The v18 schema is already structurally equivalent to 0001_current_schema;
-- migration.py verifies every immutable legacy receipt before applying this marker.
SELECT 1;

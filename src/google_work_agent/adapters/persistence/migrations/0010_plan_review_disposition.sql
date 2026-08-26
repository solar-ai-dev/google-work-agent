-- Migration 0010: persist the exact current Review disposition separately from its gate.
ALTER TABLE plans
ADD COLUMN review_disposition TEXT
CHECK (
    review_disposition IS NULL OR review_disposition IN (
        'PASS', 'REVISE', 'RETRIEVE_MORE', 'ROUTE_RECONSIDERATION', 'CONFIRM', 'BLOCK'
    )
);

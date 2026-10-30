CREATE TABLE IF NOT EXISTS inv.document_mention_reviews (
    review_id bigserial PRIMARY KEY,
    case_id text NOT NULL,
    mention_id bigint NOT NULL,
    status text NOT NULL CHECK (status IN ('confirmed','rejected')),
    reason text NOT NULL CHECK (length(reason)<=2000),
    reviewed_by text NOT NULL,
    reviewed_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(case_id,mention_id) REFERENCES inv.document_mentions(case_id,mention_id)
);
DROP TRIGGER IF EXISTS immutable_document_mention_reviews ON inv.document_mention_reviews;
CREATE TRIGGER immutable_document_mention_reviews BEFORE UPDATE OR DELETE ON inv.document_mention_reviews
FOR EACH ROW EXECUTE FUNCTION inv.reject_review_mutation();

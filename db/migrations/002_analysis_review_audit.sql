CREATE TABLE IF NOT EXISTS inv.predicted_link_reviews (
    review_id BIGSERIAL PRIMARY KEY,
    case_id TEXT NOT NULL,
    analysis_run_id UUID NOT NULL,
    person_a TEXT NOT NULL,
    person_b TEXT NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('confirmed','dismissed')),
    reason TEXT NOT NULL CHECK (length(reason) <= 2000),
    reviewed_by TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (case_id,analysis_run_id) REFERENCES inv.analysis_runs(case_id,analysis_run_id),
    FOREIGN KEY (analysis_run_id,person_a,person_b,method)
      REFERENCES inv.predicted_links(analysis_run_id,person_a,person_b,method)
);
CREATE OR REPLACE FUNCTION inv.reject_review_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Review audit records are immutable';
END;
$$;
DROP TRIGGER IF EXISTS immutable_predicted_link_reviews ON inv.predicted_link_reviews;
CREATE TRIGGER immutable_predicted_link_reviews BEFORE UPDATE OR DELETE ON inv.predicted_link_reviews
FOR EACH ROW EXECUTE FUNCTION inv.reject_review_mutation();

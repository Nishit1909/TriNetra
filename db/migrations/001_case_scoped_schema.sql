-- 001_case_scoped_schema.sql
-- Case-scoped investigation schema in its own Postgres schema "inv".
-- Non-destructive: the existing public.* tables used by the current app are not touched.
--
-- Rules enforced here (not just by convention):
--   * every row belongs to exactly one case (case_id in every primary key / foreign key)
--   * a child row can only reference a parent in the SAME case (composite foreign keys)
--   * observed records, inferred (derived) records and analysis runs live in separate tables
--   * GPS rows are vehicle evidence: person_id on location_events stays NULL
--   * an analysis result can only point at people of the run's own case

CREATE SCHEMA IF NOT EXISTS inv;
SET search_path = inv;

-- ------------------------------------------------------------------ cases
CREATE TABLE cases (
    case_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT,
    source          TEXT NOT NULL,
    is_synthetic    BOOLEAN NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('investigation', 'benchmark', 'centrality_example')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ observed records
CREATE TABLE persons (
    case_id          TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    person_id        TEXT NOT NULL,
    display_name     TEXT NOT NULL,
    department       TEXT,
    job_title        TEXT,
    source_entity_id TEXT,
    identity_basis   TEXT,                       -- how this identity was established
    PRIMARY KEY (case_id, person_id)
);

CREATE TABLE vehicles (
    case_id          TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    vehicle_id       TEXT NOT NULL,
    source_car_id    TEXT,
    department       TEXT,
    owner_job_title  TEXT,
    source_dataset   TEXT,
    PRIMARY KEY (case_id, vehicle_id)
);

CREATE TABLE vehicle_assignments (
    case_id          TEXT NOT NULL,
    vehicle_id       TEXT NOT NULL,
    person_id        TEXT NOT NULL,
    relationship     TEXT NOT NULL,
    source_dataset   TEXT,
    PRIMARY KEY (case_id, vehicle_id, person_id),
    FOREIGN KEY (case_id, vehicle_id) REFERENCES vehicles(case_id, vehicle_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, person_id)  REFERENCES persons(case_id, person_id)  ON DELETE CASCADE
);

CREATE TABLE locations (
    case_id          TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    location_id      TEXT NOT NULL,
    latitude         DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude        DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    source_dataset   TEXT,
    PRIMARY KEY (case_id, location_id)
);

CREATE TABLE location_events (
    case_id          TEXT NOT NULL,
    event_id         TEXT NOT NULL,
    vehicle_id       TEXT NOT NULL,
    person_id        TEXT,                       -- NULL: vehicle assignment does not prove the driver
    location_id      TEXT NOT NULL,
    observed_at      TIMESTAMP NOT NULL,         -- naive source-local time; timezone unknown
    event_type       TEXT NOT NULL,
    source_dataset   TEXT,
    PRIMARY KEY (case_id, event_id),
    FOREIGN KEY (case_id, vehicle_id)  REFERENCES vehicles(case_id, vehicle_id)   ON DELETE CASCADE,
    FOREIGN KEY (case_id, location_id) REFERENCES locations(case_id, location_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, person_id)   REFERENCES persons(case_id, person_id)     ON DELETE CASCADE
);
CREATE INDEX location_events_vehicle_time ON location_events (case_id, vehicle_id, observed_at);

CREATE TABLE communication_events (
    case_id                 TEXT NOT NULL,
    communication_id        TEXT NOT NULL,
    source_person_id        TEXT NOT NULL,
    target_person_id        TEXT NOT NULL,
    communication_type      TEXT NOT NULL,       -- 'email' in GAStech (headers only, no phone records)
    sent_at                 TIMESTAMP,
    time_known              BOOLEAN NOT NULL,
    timezone                TEXT,
    subject                 TEXT,
    sender_address          TEXT,
    recipient_address       TEXT,
    recipient_count         INTEGER,
    is_broadcast            BOOLEAN NOT NULL,
    source_file             TEXT,
    source_row              INTEGER,
    source_recipient_index  INTEGER,
    header_sha256           TEXT,
    source_dataset          TEXT,
    PRIMARY KEY (case_id, communication_id),
    FOREIGN KEY (case_id, source_person_id) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, target_person_id) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    CHECK (source_person_id <> target_person_id)
);
CREATE INDEX communication_events_pair ON communication_events (case_id, source_person_id, target_person_id);

-- endpoints that could not be resolved to a person (kept for review, never used in analysis)
CREATE TABLE unresolved_communication_endpoints (
    case_id                 TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    communication_id        TEXT NOT NULL,
    source_person_id        TEXT,
    target_person_id        TEXT,
    sender_address          TEXT,
    recipient_address       TEXT,
    sent_at                 TIMESTAMP,
    subject                 TEXT,
    reason                  TEXT NOT NULL,
    source_file             TEXT,
    source_row              INTEGER,
    PRIMARY KEY (case_id, communication_id)
);

CREATE TABLE transactions (
    case_id            TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    transaction_id     TEXT NOT NULL,
    occurred_at        TIMESTAMP NOT NULL,
    merchant_location  TEXT NOT NULL,
    amount             NUMERIC(12, 2) NOT NULL,
    card_last4         TEXT NOT NULL,            -- text: keeps leading zeros; owner unknown
    transaction_type   TEXT,
    source_dataset     TEXT,
    PRIMARY KEY (case_id, transaction_id)
);

CREATE TABLE loyalty_events (
    case_id            TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    loyalty_event_id   TEXT NOT NULL,
    occurred_on        DATE NOT NULL,            -- date only in the source; no time invented
    merchant_location  TEXT NOT NULL,
    amount             NUMERIC(12, 2) NOT NULL,
    loyalty_number     TEXT NOT NULL,
    source_dataset     TEXT,
    PRIMARY KEY (case_id, loyalty_event_id)
);

CREATE TABLE documents (
    case_id            TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    document_id        TEXT NOT NULL,
    document_type      TEXT NOT NULL,
    source_file        TEXT,
    text_file          TEXT,
    source_sha256      TEXT,
    text_sha256        TEXT,
    body               TEXT NOT NULL,
    PRIMARY KEY (case_id, document_id)
);

-- observed person-to-person links for cases that only provide coded ties (Caviar, Noordin),
-- and aggregated email pairs for GAStech. Always traceable to a source table.
CREATE TABLE relationships (
    case_id            TEXT NOT NULL,
    person_a           TEXT NOT NULL,
    person_b           TEXT NOT NULL,
    relationship_type  TEXT NOT NULL,            -- EMAILED, INTERCEPTED_COMMUNICATION, MEETING, ...
    weight             DOUBLE PRECISION NOT NULL DEFAULT 1,
    evidence_count     INTEGER NOT NULL DEFAULT 1,
    source_table       TEXT NOT NULL,
    source_note        TEXT,
    PRIMARY KEY (case_id, person_a, person_b, relationship_type),
    FOREIGN KEY (case_id, person_a) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, person_b) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    CHECK (person_a < person_b)
);

-- ------------------------------------------------------------------ inferred (derived) records
CREATE TABLE vehicle_stops (
    case_id              TEXT NOT NULL,
    stop_id              TEXT NOT NULL,
    vehicle_id           TEXT NOT NULL,
    assigned_person_id   TEXT,                   -- via assignment only; see person_attribution
    person_attribution   TEXT NOT NULL,
    place_id             TEXT,
    latitude             DOUBLE PRECISION,
    longitude            DOUBLE PRECISION,
    stop_start           TIMESTAMP NOT NULL,
    stop_end             TIMESTAMP NOT NULL,
    duration_min         DOUBLE PRECISION NOT NULL,
    last_gps_event_id    TEXT NOT NULL,
    next_gps_event_id    TEXT,
    boundary_distance_m  DOUBLE PRECISION,
    inference_status     TEXT NOT NULL,          -- inferred_stationary | uncertain_gap
    PRIMARY KEY (case_id, stop_id),
    FOREIGN KEY (case_id, vehicle_id) REFERENCES vehicles(case_id, vehicle_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, last_gps_event_id) REFERENCES location_events(case_id, event_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, assigned_person_id) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    CHECK (stop_end > stop_start)
);

CREATE TABLE places (
    case_id                   TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    place_id                  TEXT NOT NULL,
    latitude                  DOUBLE PRECISION NOT NULL,
    longitude                 DOUBLE PRECISION NOT NULL,
    stops                     INTEGER NOT NULL,
    vehicles                  INTEGER NOT NULL,
    place_type                TEXT NOT NULL,
    home_of_assigned_persons  TEXT,
    PRIMARY KEY (case_id, place_id)
);

CREATE TABLE colocation_events (
    case_id             TEXT NOT NULL,
    colocation_id       TEXT NOT NULL,
    vehicle_id_a        TEXT NOT NULL,
    vehicle_id_b        TEXT NOT NULL,
    person_a            TEXT,
    person_b            TEXT,
    person_attribution  TEXT NOT NULL,
    place_id            TEXT NOT NULL,
    place_type          TEXT,
    context             TEXT NOT NULL,
    overlap_start       TIMESTAMP NOT NULL,
    overlap_end         TIMESTAMP NOT NULL,
    overlap_min         DOUBLE PRECISION NOT NULL CHECK (overlap_min >= 10),
    after_hours         BOOLEAN NOT NULL,
    vehicles_present    INTEGER,
    group_gathering     BOOLEAN,
    stop_a              TEXT NOT NULL,
    stop_b              TEXT NOT NULL,
    PRIMARY KEY (case_id, colocation_id),
    FOREIGN KEY (case_id, stop_a) REFERENCES vehicle_stops(case_id, stop_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, stop_b) REFERENCES vehicle_stops(case_id, stop_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, place_id) REFERENCES places(case_id, place_id) ON DELETE CASCADE
);

CREATE TABLE inferred_relationships (
    case_id                         TEXT NOT NULL,
    person_a                        TEXT NOT NULL,
    person_b                        TEXT NOT NULL,
    relationship_type               TEXT NOT NULL,   -- MET_PRIVATELY, SEEN_TOGETHER_IN_PUBLIC, ...
    person_attribution              TEXT NOT NULL,
    lead_strength                   DOUBLE PRECISION NOT NULL CHECK (lead_strength BETWEEN 0 AND 100),
    lead_level                      TEXT NOT NULL,
    factors                         JSONB NOT NULL,  -- private_days, home_visits, chance_p_value, ...
    possible_innocent_explanations  TEXT NOT NULL,
    supporting_colocation_ids       TEXT[] NOT NULL,
    email_ids                       TEXT[] NOT NULL,
    relationship_key                TEXT,
    PRIMARY KEY (case_id, person_a, person_b),
    FOREIGN KEY (case_id, person_a) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, person_b) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    CHECK (person_a <> person_b)
);

CREATE TABLE loyalty_card_links (
    case_id            TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    card_last4         TEXT NOT NULL,
    loyalty_number     TEXT NOT NULL,
    matched_purchases  INTEGER NOT NULL,
    status             TEXT NOT NULL,
    transaction_ids    TEXT[] NOT NULL,
    loyalty_event_ids  TEXT[] NOT NULL,
    PRIMARY KEY (case_id, card_last4)
);

CREATE TABLE document_mentions (
    case_id       TEXT NOT NULL,
    mention_id    BIGSERIAL,
    document_id   TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    matched_text  TEXT NOT NULL,
    start_char    INTEGER NOT NULL,
    end_char      INTEGER NOT NULL CHECK (end_char > start_char),
    context       TEXT,
    method        TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'proposed_needs_review'
                  CHECK (review_status IN ('proposed_needs_review', 'confirmed', 'rejected')),
    PRIMARY KEY (case_id, mention_id),
    FOREIGN KEY (case_id, document_id) REFERENCES documents(case_id, document_id) ON DELETE CASCADE
);

-- ------------------------------------------------------------------ analysis runs and results
CREATE TABLE analysis_runs (
    case_id           TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    analysis_run_id   UUID NOT NULL DEFAULT gen_random_uuid(),
    mode              TEXT NOT NULL CHECK (mode IN ('observed_only', 'observed_plus_inferred')),
    weights_version   TEXT,
    algorithm         TEXT NOT NULL,
    parameters        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status            TEXT NOT NULL CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    error             TEXT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ,
    PRIMARY KEY (analysis_run_id),
    UNIQUE (case_id, analysis_run_id)
);

CREATE TABLE person_metrics (
    case_id            TEXT NOT NULL,
    analysis_run_id    UUID NOT NULL,
    person_id          TEXT NOT NULL,
    degree             DOUBLE PRECISION,
    weighted_degree    DOUBLE PRECISION,
    betweenness        DOUBLE PRECISION,
    pagerank           DOUBLE PRECISION,
    community_id       TEXT,
    hub_flag           BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (analysis_run_id, person_id),
    FOREIGN KEY (case_id, analysis_run_id) REFERENCES analysis_runs(case_id, analysis_run_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, person_id) REFERENCES persons(case_id, person_id) ON DELETE CASCADE
);

CREATE TABLE predicted_links (
    case_id            TEXT NOT NULL,
    analysis_run_id    UUID NOT NULL,
    person_a           TEXT NOT NULL,
    person_b           TEXT NOT NULL,
    method             TEXT NOT NULL,
    score              DOUBLE PRECISION NOT NULL,
    factor_breakdown   JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs      TEXT[] NOT NULL DEFAULT '{}',
    review_status      TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'confirmed', 'dismissed')),
    review_reason      TEXT,
    reviewed_by        TEXT,
    reviewed_at        TIMESTAMPTZ,
    PRIMARY KEY (analysis_run_id, person_a, person_b, method),
    FOREIGN KEY (case_id, analysis_run_id) REFERENCES analysis_runs(case_id, analysis_run_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, person_a) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, person_b) REFERENCES persons(case_id, person_id) ON DELETE CASCADE,
    CHECK (person_a < person_b)
);

-- ------------------------------------------------------------------ convenience view (always filter by case_id)
CREATE VIEW case_graph_edges AS
    SELECT case_id, person_a, person_b, relationship_type, weight, FALSE AS is_inferred, source_table AS evidence_table
    FROM relationships
    UNION ALL
    SELECT case_id, LEAST(person_a, person_b), GREATEST(person_a, person_b), relationship_type,
           lead_strength / 100.0, TRUE, 'inferred_relationships'
    FROM inferred_relationships
    WHERE relationship_type <> 'WORKPLACE_ONLY';

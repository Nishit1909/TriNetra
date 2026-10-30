-- 007: location evidence for uploaded cases (locations.csv -> meetings -> inferred links).
-- GAStech keeps its own vehicle-GPS tables; these tables are for uploads and are independent of vehicles.

CREATE TABLE IF NOT EXISTS inv.location_points (
    case_id      text NOT NULL REFERENCES inv.cases(case_id) ON DELETE CASCADE,
    point_id     text NOT NULL,
    person_id    text NOT NULL,
    observed_at  timestamp without time zone NOT NULL,
    latitude     double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude    double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    place_id     text,
    place_name   text,
    source       text NOT NULL DEFAULT 'gps',
    source_row   integer,
    PRIMARY KEY (case_id, point_id),
    FOREIGN KEY (case_id, person_id) REFERENCES inv.persons(case_id, person_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS location_points_person ON inv.location_points (case_id, person_id, observed_at);

CREATE TABLE IF NOT EXISTS inv.location_meetings (
    case_id         text NOT NULL REFERENCES inv.cases(case_id) ON DELETE CASCADE,
    meeting_id      text NOT NULL,
    person_a        text NOT NULL,
    person_b        text NOT NULL,
    place_id        text NOT NULL,
    place_label     text,
    place_type      text NOT NULL,
    start_at        timestamp without time zone NOT NULL,
    end_at          timestamp without time zone NOT NULL,
    after_hours     boolean NOT NULL,
    people_present  integer NOT NULL,
    low_precision   boolean NOT NULL DEFAULT false,
    point_a         text NOT NULL,
    point_b         text NOT NULL,
    PRIMARY KEY (case_id, meeting_id),
    CHECK (person_a < person_b),
    FOREIGN KEY (case_id, person_a) REFERENCES inv.persons(case_id, person_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, person_b) REFERENCES inv.persons(case_id, person_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS location_meetings_pair ON inv.location_meetings (case_id, person_a, person_b);

-- money transfers between people in an uploaded case (UPI, bank, cash, other)
CREATE TABLE IF NOT EXISTS inv.money_transfers (
    case_id         text NOT NULL REFERENCES inv.cases(case_id) ON DELETE CASCADE,
    transaction_id  text NOT NULL,
    from_person_id  text NOT NULL,
    to_person_id    text NOT NULL,
    amount          numeric(14,2) NOT NULL CHECK (amount > 0),
    occurred_at     timestamp without time zone,
    method          text NOT NULL DEFAULT 'other',
    reference       text,
    source_row      integer,
    PRIMARY KEY (case_id, transaction_id),
    CHECK (from_person_id <> to_person_id),
    FOREIGN KEY (case_id, from_person_id) REFERENCES inv.persons(case_id, person_id) ON DELETE CASCADE,
    FOREIGN KEY (case_id, to_person_id) REFERENCES inv.persons(case_id, person_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS money_transfers_pair ON inv.money_transfers (case_id, from_person_id, to_person_id);

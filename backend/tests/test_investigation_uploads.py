import io
import os
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from app.investigation import analysis, evidence, uploads
from app.investigation import analysis, uploads

PERSONS = "person_id,display_name,department\nP1,Asha Rao,Finance\nP2,Vikram Shetty,Security\nP3,Asha Rao,Ops\nP4,Lone Person,\n"
RELS = "person_a,person_b,relationship_type,weight\nP1,P2,MEETINGS,1\nP2,P1,meetings,1\nP2,P3,FRIENDSHIP,1\n"
COMMS = "source_person_id,target_person_id,sent_at,subject,recipient_count\nP1,P3,2026-01-02 10:00,hi,1\nP3,P1,2026-01-03,re,1\nP2,P4,2026-01-04,all staff,12\n"


def zipped(**files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


# ---------- pure validation (no database)
def test_validation_accepts_good_files_without_merging_people():
    files, notes = uploads.collect_files([("case.zip", zipped(**{"persons.csv": PERSONS, "relationships.csv": RELS, "communications.csv": COMMS}))])
    tables, report = uploads.validate_case_files(files)
    assert report["valid"] and tables is not None
    assert report["counts"]["persons"] == 4                     # same-name P1/P3 kept apart
    assert any("shared by different person IDs" in w for w in report["warnings"])
    assert any("combined" in w for w in report["warnings"])     # P1-P2 meetings rows combined
    assert "COMMUNICATIONS" in report["relationship_types"]
    comm = tables["communications"]
    assert comm.loc[comm.subject == "all staff", "is_broadcast"].item() is True


@pytest.mark.parametrize("persons,rels,needle", [
    ("person_id,display_name\nP1,A\nP1,B\n", "person_a,person_b,relationship_type\nP1,P1,MEETINGS\n", "duplicate person_id"),
    ("person_id,display_name\nP1,A\nP2,B\n", "person_a,person_b,relationship_type\nP1,P9,MEETINGS\n", "not in persons.csv"),
    ("person_id,display_name\nP1,A\nP2,B\n", "person_a,person_b,relationship_type\nP1,P1,MEETINGS\n", "themselves"),
    ("person_id,display_name\nP1,A\nP2,B\n", "person_a,person_b,relationship_type,weight\nP1,P2,MEETINGS,-3\n", "weight must be"),
    ("person_id,display_name\nP 1,A\nP2,B\n", "person_a,person_b,relationship_type\nP2,P 1,MEETINGS\n", "person_id must be"),
    ("id,name\nP1,A\n", "person_a,person_b,relationship_type\nP1,P2,MEETINGS\n", "missing column"),
])
def test_validation_rejects_bad_files(persons, rels, needle):
    tables, report = uploads.validate_case_files({"persons": persons.encode(), "relationships": rels.encode(),
                                                  "communications": b"source_person_id,target_person_id\nP1,P2\n"})
    assert tables is None and not report["valid"]
    assert any(needle in e for e in report["errors"]), report["errors"]


def test_missing_required_file_and_zip_limits():
    _, report = uploads.validate_case_files({"persons": PERSONS.encode()})
    assert any("relationships.csv is required" in e for e in report["errors"])
    assert any("communications.csv is required" in e for e in report["errors"])
    too_many = zipped(**{f"f{i}.csv": "a\n1\n" for i in range(uploads.MAX_FILES_IN_ZIP + 1)})
    with pytest.raises(Exception) as exc:
        uploads.collect_files([("x.zip", too_many)])
    assert getattr(exc.value, "status_code", None) == 422
    with pytest.raises(Exception) as exc:
        uploads.collect_files([("x.zip", b"not a zip")])
    assert exc.value.status_code == 422


# ---------- API against a disposable database
pytestmark_db = pytest.mark.skipif(not os.getenv("INV_TEST_DSN"), reason="needs disposable INV_TEST_DSN")


@pytest.fixture
def client(monkeypatch):
    dsn = os.environ["INV_TEST_DSN"]
    connect = lambda: psycopg.connect(dsn, row_factory=dict_row)
    monkeypatch.setattr(uploads, "connect", connect)
    monkeypatch.setattr(analysis, "connect", connect)
    monkeypatch.setattr(evidence, "connect", connect)
    created = []
    app = FastAPI()
    who = {"admin": True}

    def principal():
        return SimpleNamespace(local=True, is_admin=who["admin"], user_id="local")
    app.dependency_overrides[uploads.get_principal] = principal
    app.include_router(uploads.router)
    app.include_router(analysis.router)
    app.include_router(evidence.router)
    with TestClient(app) as c:
        yield c, created, who, connect
    with connect() as conn:
        for cid in created:
            conn.execute("DELETE FROM inv.cases WHERE case_id=%s", (cid,))


@pytestmark_db
def test_upload_creates_new_isolated_case_and_analysis_runs(client):
    c, created, who, connect = client
    with connect() as conn:
        before = conn.execute("SELECT count(*) n FROM inv.cases").fetchone()["n"]
    r = c.post("/api/case-uploads/validate", files={"file": ("case.zip", zipped(**{"persons.csv": PERSONS, "relationships.csv": RELS, "communications.csv": COMMS}))})
    assert r.status_code == 200 and r.json()["valid"]
    with connect() as conn:
        assert conn.execute("SELECT count(*) n FROM inv.cases").fetchone()["n"] == before     # dry run wrote nothing

    r = c.post("/api/case-uploads", data={"name": "Test upload " + uuid4().hex[:4]},
               files={"persons": ("p.csv", PERSONS), "relationships": ("r.csv", RELS), "communications": ("c.csv", COMMS)})
    assert r.status_code == 200, r.text
    case_id = r.json()["case_id"]; created.append(case_id)
    assert case_id.startswith("CASE_UPLOAD_")
    with connect() as conn:
        assert conn.execute("SELECT count(*) n FROM inv.persons WHERE case_id=%s", (case_id,)).fetchone()["n"] == 4
        assert conn.execute("SELECT count(*) n FROM inv.communication_events WHERE case_id=%s AND is_broadcast", (case_id,)).fetchone()["n"] == 1
    run = c.post(f"/api/cases/{case_id}/analysis", json={"mode": "observed_only"}).json()
    assert run["run"]["status"] == "completed", run["run"]
    assert len(run["person_metrics"]) == 4

    # Bad upload: 422 with a report, and nothing written.
    with connect() as conn:
        before = conn.execute("SELECT count(*) n FROM inv.cases").fetchone()["n"]
    bad = c.post("/api/case-uploads", data={"name": "Bad upload"},
                 files={"persons": ("p.csv", "person_id,display_name\nP1,A\nP1,B\n"), "relationships": ("r.csv", RELS)})
    assert bad.status_code == 422 and "nothing was saved" in bad.text
    with connect() as conn:
        assert conn.execute("SELECT count(*) n FROM inv.cases").fetchone()["n"] == before

    who["admin"] = False
    assert c.post("/api/case-uploads", data={"name": "Nope"}, files={"persons": ("p.csv", PERSONS), "relationships": ("r.csv", RELS)}).status_code == 403
    assert c.get("/api/case-uploads/template").status_code == 200


LOCS = """person_id,observed_at,latitude,longitude,place_name,source
P1,2026-01-05 22:10,12.30000,76.60000,Lakeview Lodge,gps
P4,2026-01-05 22:20,12.30020,76.60010,,gps
P1,2026-01-06 23:00,12.30000,76.60000,Lakeview Lodge,gps
P4,2026-01-06 23:15,12.30010,76.60000,,cell_tower
P2,2026-01-05 10:00,12.40000,76.70000,Office,gps
P3,2026-01-05 10:05,12.40000,76.70000,Office,gps
"""
TX = """from_person_id,to_person_id,amount,occurred_at,method,reference
P1,P4,"45,000",2026-01-07 11:00,upi,consultancy
P4,P1,1200.50,,cash,
"""


def test_locations_and_transactions_become_inferred_and_finance_ties():
    tables, report = uploads.validate_case_files({"persons": PERSONS.encode(), "relationships": RELS.encode(),
                                                  "communications": COMMS.encode(), "locations": LOCS.encode(),
                                                  "transactions": TX.encode()})
    assert report["valid"], report["errors"]
    c = report["counts"]
    assert c["locations"] == 6 and c["transactions"] == 2 and c["meetings"] >= 3
    inferred = {(r["person_a"], r["person_b"]): r for r in tables["locations"]["inferred"]}
    met = inferred[("P1", "P4")]
    assert met["relationship_type"] == "MET_PRIVATELY" and met["factors"]["private_days"] == 2
    assert met["factors"]["after_hours_private"] == 2 and met["lead_strength"] > 0
    assert "presence, not interaction" in met["innocent"]
    assert "BUSINESS&FINANCE" in report["relationship_types"]
    assert tables["transactions"].amount.tolist() == [45000.0, 1200.5]


def test_bad_location_and_transaction_rows_are_rejected():
    _, report = uploads.validate_case_files({"persons": PERSONS.encode(), "relationships": RELS.encode(), "communications": COMMS.encode(),
                                             "locations": b"person_id,observed_at,latitude,longitude\nP1,yesterday,12,76\nP9,2026-01-01,12,76\nP1,2026-01-01,200,76\n",
                                             "transactions": b"from_person_id,to_person_id,amount\nP1,P1,10\nP1,P2,-5\n"})
    errs = " | ".join(report["errors"])
    assert "not a date/time" in errs and "not in persons.csv" in errs and "latitude/longitude" in errs
    assert "same person" in errs and "positive number" in errs


def test_upload_with_locations_shows_meetings_in_pair_evidence(client):
    c, created, who, connect = client
    r = c.post("/api/case-uploads", data={"name": "Loc upload " + uuid4().hex[:4]},
               files={"persons": ("p.csv", PERSONS), "relationships": ("r.csv", RELS), "communications": ("c.csv", COMMS),
                      "locations": ("l.csv", LOCS), "transactions": ("t.csv", TX)})
    assert r.status_code == 200, r.text
    case_id = r.json()["case_id"]; created.append(case_id)
    summary = c.get(f"/api/cases/{case_id}/summary").json()
    assert summary["counts"]["colocation_events"] >= 3 and summary["counts"]["transactions"] == 2
    run = c.post(f"/api/cases/{case_id}/analysis", json={"mode": "observed_plus_inferred"}).json()
    assert run["run"]["status"] == "completed", run["run"]
    body = c.get(f"/api/cases/{case_id}/relationships/P1/P4").json()
    assert body["colocation_events"]["total"] >= 2 and body["colocation_events"]["items"][0]["source"] == "location"
    assert body["transfers"]["total"] == 2 and body["uncertainty"]["person_attribution"] == "uploaded_location_as_given"

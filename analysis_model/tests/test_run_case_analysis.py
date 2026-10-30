import importlib
import json
from pathlib import Path

import pandas as pd
import pytest

from analysis_model import LINK_COLUMNS, METRIC_COLUMNS, STAGES, run_case_analysis

rca = importlib.import_module("analysis_model.run_case_analysis")  # the module (the package re-exports the function)

W = json.loads((Path(__file__).resolve().parents[1] / "weights" / "v1_2.json").read_text())


def tiny():
    persons = pd.DataFrame({"person_id": ["A", "B", "C", "D", "E"], "department": ["X", "X", "Y", "Y", "Z"]})
    edges = pd.DataFrame([
        ("A", "B", "EMAILED", False, 1.0, {"email_events": 3, "direct_email_events": 3}, None),
        ("B", "C", "EMAILED", False, 1.0, {"email_events": 2, "direct_email_events": 2}, None),
        ("C", "D", "EMAILED", False, 1.0, {"email_events": 4, "direct_email_events": 0}, None),   # broadcast only
        ("A", "D", "MET_PRIVATELY", True, 0.6,
         {"private_days": 3, "private_meetings": 3, "after_hours_private": 3, "home_visits": 1, "chance_p_value": 0.07}, "CO1;CO2"),
    ], columns=["person_a", "person_b", "relationship_type", "is_inferred", "weight", "factors", "evidence_refs"])
    return persons, edges


def test_contract_shape_and_ok_status():
    p, e = tiny()
    r = run_case_analysis(p, e, "observed_plus_inferred", W)
    assert r["status"] == "ok" and set(r["stages"]) == set(STAGES)
    assert all(s["status"] == "ok" for s in r["stages"].values())
    assert list(r["person_metrics"].columns) == METRIC_COLUMNS and len(r["person_metrics"]) == 5
    assert list(r["predicted_links"].columns) == LINK_COLUMNS
    assert r["weights_version"] == "v1.2" and r["mode"] == "observed_plus_inferred"


def test_observed_only_ignores_inferred_edges():
    p, e = tiny()
    r = run_case_analysis(p, e, "observed_only", W)
    assert r["status"] == "ok"
    assert r["stages"]["validate_input"]["rows"] == 3
    assert not (r["predicted_links"].method == "tie_without_recorded_communication").any()   # only an inferred non-communication tie exists


def test_meet_but_never_communicate_lead_with_breakdown_and_evidence():
    p, e = tiny()
    pl = run_case_analysis(p, e, "observed_plus_inferred", W)["predicted_links"]
    lead = pl[pl.method == "tie_without_recorded_communication"]
    assert list(zip(lead.person_a, lead.person_b)) == [("A", "D")]
    row = lead.iloc[0]
    assert row.score > 0 and "home visit" in row.factor_breakdown and row.evidence_refs == ["CO1", "CO2"]
    assert row.factor_breakdown["basis"] == "inferred"


def test_observed_noncommunication_tie_without_communication_is_a_lead():
    # Noordin-style: an observed MEETINGS tie between people with no recorded communication
    p = pd.DataFrame({"person_id": ["A", "B", "C"]})
    e = pd.DataFrame([("A", "B", "MEETINGS", False, 1.0, None, None), ("B", "C", "MEETINGS", False, 1.0, None, None),
                      ("B", "C", "COMMUNICATIONS", False, 1.0, None, None)],
                     columns=["person_a", "person_b", "relationship_type", "is_inferred", "weight", "factors", "evidence_refs"])
    pl = run_case_analysis(p, e, "observed_only", W)["predicted_links"]
    lead = pl[pl.method == "tie_without_recorded_communication"]
    assert list(zip(lead.person_a, lead.person_b)) == [("A", "B")]      # B-C already communicate
    assert lead.iloc[0].factor_breakdown["basis"] == "observed"


def test_broadcast_only_email_is_not_a_relationship():
    p, e = tiny()
    r = run_case_analysis(p, e, "observed_only", W)
    m = r["person_metrics"].set_index("person_id")
    assert m.loc["D", "degree"] == 0          # C-D linked only by broadcasts
    assert any("zero strength" in x for x in r["warnings"])


def test_failed_stage_is_reported_not_hidden(monkeypatch):
    p, e = tiny()
    monkeypatch.setattr(rca, "_communities", lambda G, w: (_ for _ in ()).throw(RuntimeError("boom")))
    r = run_case_analysis(p, e, "observed_plus_inferred", W)
    assert r["status"] == "partial"
    assert r["stages"]["communities"]["status"] == "failed" and "boom" in r["stages"]["communities"]["error"]
    assert r["person_metrics"].community_id.isna().all()      # missing, not fabricated
    assert r["stages"]["centrality"]["status"] == "ok"


def test_link_prediction_failure_is_not_no_findings(monkeypatch):
    p, e = tiny()
    monkeypatch.setattr(rca, "_link_prediction", lambda *a: (_ for _ in ()).throw(ValueError("bad")))
    r = run_case_analysis(p, e, "observed_plus_inferred", W)
    assert r["status"] == "partial" and r["stages"]["link_prediction"]["status"] == "failed"
    assert r["stages"]["link_prediction"]["rows"] is None   # vs ok + 0 rows = genuinely no findings


def test_unknown_person_fails_validation():
    p, e = tiny()
    e.loc[len(e)] = ("A", "Z9", "EMAILED", False, 1.0, None, None)
    r = run_case_analysis(p, e, "observed_only", W)
    assert r["status"] == "failed" and r["stages"]["validate_input"]["status"] == "failed"
    assert "unknown persons" in r["stages"]["validate_input"]["error"]
    assert all(r["stages"][s]["status"] == "skipped" for s in STAGES[1:])


@pytest.mark.parametrize("bad", [{"mode": "everything"}, {"weights": {}}])
def test_bad_mode_or_weights_fail(bad):
    p, e = tiny()
    r = run_case_analysis(p, e, bad.get("mode", "observed_only"), bad.get("weights", W))
    assert r["status"] == "failed"


def test_empty_case_is_ok_with_no_findings():
    p = pd.DataFrame({"person_id": ["A", "B"]})
    r = run_case_analysis(p, pd.DataFrame(), "observed_plus_inferred", W)
    assert r["status"] == "ok" and r["predicted_links"].empty and r["stages"]["link_prediction"]["rows"] == 0


def test_deterministic():
    p, e = tiny()
    a = run_case_analysis(p, e, "observed_plus_inferred", W)
    b = run_case_analysis(p, e, "observed_plus_inferred", W)
    pd.testing.assert_frame_equal(a["person_metrics"], b["person_metrics"])
    pd.testing.assert_frame_equal(a["predicted_links"], b["predicted_links"])


def test_hub_is_flagged_not_dropped():
    ids = [f"P{i:02d}" for i in range(30)]
    p = pd.DataFrame({"person_id": ids})
    rows = [("P00", x, "EMAILED", False, 1.0, None, None) for x in ids[1:]]
    rows += [(ids[i], ids[i + 1], "EMAILED", False, 1.0, None, None) for i in range(1, 29, 2)]
    e = pd.DataFrame(rows, columns=["person_a", "person_b", "relationship_type", "is_inferred", "weight", "factors", "evidence_refs"])
    r = run_case_analysis(p, e, "observed_only", W)
    m = r["person_metrics"].set_index("person_id")
    assert bool(m.loc["P00", "hub_flag"]) and len(m) == 30


def _path4():
    p = pd.DataFrame({"person_id": ["A", "B", "C", "D"]})
    e = pd.DataFrame([("A", "B", "EMAILED", False, 1.0, None, None), ("B", "C", "EMAILED", False, 1.0, None, None),
                      ("C", "D", "EMAILED", False, 1.0, None, None)],
                     columns=["person_a", "person_b", "relationship_type", "is_inferred", "weight", "factors", "evidence_refs"])
    return p, e


def test_learned_ranker_suggests_unconnected_pairs_with_explanations():
    p, e = _path4()
    r = run_case_analysis(p, e, "observed_only", W)
    pl = r["predicted_links"]
    bl = pl[pl.method == "hidden_link_ranker"]
    assert set(zip(bl.person_a, bl.person_b)) == {("A", "C"), ("B", "D"), ("A", "D")}
    assert bl.score.is_monotonic_decreasing
    bd = bl.factor_breakdown.iloc[0]
    assert {"shared contacts", "network proximity (percentile)", "learned ranker (percentile)", "same group"} <= set(bd)
    assert not any("unavailable" in x for x in r["warnings"])


def _fresh(monkeypatch):
    monkeypatch.setattr(rca, "_RANKER_CACHE", {})


def test_missing_model_falls_back_to_ppr_with_warning(monkeypatch):
    _fresh(monkeypatch)
    p, e = _path4()
    w = json.loads(json.dumps(W)); w["link_prediction"]["ranker_model"] = "does_not_exist"
    r = run_case_analysis(p, e, "observed_only", w)
    assert r["status"] == "ok"
    pl = r["predicted_links"]
    pr = pl[pl.method == "network_proximity_ppr"]
    assert set(zip(pr.person_a[:2], pr.person_b[:2])) == {("A", "C"), ("B", "D")}   # 2 steps apart before 3 steps
    assert any("fell back to personalised PageRank" in x for x in r["warnings"])


def test_tampered_model_is_rejected(monkeypatch, tmp_path):
    _fresh(monkeypatch)
    import shutil
    for ext in ("trees.json", "json"):
        shutil.copy(rca.MODELS_DIR / f"link_ranker_gbm_v1.{ext}", tmp_path / f"link_ranker_gbm_v1.{ext}")
    with open(tmp_path / "link_ranker_gbm_v1.trees.json", "ab") as fh:
        fh.write(b"tamper")
    monkeypatch.setattr(rca, "MODELS_DIR", tmp_path)
    p, e = _path4()
    r = run_case_analysis(p, e, "observed_only", W)
    assert any("checksum" in x for x in r["warnings"])
    assert (r["predicted_links"].method == "network_proximity_ppr").any()


@pytest.mark.parametrize("mode,method", [("blend", "hidden_link_ranker_blend"), ("ppr", "network_proximity_ppr")])
def test_ranker_modes(monkeypatch, mode, method):
    _fresh(monkeypatch)
    p, e = _path4()
    w = json.loads(json.dumps(W)); w["link_prediction"]["ranker_mode"] = mode
    pl = run_case_analysis(p, e, "observed_only", w)["predicted_links"]
    assert set(pl.method) == {method}

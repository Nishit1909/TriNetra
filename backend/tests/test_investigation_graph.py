import pytest
from fastapi import HTTPException

from app.investigation.graph import compact_graph
from app.investigation import graph


def sample():
    nodes = [{"id":pid,"label":pid,"department":None} for pid in "ABCDE"]
    edges = [dict(source=a,target=b,kind=kind,type="T",weight=w) for a,b,kind,w in
             [("A","B","observed",2),("B","C","inferred",5),("C","D","observed",3),
              ("A","E","predicted",1),("A","D","observed",0),("A","UNKNOWN","observed",99)]]
    return nodes,edges


def test_compact_filters_limits_and_no_dangling_edges():
    nodes,edges = sample()
    out = compact_graph(nodes,edges,{},set(["observed","inferred","predicted"]),"observed_only",3,1,None)
    assert out["counts"] == {"total_nodes":5,"total_edges":3,"shown_nodes":3,"shown_edges":1}
    assert out["truncated"]
    assert all(e["kind"] != "inferred" and e["weight"] > 0 for e in out["edges"])
    assert all(e["source"] in {n["id"] for n in out["nodes"]} and e["target"] in {n["id"] for n in out["nodes"]} for e in out["edges"])
    assert out == compact_graph(nodes[::-1],edges[::-1],{},set(["observed","inferred","predicted"]),"observed_only",3,1,None)


def test_run_ranking_focus_and_counts():
    nodes,edges = sample()
    metrics = {"E":{"pagerank":0.9},"A":{"pagerank":0.1}}
    out = compact_graph(nodes,edges,metrics,{"observed","inferred"},"observed_plus_inferred",2,10,"C")
    assert out["nodes"][0]["id"] == "C"
    assert len(out["nodes"]) == 2
    larger = compact_graph(nodes,edges,metrics,{"observed","inferred"},"observed_plus_inferred",4,10,"C")
    assert {n["id"] for n in out["nodes"]} <= {n["id"] for n in larger["nodes"]}
    assert larger["counts"]["total_edges"] == 3
    with pytest.raises(HTTPException) as exc:
        compact_graph(nodes,edges,{}, {"observed"},"observed_only",2,10,"UNKNOWN")
    assert exc.value.status_code == 404


def test_pagerank_is_used_instead_of_display_degree():
    nodes,edges = sample()
    out = compact_graph(nodes,edges,{pid:{"pagerank":rank} for pid,rank in zip("ABCDE",[0.1,0.2,0.3,0.15,0.25])},
                        {"observed"},"observed_only",1,10,None)
    assert out["nodes"][0]["id"] == "C"


def test_neo_queries_bind_case_and_active_snapshot_on_both_endpoints(monkeypatch):
    calls = []
    class Rows(list):
        def single(self):
            return self[0]
    class Session:
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def run(self,query,**params):
            calls.append((query,params))
            if "active_snapshot_id" in query:
                return Rows([{"snapshot_id":"ACTIVE"}])
            if "INV_LINK" in query:
                return Rows([{"id":"E","source":"A","target":"B","kind":"inferred",
                              "is_inferred":True,"type":"MET_PRIVATELY","weight":0.5,
                              "attributes_json":'{"lead_strength":50}'}])
            return Rows([{"id":"A","label":"Alice","department":None},
                         {"id":"B","label":"Bob","department":None}])
    class Driver:
        def session(self,**kwargs):
            return Session()
    monkeypatch.setattr(graph,"get_driver",lambda:Driver())
    nodes,edges = graph.neo_graph("CASE")
    assert len(nodes) == 2 and edges[0]["lead_strength"] == 50
    edge_query,params = next(call for call in calls if "INV_LINK" in call[0])
    assert params == {"case_id":"CASE","snapshot_id":"ACTIVE"}
    assert edge_query.count("case_id:$case_id,snapshot_id:$snapshot_id") == 3

"""Does plain centrality surface Caviar subject X1 (principal organiser per Morselli 2009)? Usage: python scripts/caviar_check.py cases/caviar"""
import sys, json
from pathlib import Path
import networkx as nx, pandas as pd
d = Path(sys.argv[1]); e = pd.read_csv(d / "communication_links.csv"); out = {}
for ph in ["start", "middle", "end", "all"]:
    s = e if ph == "all" else e[e.phase == ph]
    G = nx.Graph()
    for r in s.itertuples():
        w = G.get_edge_data(r.person_a, r.person_b, {"weight": 0})["weight"]
        G.add_edge(r.person_a, r.person_b, weight=w + r.intercept_count)
    m = {"pagerank": nx.pagerank(G, weight="weight"), "betweenness": nx.betweenness_centrality(G), "degree": dict(G.degree())}
    out[ph] = {"nodes": G.number_of_nodes(), **{k: sorted(v, key=v.get, reverse=True).index("CV_X1") + 1 for k, v in m.items()}}
    print(ph, out[ph])
(d / "centrality_check.json").write_text(json.dumps({"subject": "CV_X1", "rank_of_subject": out}, indent=1))

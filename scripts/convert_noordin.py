"""Convert the Noordin Top network (networkdata::covert_34, R/igraph format) into a case folder.

Usage: python scripts/convert_noordin.py cases/noordin/source/covert_34.rda cases/noordin
Requires: pip install rdata pandas numpy   (no R needed)

Writes persons.csv, relationships.csv (one row per undirected pair per layer) and
validation_report.json. IDs are NR_01..NR_79 in the source vertex order; the original names
are kept as display names. Identities are separate from every other case.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rdata

SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])
CASE = "CASE_NOORDIN"


def py(x):
    t = x.info.type.name
    if t in ("REAL", "INT", "LGL"):
        return np.asarray(x.value)
    if t == "STR":
        return [s.value.decode() if s.value is not None else None for s in x.value]
    if t == "VEC":
        return [py(e) for e in x.value]
    return t


parsed = rdata.parser.parse_file(str(SRC))
graphs = parsed.object.value[0].value          # list of igraph objects, one per layer
layers, names, report = {}, None, {"layers": {}, "issues": []}
for g in graphs:
    el = g.value
    n = int(py(el[0])[0])
    directed = bool(py(el[1])[0])
    frm, to = py(el[2]).astype(int), py(el[3]).astype(int)   # igraph stores 0-based endpoints
    attrs = py(el[8])                                          # [version, graph attrs, vertex attrs, edge attrs]
    layer = attrs[1][0][0].replace("NOORDINTOP_", "").lower()
    vnames = attrs[2][0]
    if names is None:
        names = vnames
    if vnames != names:
        report["issues"].append(f"{layer}: vertex order differs from first layer")
    if directed:
        report["issues"].append(f"{layer}: directed graph (expected undirected)")
    self_loops = int((frm == to).sum())
    pairs = {tuple(sorted((int(a), int(b)))) for a, b in zip(frm, to) if a != b}
    dup = len(frm) - self_loops - len(pairs)
    layers[layer] = pairs
    report["layers"][layer] = {"nodes": n, "edges_raw": int(len(frm)), "undirected_pairs": len(pairs),
                               "self_loops_removed": self_loops, "duplicate_rows_collapsed": int(dup)}

pid = [f"NR_{i + 1:02d}" for i in range(len(names))]
persons = pd.DataFrame({"person_id": pid, "case_id": CASE, "display_name": names,
                        "source_vertex_index": range(len(names))})
rows = []
for layer, pairs in sorted(layers.items()):
    for a, b in sorted(pairs):
        rows.append({"case_id": CASE, "person_a": pid[a], "person_b": pid[b], "layer": layer,
                     "is_label_layer": layer == "communications"})
rel = pd.DataFrame(rows)

OUT.mkdir(parents=True, exist_ok=True)
persons.to_csv(OUT / "persons.csv", index=False)
rel.to_csv(OUT / "relationships.csv", index=False)

deg_any = pd.concat([rel.person_a, rel.person_b]).value_counts()
report.update({
    "case_id": CASE,
    "source_file": SRC.name,
    "source_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
    "persons": len(persons),
    "duplicate_display_names": int(persons.display_name.duplicated().sum()),
    "missing_display_names": int(persons.display_name.isna().sum()),
    "persons_with_no_tie_in_any_layer": int(len(set(pid) - set(deg_any.index))),
    "persons_with_no_communication_tie": int(len(set(pid) - set(pd.concat([rel[rel.layer == "communications"].person_a,
                                                                          rel[rel.layer == "communications"].person_b])))),
    "relationship_rows": len(rel),
    "all_pairs": len(pid) * (len(pid) - 1) // 2,
    "missing_values_note": "The source has no missing-value marker: an absent tie means 'not recorded in the coded "
                           "sources', not a confirmed non-relationship.",
})
(OUT / "validation_report.json").write_text(json.dumps(report, indent=1))
print(json.dumps({k: v for k, v in report.items() if k != "layers"}, indent=1))
print(pd.DataFrame(report["layers"]).T.to_string())

# Operation Caviar (validation case)

A real drug-trafficking network investigated in Montreal (1994–1996), reconstructed from police wiretap evidence by Morselli (2009). Taken from the `onadata` R package (`caviar_start`, `caviar_middle`, `caviar_end`), which bundles three snapshots of the investigation.

| File | What it is |
|---|---|
| `communication_links.csv` | 148 phase edges: `person_a`, `person_b`, `phase`, `intercept_count` (intercepted communications) |
| `graph_edges.csv` | 88 undirected pairs, all phases merged, weight = total intercepts |
| `persons.csv` | 62 anonymised subjects (`CV_Xn`) |
| `centrality_check.json` | Output of `scripts/caviar_check.py` |

**Why it's here:** it's the only case with a known answer about who is central. Plain centrality ranks subject X1 #1 on PageRank, betweenness and degree in the start and middle snapshots and on all phases combined, and #2 on betweenness in the end snapshot (after seizures disrupted the network). Morselli describes X1 as the principal organiser; check the book before quoting this.

This validates network analytics on a real criminal network. It says nothing about predicting criminality.

Sources: Morselli, C. (2009). *Inside Criminal Networks*. Springer. https://doi.org/10.1007/978-0-387-09526-4 · McNulty, K., onadata R package, https://github.com/keithmcnulty/onadata

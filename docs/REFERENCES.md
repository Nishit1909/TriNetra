# References

| Dataset | Used for | Real / synthetic |
|---|---|---|
| VAST Challenge 2021 MC1 + MC2 (re-release of 2014 GAStech scenario) | The validated case and the derived layer | Synthetic scenario |
| Operation Caviar (Morselli 2009) via onadata | `cases/caviar`, centrality validation | Real criminal network |
| Elliptic Bitcoin dataset | Only the existing backend risk model (not in this repo) | Real, anonymised transactions |

1. VAST Challenge 2021, Mini-Challenge 1 and 2. https://vast-challenge.github.io/2021/MC1.html · https://vast-challenge.github.io/2021/MC2.html
2. VAST Challenge 2014, MC1 "Disappearance at GASTech". https://vast.cs.umass.edu/VAST%20Challenge%202014/challenges/MC1%20-%20Disappearance%20at%20GASTech
3. Cook, K., Grinstein, G., & Whiting, M. (2014). The VAST Challenge: history, scope, and outcomes. *Information Visualization*, 13(4), 301–312.
4. Morselli, C. (2009). *Inside Criminal Networks*. Springer. https://doi.org/10.1007/978-0-387-09526-4
5. McNulty, K. (2022). *Handbook of Graphs and Networks in People Analytics*. CRC Press. Data: onadata R package, https://github.com/keithmcnulty/onadata
6. Weber, M., et al. (2019). Anti-Money Laundering in Bitcoin: Experimenting with Graph Convolutional Networks for Financial Forensics. *KDD '19 Workshop on Anomaly Detection in Finance*.
7. Derived evidence: SIH26189 pipeline, `scripts/derive_evidence.py`.

Check years, pages and author lists for 3, 5 and 6 against the publishers before submitting. Enron, Indian Kanoon, GeoLife, Noordin Top, Facebook Social Circles, IBM AML and PaySim are **not** used here; don't claim them.

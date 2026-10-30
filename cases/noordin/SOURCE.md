# Noordin Top network (separate benchmark case)

`CASE_NOORDIN`, a real covert network used **only** for the link-recovery benchmark. Its identities (`NR_01`–`NR_79`) are completely separate from GAStech and Caviar, and no model trained here is applied to another case.

## Source
- **Original coding:** Roberts, N. & Everton, S. F. (2011). *Roberts and Everton Terrorist Data: Noordin Top Terrorist Network (Subset).* Coded mainly from International Crisis Group (2006), *Terrorism in Indonesia: Noordin's Networks*, Appendix C (79 individuals). Coded by Naval Postgraduate School students (CORE Lab), cleaned by D. Cunningham.
- **File used:** `source/covert_34.rda` from the `networkdata` R package (v0.2.4, MIT licence, https://github.com/schochastics/networkdata, commit `521594049f725c3962c11496d5b0f48386ee84b2`). SHA-256 `2b28737e5d0088bfe28478b0aed574682fc75b6a4d0c3c2f90a06367a3cda19f`.
- **Further reading:** Everton, S. F. (2012). *Disrupting Dark Networks.* Cambridge University Press.

## Contents (from `validation_report.json`)
79 people, 10 undirected layers, no self-loops, no duplicate rows, consistent vertex order across layers.

| Layer | Pairs |
|---|---:|
| operations | 267 |
| communications (**label only**) | 200 |
| classmates | 175 |
| trainingevents | 147 |
| friendship | 91 |
| meetings | 63 |
| logistics | 29 |
| kinship | 16 |
| business&finance | 15 |
| soulmates | 11 |

- 1 person has no recorded tie in any layer; 5 have no communication tie.
- The package documentation lists nine tie types but the file contains a tenth, **kinship**. It's used as found.
- **Missing values:** the source has no "unknown" marker. An absent tie means "not recorded in the coded sources", **not** a confirmed non-relationship.

## Files
| File | What it is |
|---|---|
| `persons.csv` | `NR_xx` ID, original name, source vertex index |
| `relationships.csv` | One row per pair per layer; `is_label_layer` marks communications |
| `validation_report.json` | Counts, checks, source hash |

Rebuild: `python scripts/convert_noordin.py cases/noordin/source/covert_34.rda cases/noordin` (needs `pip install rdata`; no R required).

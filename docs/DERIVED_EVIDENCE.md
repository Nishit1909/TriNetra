# Derived evidence layer

The validated case (`datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip`) is the raw evidence. `derived/` is a separate layer of **conclusions drawn from it**. Every conclusion points back to case rows, and nothing in the case is changed.

Rebuild and check:

```
unzip datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip -d /tmp/case
python scripts/derive_evidence.py /tmp/case derived      # ~15 s
python scripts/validate_derived.py /tmp/case derived     # 23/23 checks
python scripts/caviar_check.py cases/caviar
```

Requires Python 3.10+, pandas, numpy, scikit-learn and networkx (the last only for the Caviar check).

## Rules the layer follows

1. **GPS is vehicle evidence.** Stops and co-location are computed per vehicle. A person is attached only through `vehicle_assignments.csv`, and every such row says `person_attribution = assigned_driver_assumed`. The UI should say "X's assigned car was…", not "X was…".
2. **Quarantined email endpoints are not used.** The 111 rows involving the unresolved CEO alias address stay out of every count.
3. **Leads, not accusations.** Pairs get a `lead_strength` (0–100), a `lead_level`, a chance comparison and a list of `possible_innocent_explanations`. An investigator decides.

## Files

| File | Rows | What it is | Points back to |
|---|---:|---|---|
| `vehicle_stops.csv` | 3,068 | A car parked for at least 5 min (VAST GPS logs only while moving) | `last_gps_event_id` → `location_events.csv` |
| `places.csv` | 98 | Stops clustered within 50 m: workplace (1), homes (26), busy public (10+ cars), other | stops |
| `colocation_events.csv` | 13,488 | Two cars parked at the same place at the same time for at least 10 min; context, after-hours flag, number of cars present | `stop_a`, `stop_b` |
| `colocation_relationships.csv` | 564 pairs | Per pair: private meeting days, home visits, group gatherings, chance baseline, direct emails, lead strength and level, innocent explanations | colocation ids, communication ids |
| `card_owner_inference.csv` + `card_owner_evidence.csv` | 55 cards (19 inferred) | Card → vehicle (→ assigned person, assumed) | purchase ids, stop ids |
| `loyalty_card_links.csv` | 53 linked | Loyalty card ↔ payment card: same day, shop and amount at least 3 times. No driver assumption | purchase ids, loyalty ids |
| `document_mentions.csv` | 3,002 | Exact-name person and organisation mentions with character offsets, all `proposed_needs_review` | `text_file` + offsets |
| `derived_graph_edges.csv` | 575 | Inferred edges for the graph overlay (`is_inferred = true`); `WORKPLACE_ONLY` pairs left out | the tables above |

## How false alarms are reduced

| Step | Effect on this data |
|---|---|
| A private meeting needs 10+ min of overlap at a non-office, non-busy place | 13,488 co-location events → 385 private events |
| Neighbours and co-residents are separated (`both_live_here`) | Not counted as meetings |
| A lead needs **2 or more separate days** | "Meets privately, no direct email": 104 pairs → 26 |
| **Chance baseline:** one car's days are shifted by 1–13 days and meetings recounted; `chance_p_value` = share of shifts that match or beat the real count | A pattern that happens every night (a routine) scores high p; a rare repeated meeting scores low p |
| **Group gatherings** (3+ cars present) and lunch-hour routines are penalised and explained | The 7-person lunch group drops from "strong" to medium, labelled "likely a social or lunch group" |
| Daytime-only pairs with no home visit are capped at medium | Ordinary daytime routines can't top the list |
| Same department, neighbours, direct work email and security role at a home are listed as innocent explanations | Shown with every lead |

Result: 22 medium and 32 weak leads, none strong. The top leads are security staff at the CFO's and CIO's homes at night. They're flagged and annotated "could be patrol or protection duty", and the chance baseline shows the CIO visits recur on most nights, which looks like a routine. That's the intended behaviour: surface it, explain it, let a human judge.

## Limits
- VAST is a fictional scenario; no conclusion here is ground truth.
- Card attribution covers 19 of 55 cards. Cafés near the office are reached on foot, so car GPS can't attribute them; they stay unresolved.
- Mentions are exact-name matches only (no nicknames or pronouns). They're a transparent baseline for a reviewed extraction step, not a full NER system.
- The chance baseline has 13 shifts, so the smallest possible p-value is 0.071. Treat it as a screening signal, not a significance test.

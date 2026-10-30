# Analysis model: contract, factors and weights (v1.1)

`analysis_model.run_case_analysis(persons, edges, mode, weights)` analyses **one case**. The backend loads the case, calls the function, validates the output and saves the run. The function never touches a database.

## Contract

**Inputs**

| Argument | Shape |
|---|---|
| `persons` | DataFrame: `person_id` (unique), optional `department` |
| `edges` | DataFrame: `person_a`, `person_b`, `relationship_type`, `is_inferred` (bool), `weight` (float ≥ 0), optional `factors` (dict or JSON), optional `evidence_refs` (list or `;`-string) |
| `mode` | `"observed_only"` (inferred edges dropped) or `"observed_plus_inferred"` |
| `weights` | Parsed `weights/v1_1.json` (current; `v1.json` kept for history); its `version` is echoed back |

**Output**

| Key | Meaning |
|---|---|
| `status` | `ok` = every stage succeeded · `partial` = a non-critical stage failed (results present but incomplete) · `failed` = input, edge or graph stage failed (no results) |
| `stages` | For `validate_input`, `edge_strength`, `graph`, `centrality`, `communities`, `link_prediction`: `status` (`ok` / `failed` / `skipped`), `error`, `rows` |
| `person_metrics` | `person_id, degree, weighted_degree, betweenness, pagerank, community_id, hub_flag`, one row per person (people with no edges get zeros) |
| `predicted_links` | `person_a, person_b, method, score, factor_breakdown (dict), evidence_refs (list)` |
| `warnings` | e.g. dropped self-loops, zero-strength edges, flagged hubs |
| `mode`, `weights_version` | Echoed for storage in `inv.analysis_runs` |

**"No findings" vs "failed":** `link_prediction` with `status: ok, rows: 0` means nothing was found. `status: failed` with an error means the algorithm broke. Results from a failed stage are left missing (e.g. `community_id` empty), never filled in.

**Validation rejects:** unknown mode, weights without a version, duplicate `person_id`, edges whose endpoints aren't in `persons` (catches cross-case mix-ups), missing edge columns.

## Stages

1. **Edge strength** (per edge, with a readable breakdown)
   - *Observed* edge: `type weight × input weight`. For **email pairs**, when `factors` has `direct_email_events`: `log(1 + direct emails) + broadcast_weight × log(1 + broadcast emails)`. With `broadcast_weight = 0`, pairs linked only by all-staff emails aren't relationships.
   - *Inferred* edge with `factors`: the sum of the factor contributions below, divided by `inferred_scale` (15).
2. **Graph:** one weighted edge per pair (strengths summed). Then **association strength** `w = s_ab / √(S_a · S_b)`, where `S` is a person's total strength, so one of many mass contacts counts less than an exclusive tie (the "P0001 hub" fix). **Hubs** (degree > mean + 3σ and ≥ 3) are flagged for verification, **not dropped**.
3. **Centrality:** degree, weighted degree, PageRank on `w`, betweenness with distance `1/w` (exact up to 2,000 people, seeded sampling above).
4. **Communities:** Leiden if `leidenalg` is installed, else seeded Louvain on `w`. Labels `C00`, `C01`… by size. They're groups of people who interact closely, not verified gangs.
5. **Link prediction** (methods chosen by the benchmark in `results/link_methods/REPORT.md`):
   - `tie_without_recorded_communication`: pairs joined by a **non-communication** tie (inferred co-location, or observed meetings, friendship and similar) with no observed communication of positive strength. Score = summed evidence strength; breakdown = factor contributions plus `basis` (`inferred` / `observed`); evidence = supporting IDs. On Noordin this recovers hidden communication at about 10× random AP, far above shared-contact methods. In `observed_only` mode, inferred ties are absent, so GAStech gets no such leads there.
   - `network_proximity_ppr`: pairs with no edge, ranked by symmetrised **personalised PageRank** (restart 0.15, unweighted transitions). Across 8 time-sliced covert networks it beat Adamic-Adar at predicting next-period links (24 of 36 transitions, 95% CI of the gain above zero), and tied on hidden-link recovery across 17 networks. Breakdown lists shared contacts and the proximity score. Cases over 3,000 people fall back to Adamic-Adar (`network_proximity_adamic_adar`).
   - Up to 50 suggestions per method, sorted by score.

## Inferred-edge factors (GAStech co-location)

| Factor (from `inv.inferred_relationships.factors`) | Contribution | Why |
|---|---|---|
| `private_days` (distinct days with a private-context overlap, cap 5) | +3 per day | Repetition is the core signal; meetings are a strong tier in Noordin |
| Group-gathering share (`group_gatherings / private_meetings`) | −60% × share of the meeting-day points | Group routines (3+ cars) are weak evidence of a specific tie |
| `home_visits > 0` | +1.5 | A home is more personal than a venue |
| After-hours share (`after_hours_private / private_meetings`) | +2 × share | Night and weekend meetings are less routine |
| `chance_p_value ≤ 0.1` with ≥ 2 days | +2.5 | More often than day-shifted chance |
| `public_place_events` | +0.3 × log(1 + n) | GAStech: public sightings barely change email rate (29% vs 24%) |
| `both_live_here_events > 0` | +0.5 | Neighbours: proximity, not a meeting |
| Same department | −1.5 | GAStech: emails follow departments (95% vs 5%), so contact is routine |
| No after-hours and no home visit | total × 0.5 | Daytime-only routine |

## Observed tie types (`weights.observed`)

| Type | Weight | Source |
|---|---|---|
| EMAILED, INTERCEPTED_COMMUNICATION, COMMUNICATIONS | 1.0 | Observed communication |
| FRIENDSHIP, MEETINGS | 1.0 | Noordin strong tier (87% / 89% also communicate; bootstrap range excludes zero) |
| KINSHIP | 0.9 | Noordin strong, only 16 pairs |
| SOULMATES, BUSINESS&FINANCE | 0.7 | High share, too few pairs to be sure |
| LOGISTICS | 0.5 | Noordin medium |
| TRAININGEVENTS, OPERATIONS | 0.3 | Noordin weak |
| CLASSMATES | 0.2 | Noordin weak |
| Unknown type | 0.5 | Judgement |

The weights are **hand-set and versioned**, informed by `results/noordin/report.md` and the GAStech feasibility check. They are not a trained model and not a probability of criminality. Change them by adding `weights/v2.json`; every run stores the version it used.

## Example outputs (from `example_adapter.py` on schema `inv`, weights v1.1; full text in `results/analysis_v1_1/`)

| Case / mode | Result |
|---|---|
| GAStech, observed + inferred | `ok`. Top "meet but never communicate" lead: SVP/CFO Ingrid Barranco ↔ perimeter-control officer Hennie Osvaldo (2 private days, home visit, after hours; 24 supporting events). Lunch-group pairs are discounted |
| GAStech, observed only | `ok`, no inferred leads (as designed); broadcast-only email pairs excluded |
| Caviar | `ok`. Subject X1 ranks first on PageRank and betweenness and is flagged as a hub to verify |
| Noordin (all layers) | `ok`. Noordin Mohammed Top ranks first on PageRank; Azhari Husin third; both flagged as hubs. Top tie-without-communication leads list the exact layers (e.g. FRIENDSHIP + OPERATIONS) |

These rankings describe position within each network. They aren't accuracy figures.

## Tests
`pytest analysis_model/tests` (14 tests): contract shape, mode filtering, lead breakdown and evidence, broadcast handling, failed stages reported as `partial` with errors, link-prediction failure distinguished from no findings, cross-case IDs rejected, empty case, determinism, hubs flagged not dropped.

## Measured performance
See `results/link_methods/REPORT.md`. In short: tie-based leads recover hidden communication on Noordin at AP 0.68 (10.4× random, all top 10 correct). Network proximity predicts next-period links at about 2–3× random across 8 real covert networks. These are ranking-quality measures on coded networks, not crime-detection or GAStech accuracy.

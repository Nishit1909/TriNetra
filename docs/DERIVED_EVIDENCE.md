# Derived evidence layer

The validated case ZIP is source evidence. `derived/` contains separately generated hypotheses and supporting references. The source ZIPs and person identities are unchanged.

## Rebuild and verify

Requires Python 3.10+, pandas 2+, numpy, scikit-learn and networkx. NetworkX is used only by the separate Caviar check.

```text
python -m zipfile -e datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip case-input
python scripts/derive_evidence.py case-input derived
python scripts/validate_derived.py case-input derived
python -m unittest discover -s tests -v
python scripts/caviar_check.py cases/caviar
```

`case-input/` is a local extraction directory, excluded from Git. The unittest suite extracts and rebuilds its own disposable copy. No command above contacts a database or OpenAI API.

## Rules

1. GPS establishes vehicle positions. A gap of at least five minutes proposes a stop only when the positions bounding it are at most 50 metres apart. Stops remain inferred; close endpoints cannot prove continuous parking. Other gaps are retained as uncertain and excluded from positive co-location.
2. A person is associated only through the verified assignment table, labelled `assigned_driver_assumed`. Display "this person's assigned vehicle overlapped another vehicle", not a proven personal meeting.
3. Email counts use resolved sender-recipient events only. The 111 quarantined endpoint events remain excluded. Events are not unique messages or telephone calls.
4. Lead strength is a hand-written screening score, not a trained model, probability of crime or calibrated significance test. Possible routine explanations remain visible.
5. Card ownership remains unresolved because no verified merchant-to-place mapping is provided. Matching parking and purchase times alone is insufficient. No person-to-card ownership edges are exported.

## Current outputs

| File | Rows | Meaning |
|---|---:|---|
| vehicle_stops.csv | 2,975 | Inferred stationary intervals with both bounding GPS IDs, coordinates and displacement |
| uncertain_vehicle_gaps.csv | 93 | Ambiguous sampling gaps retained for inspection, excluded from positive inference |
| places.csv | 73 | Stop clusters: one workplace-like place and 23 home-like places; classifications are inferred |
| colocation_events.csv | 13,357 | Assigned-vehicle stop intervals overlapping for at least ten minutes within the same inferred place |
| colocation_relationships.csv | 561 | Pair summaries, chance comparison, lead scores, explanations and support IDs for all categories |
| card_owner_inference.csv | 55 | All source cards retained, all ownership unresolved |
| card_owner_evidence.csv | 0 | Header-only: no unsupported ownership evidence |
| loyalty_card_links.csv | 55 | 53 links meet the three-match rule; two remain weak. These do not establish person ownership. |
| document_mentions.csv | 3,002 | Exact-name mentions with text offsets, all proposed for review |
| derived_graph_edges.csv | 550 | 497 assigned-vehicle-based pair hypotheses and 53 loyalty/payment links, all marked inferred |
| derived_graph_nodes.csv | 138 | Nodes for every overlay endpoint; merge by node_id with the base graph |

## Corrected chance comparison

One vehicle schedule is shifted by each of 1–13 days. Distinct overlap days are counted separately for each shift direction and then averaged. The old code counted distinct days after combining directions and divided again, understating the baseline.

After that correction and exclusion of ambiguous gaps, current lead levels are 10 medium, 41 weak multi-day, 127 single-day weak and 383 not-a-lead. None is strong. Twenty-five pairs have repeated private-context overlaps with no counted direct email. These are vehicle-based screening outputs, not evidence of an undisclosed personal relationship.

The minimum smoothed chance value is 1/14, approximately 0.071. The short observation period, circular shifts, inferred stops and manually chosen rules limit its interpretation. Do not market this as a validated p-value or criminal-risk estimate.

## Evidence keys and graph integration

Every pair has `supporting_colocation_ids` covering all supporting event categories. `supporting_private_colocation_ids` retains the private-context subset separately. A graph edge supplies `evidence_table` and `evidence_key`: `relationship_key` identifies a pair row, and `link_key` identifies a loyalty/payment row.

Follow a pair row to its co-location IDs, then its stop IDs, then `last_gps_event_id` and `next_gps_event_id` in the source events. Email references point to `evidence/communication_events.csv`. Do not populate a drawer with unrelated records merely because an ID exists.

The 44-check validator verifies exact GPS endpoints and intervals, overlap calculations, pair membership, private-context support, source identities, node coverage and evidence-key resolution. The regression suite also proves corrupted intervals, unrelated support and missing nodes are rejected, and card suffixes retain leading zeros. These checks establish consistency, not field accuracy.

## Remaining limits

- A radius-50-metre place cluster is not a pairwise 50-metre proximity test; two members can be farther apart. Say "same inferred place" unless adding a separate pairwise rule.
- Home/workplace and person-meeting names are inferred context labels, never proven addresses or personal presence. Keep attribution warnings visible.
- Text extraction is a dictionary baseline. It misses aliases and pronouns and does not extract arbitrary relationships. Entity types also require review.
- The source case has email headers and vehicle GPS, not genuine phone CDRs. See [input record contracts](INPUT_RECORDS.md).
- This branch exports files. The SIH backend and frontend still require integration; no API or shared database has been updated.

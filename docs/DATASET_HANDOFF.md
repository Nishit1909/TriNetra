# GAStech dataset ready for integration

Prepared 30 October 2026. The original repository and shared databases were not changed.

## Send these files to the team

- GASTECH_MC1_MC2_VALIDATED_CASE.zip: prepared coherent case, source-linked email evidence, text documents, mappings and validation reports.
- GASTECH_SOURCE_ARCHIVES.zip: original MC1 and MC2 downloads, unchanged, from the university VAST benchmark repository.
- This handoff and the package README explain what is ready and the remaining integration limits.

The sources are the official 2021 re-release of the fictional January 2014 GAStech scenario. MC1 was fetched for communications and text; MC2 was fetched to verify existing GPS/assignment data against originals. The friend's claim that Caviar was already present could not be confirmed: no Caviar source was found in the supplied repository archive.

## Verified contents

| Item | Count |
|---|---:|
| Employee roster identities | 54 |
| Exact full-name matches to existing GPS roster | 35 |
| Additional MC1 employees | 19 |
| Raw email-header rows | 1,175 |
| Resolved non-self sender-recipient events | 8,097 |
| Quarantined unresolved endpoint events | 111 |
| Vehicles | 40 |
| Source-backed vehicle assignments | 35 |
| GPS records verified against source | 685,169 |
| Existing coordinate bins | 33,708 |
| Card purchase rows without verified person ownership | 1,490 |
| Date-only loyalty records | 1,392 |
| News documents | 845 |
| Resume documents converted to text | 35 |
| Background documents converted to text | 4 |

Email-recipient events are not unique messages. Multi-recipient rows expand to several events. Four groups of identical-looking header rows, totaling five extra rows, are retained and flagged because no Message-ID proves whether they are duplicates. Self-recipient entries are preserved outside the relationship graph.

## Identity and source decisions

- All 35 shared employee names matched uniquely and exactly. Existing P0001 through P0035 identities were retained; 19 new identities use a separate MC1 prefix to avoid colliding with the old Enron placeholders.
- One address, Sten.Sanjorge Jr.@gastech.com.tethys, does not exactly match the employee roster domain. The affected 111 expanded endpoint events remain in the evidence quarantine, not silently merged with the Kronos account. This is an unresolved alias candidate, not proof of a different person.
- Original MC1 and MC2 disagree on six job titles and two department attributes. Both values and their source records are retained. No claim that one source was corrected by the other is made.
- Vehicle assignments were verified against official car-assignments.csv. All GPS remains vehicle evidence: person_id is blank, because assignment does not prove the driver. The previous 613,077 populated person attributions are not promoted to confirmed observations; they remain recoverable in the unchanged original supplied archive.
- Enron communications, synthetic cross-source identities, synthetic CDRs and synthetic identity training pairs are not in this coherent case. They remain in the unchanged original archive.
- Email and GPS source timestamps remain naive local values with an explicit unknown-timezone policy. No UTC offset or midnight time for date-only loyalty events was invented.

## Backend owner next steps

1. Disable unsafe fuzzy auto-merges. Preserve these source-backed IDs and review proposals separately.
2. Read location_events.vehicle_id when event_type is VEHICLE_GPS and emit a vehicle visit, not a person visit. The present _iter_graph_edges skips these rows because person_id is blank. Do not refill person IDs as a workaround.
3. Persist evidence/communication_events.csv, or introduce a compatible event table, so email timestamps, subjects and source references survive import. The current importer reads only the five existing communication columns and ignores this sidecar.
4. Keep the same timestamped event input across projection and analytics. A shared coordinate bin alone is not a meeting. No new personal co-location ground truth is claimed in this package.
5. Rehearse in a disposable environment or truly isolated case. Current global upserts do not remove old Enron relationships, so importing this archive into the old graph is not a clean replacement. No shared-database cleanup has been authorized or performed here.

The static graph_nodes.csv and graph_edges.csv are internally consistent. They include vehicle visits, but the current upload implementation does not read those graph CSVs; it reconstructs edges from other tables. A header-valid archive is therefore not proof of end-to-end live application correctness.

## Checks completed

- Existing backend schema validator executed successfully with no database calls.
- Independent scan of the finished ZIP checked CRC integrity, counts, unique IDs, endpoint references, timestamps, valid coordinates, communication-to-evidence coverage and vehicle-only GPS graph edges.
- Each supplied GPS row was matched in order to the official raw source by vehicle and timestamp; its coordinate-bin error is at most half a four-decimal bin, allowing decimal midpoint rounding differences.
- Raw download hashes, detailed mapping evidence, source conflicts, document hashes and expected examples are included.

Not checked: live PostgreSQL or Neo4j import, browser display, target cloud schema, API extraction accuracy or performance. No API key was used, no credit was spent, and no backend source was modified.

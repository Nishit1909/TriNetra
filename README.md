# GAStech hackathon dataset handoff

Start with **[docs/DATASET_HANDOFF.md](docs/DATASET_HANDOFF.md)** before importing. This repository currently contains dataset artifacts and integration notes, not a runnable application.

The package combines the official VAST 2021 re-release of the fictional January 2014 GAStech Mini-Challenge 1 and Mini-Challenge 2 scenario. Unrelated Enron communications and derived phone records are excluded.

## Download these files

| File | Use |
|---|---|
| [Prepared case ZIP](datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip) | Extract into a new directory for integration. Includes CSV tables, source-linked email evidence, text documents, mappings, conflicts and validation reports. |
| [Original source archives](datasets/GASTECH_SOURCE_ARCHIVES.zip) | Unchanged MC1 and MC2 downloads for checking provenance and rebuilding source inputs. |
| [Dataset handoff](docs/DATASET_HANDOFF.md) | Readiness, source decisions and the specific backend changes still needed. |
| [Metadata](validation/DATASET_METADATA.json) | Counts, original source URLs/hashes, exclusions and limitations. |
| [Validation results](validation/independent_validation.json) | Independent archive checks and existing backend schema check. No live database import. |
| [Expected examples](validation/expected_checks.json) | Source-backed checks for integration; these are not crime labels or a model benchmark. |
| [ZIP checksums](datasets/SHA256SUMS.json) | SHA-256 digests for both ZIP files. |

On GitHub, open a ZIP and select **Download raw file**, or clone the repository. The prepared case is approximately 7.6 MB; the original source bundle is approximately 11.2 MB.

## What is included

- 54 employee identities: 35 exact matches to the existing movement roster and 19 additional MC1 employees.
- 1,175 original email-header rows expanded into 8,097 resolved, non-self sender-recipient events. Recipient events are not unique messages.
- 40 vehicles, 35 verified assignment relations and 685,169 GPS records checked against original source timestamps, vehicles and coordinate bins.
- 1,490 card purchases and 1,392 date-only loyalty records, without invented person ownership.
- 845 news documents, 35 resumes and four background documents as source-linked UTF-8 text.

## Integration limits that must not be hidden

The files passed structural checks and the audited SIH backend's existing schema validator. That does not mean the current app will preserve every evidence field automatically.

1. **Preserve identities.** Disable the audited unsafe name auto-merge before importing new roster identities.
2. **Preserve email evidence.** The existing five-column communications import drops timestamps and provenance. Integrate `evidence/communication_events.csv` to retain them.
3. **Display vehicle GPS honestly.** GPS rows have a vehicle ID and no confirmed person ID. The audited backend skips these graph edges; adapt it to represent vehicle visits rather than inventing the driver.
4. **Use clean test storage.** Global upserts in the old app will not remove old Enron graph edges. No shared database cleanup or migration has been performed here.
5. **Keep uncertainty visible.** One alternate-domain email address is unresolved; 111 affected recipient events are preserved for review. Eight attribute conflicts between the original MC1 and MC2 sources retain both values.

The static `graph_nodes.csv` and `graph_edges.csv` inside the prepared ZIP contain vehicle visits, assignments and communication pairs. The audited uploader reconstructs graph edges from other tables and does not read these graph CSVs. Raw event timestamps are still required for temporal inference.

## Sources and scope

- [Official MC1 scenario](https://vast-challenge.github.io/2021/MC1.html)
- [Original MC1 archive](https://visualdata.wustl.edu/varepository/VAST_Challenge_2021/challenges/MC1/dataset/MC1.zip)
- [Original MC2 archive](https://visualdata.wustl.edu/varepository/VAST_Challenge_2021/challenges/MC2/dataset/MC2.zip)

This is fictional scenario evidence, not real-world criminal-risk ground truth. No Caviar source was identified in the supplied SIH archive. No OpenAI API key or API credit was used for dataset preparation.

Prepared 30 October 2026. Live PostgreSQL/Neo4j import and browser rehearsal remain unverified. No model performance claim is made.

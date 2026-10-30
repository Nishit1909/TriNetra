# Evidence corrections implementation plan

**Goal:** Correct the reviewed evidence defects without changing source dataset identities or inventing phone records.

**Architecture:** Keep the existing batch script and CSV outputs. Bound stop inference using both GPS endpoints, count null trials consistently, retain evidence keys for every overlay category, and leave card ownership unresolved because merchant coordinates are not verified.

**Scope approved:** The user requested fixes to the reviewed branch and asked about persons and CDR files. No new application backend, model, source-data rewrite or shared database import is included.

## Sequence

- [x] Add an end-to-end unittest regression suite that rebuilds the prepared case in temporary storage. Demonstrate failures for unsupported card attribution, null-day arithmetic, ambiguous GPS gaps, missing supporting IDs and missing graph nodes.
- [x] Update scripts/derive_evidence.py. Record both bounding GPS IDs and displacement; separate uncertain gaps; use direction-specific unique-day counts; keep cards unresolved without merchant mapping; export full support keys and graph nodes.
- [x] Strengthen scripts/validate_derived.py to check the corrected contracts, including source identities, exact overlap durations, uncertainty, overlay endpoints and evidence keys.
- [x] Regenerate derived artifacts from the unchanged case, rerun the regression suite and validator, and rerun Caviar separately.
- [x] Update README and docs/DERIVED_EVIDENCE.md with corrected counts, person-attribution limits and the explicit absence of genuine phone CDRs. Add docs/INPUT_RECORDS.md describing the source-file contracts.
- [x] Review the diff and source ZIP hashes. Independent review found no blockers; private-support and leading-zero identifier checks were added after its feedback.

Publication follows verification: commit only this scope, push codex/fix-derived-evidence, and open a draft PR targeting derived-evidence-layer. Do not merge the friend's branch.

## Verification commands

Run `python -m unittest discover -s tests -v`, then `python scripts/validate_derived.py <extracted-case> derived` and `python scripts/caviar_check.py <separate-copy-of-caviar>`. Source ZIP SHA-256 values must remain those recorded in datasets/SHA256SUMS.json. A failed structural or regression check blocks publication of regenerated claims.

# People communications and phone records

This branch keeps source evidence separate from derived proposals. The original dataset ZIPs and SHA-256 checksums remain unchanged by the evidence corrections.

| File | What is established | What must remain uncertain |
|---|---|---|
| persons.csv | 54 source-backed GAStech employee identities; 35 exact full-name matches to the movement roster and 19 additional MC1 employees | Names are not unique identity keys. Source job-title/department disagreements remain in evidence/source_attribute_conflicts.csv. No person is labelled criminal. |
| evidence/employee_identity_mapping.csv | Workbook email, original person ID where present, exact-name mapping method and workbook row | It does not approve arbitrary future fuzzy matches or merge the unresolved alternate-domain email. |
| communications.csv | 8,097 resolved non-self sender-recipient email events in the existing five-column import format | These are not 8,097 unique messages, phone calls or independent corroborating sources. |
| evidence/communication_events.csv | Email timestamp, subject, full addresses, source row/recipient index and header hash | Source timezone remains unknown. Header duplicates cannot be resolved into unique messages without Message-ID evidence. |
| evidence/unresolved_email_endpoints.csv | 111 affected endpoint events involving an address absent from the exact roster | The alternate Tethys-domain CEO address is an alias candidate; it is excluded from resolved analysis until reviewed. |
| vehicle_assignments.csv | 35 assignments verified against original MC2 source | Assignment does not establish who drove a vehicle during a GPS event. Derived person associations remain assigned_driver_assumed. |
| location_events.csv | 685,169 source-verified vehicle GPS records | Person IDs remain blank. Inferred stationary intervals are not direct observations of a person meeting someone. |
| transactions.csv | 1,490 source purchase records with merchant labels, amounts and payment-card suffixes | No verified person ownership or merchant-to-GPS-place mapping. All 55 payment cards remain unresolved in card_owner_inference.csv. |
| loyalty_events.csv | 1,392 date-only records | Day-level matching does not establish exact purchase times, legal identity or card ownership. Loyalty/payment links remain proposals. |
| cases/caviar/persons.csv | A separate 62-subject anonymized network with CV_ identifiers | Never join it to GAStech people. Its centrality example does not validate GAStech lead scores or personal criminal-risk prediction. |

## Why there is no CDR file

Neither GAStech MC1 nor MC2 supplies genuine telephone call-detail records. MC1 supplies email headers. The old SIH package's cdr_records.csv was explicitly synthetic: phone numbers, towers, durations and call times were generated from Enron edges. It is intentionally excluded from this coherent case.

Do not recreate those records, rename emails as calls, infer phone numbers from names, or use invented calls to support a lead. There is no CDR import feature in the evidence-layer script and no phone evidence was added by these fixes.

If the team later obtains authorized real call records, keep them as a separate source with actual caller/callee identifiers, timestamps and timezone, source record IDs and known units. Map people only with supporting identity evidence. That would require a separate documented ingestion contract; it is not implemented or claimed here.

## What backend integration still needs

The old SIH uploader ignores the evidence sidecars, drops communication timestamps and automatically fuzzy-merges names. Its graph loader skips vehicle GPS when person_id is blank. This data-only repository does not contain that application backend, so these fixes cannot change it.

Use person_id for joins; preserve source rows and event times; show vehicle movements; keep observed records separate from inferred overlays; and show the exact supporting evidence when selecting a relationship. Do not append this case into an old globally upserted Enron graph and call it a clean replacement.

The validation script checks input identifiers and references, exact stop endpoints, overlap intervals, supporting pair membership, and overlay endpoints/evidence keys. These checks establish consistency of this pipeline, not real-world inference accuracy.

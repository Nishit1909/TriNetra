# Sample upload: Operation Monsoon Ledger (fictional)

Invented people and events for testing case ingestion. Not real data.

| File | Use |
|---|---|
| `monsoon_ledger_case.zip` | Valid case: 30 people, 41 relationships, 309 messages (incl. 3 all-staff broadcasts) |
| `monsoon_ledger_BROKEN.zip` | Deliberately invalid: duplicate person ID, unknown person, self-link, negative weight, bad date. Must be rejected with 5 errors and save nothing |
| `monsoon_ledger_csv/` | The same valid case as three separate CSVs (for the "Separate CSV Files" mode) |
| `make_monsoon_ledger.py` | Regenerates the files (deterministic) |

Planted story, to check the analysis finds it:
- **Rakesh Venkat (OM01)** coordinates in person: meetings with one person in each team, almost no messages. Expected: hub flag, top bridging score, and all top "meets but never communicates" leads involve him.
- **Suresh Babu (OM16)** links customs, port and finance. Expected: key figure / high influence.
- **Asha Rao (OM22)** sends the all-staff broadcasts. Expected: those messages add no relationship strength.
- Two people share the surname Rao: they must stay separate people (no automatic merging).

Upload as an investigator or admin: Upload Case → Single ZIP Archive → Validate → Create → Run Analysis & Open Network Graph.

# Sample upload: Operation Monsoon Ledger (fictional)

Invented people and events for testing case ingestion. Not real data.

| File | Use |
|---|---|
| `monsoon_ledger_case.zip` | Valid case: 30 people, 41 relationships, 309 messages (incl. 3 all-staff broadcasts), 399 location points, 7 money transfers |
| `monsoon_ledger_BROKEN.zip` | Deliberately invalid: duplicate person ID, unknown person, self-link, negative weight, bad date. Must be rejected with 5 errors and save nothing |
| `monsoon_ledger_csv/` | The same valid case as separate CSVs: persons, relationships, communications (required), locations, transactions (optional) |
| `make_monsoon_ledger.py` | Regenerates the files (deterministic) |

Planted story, to check the analysis finds it:
- **Rakesh Venkat (OM01)** coordinates in person: meetings with one person in each team, almost no messages. Expected: hub flag, top bridging score, and most top "linked, but never communicates" leads involve him.
- **Suresh Babu (OM16)** links customs, port and finance. Expected: key figure / high influence.
- **Asha Rao (OM22)** sends the all-staff broadcasts. Expected: those messages add no relationship strength.
- **Pooja Agarwal (OM28, auditor)** meets **Lakshmi Iyer (OM09, accounts)** four times late at night at a riverside godown, and they never call or e-mail. Only `locations.csv` reveals it. Expected: an *inferred* "linked, but never communicates" lead (private meeting days 4, after hours, more than chance), with the 4 meetings in pair evidence (one side is cell-tower: marked low precision).
- **Ravi Shankar (OM25, supplier)** pays Suresh Babu ₹4.85 lakh over UPI, and **Suresh Babu pays the auditor ₹4.5 lakh in cash**, with no recorded communication with her. Expected: a "linked, but never communicates" lead for Suresh ↔ Pooja, with the transfers listed in pair evidence.
- Everyone also appears at the Port Office on working days: busy daytime place = routine, so it creates no leads.
- Two people share the surname Rao: they must stay separate people (no automatic merging).

Upload as an investigator or admin: Upload Case → Single ZIP Archive → Validate → Create → Run Analysis & Open Network Graph.

-- Run in Supabase SQL Editor after loading. All reads are case scoped.
SELECT c.case_id, c.name,
       (SELECT count(*) FROM inv.persons p WHERE p.case_id=c.case_id) AS persons,
       (SELECT count(*) FROM inv.relationships r WHERE r.case_id=c.case_id) AS observed_relationships,
       (SELECT count(*) FROM inv.inferred_relationships i WHERE i.case_id=c.case_id) AS inferred_relationship_rows,
       (SELECT count(*) FROM inv.communication_events e WHERE e.case_id=c.case_id) AS email_events,
       (SELECT count(*) FROM inv.location_events g WHERE g.case_id=c.case_id) AS gps_events
FROM inv.cases c ORDER BY c.case_id;
-- GAStech: 54 persons,1262 observed,561 inferred rows,8097 email events,685169 GPS.
-- Caviar: 62 persons,88 observed relationships.
-- Noordin:79 persons,1014 observed typed relationships (includes communication labels).

// Active case projections only; no global MATCH (node) query.
MATCH (c:InvCase)
RETURN c.case_id,c.active_snapshot_id,c.person_count,c.edge_count;

MATCH (c:InvCase {case_id:'CASE_VAST_GASTECH'})
MATCH (a:InvPerson {case_id:c.case_id,snapshot_id:c.active_snapshot_id})
      -[r:INV_LINK]->
      (b:InvPerson {case_id:c.case_id,snapshot_id:c.active_snapshot_id})
RETURN a,r,b LIMIT 100;

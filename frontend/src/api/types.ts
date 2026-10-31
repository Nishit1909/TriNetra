export type PortalView = 'viewer' | 'investigator' | 'admin';
export type PortalRole = 'viewer' | 'investigator' | 'admin';
export type CaseAccessLevel = 'viewer' | 'editor' | 'admin';
export type AnalysisMode = 'observed_only' | 'observed_plus_inferred';
export type CaseRole = 'investigation' | 'benchmark' | 'centrality_example';
export type NodeTier = 'key_figure' | 'secondary_figure' | 'connector' | 'neutral';

export interface HealthResponse {
  status: string;
  api_version?: string;
}

export interface DatabaseHealthResponse {
  status: 'ok' | 'degraded' | 'unavailable';
  databases: {
    postgresql: string;
    neo4j: string;
  };
  notes: string[];
}

export interface AuthCaseAccess {
  case_id: string;
  name: string;
  access_level: CaseAccessLevel;
}

export interface AuthMeResponse {
  user_id: string;
  label: string;
  role: PortalRole;
  view: PortalView;
  is_admin: boolean;
  can_edit: boolean;
  local: boolean;
  is_demo: boolean;
  display_name?: string;
  login_required?: boolean;
  cases: AuthCaseAccess[];
}

export interface LoginResponse {
  signed_in: boolean;
  expires_at: string;
  role: PortalRole;
  label: string;
  display_name: string;
}

export interface CaseRecord {
  case_id: string;
  name: string;
  description: string | null;
  source: string | null;
  is_synthetic: boolean;
  role: CaseRole;
  created_at?: string;
}

export interface CaseCounts {
  persons: number;
  vehicles: number;
  communication_events: number;
  relationships: number;
  inferred_relationships: number;
  colocation_events: number;
  places: number;
  documents: number;
  document_mentions: number;
  transactions: number;
}

export interface StageStatus {
  status: 'ok' | 'failed' | 'skipped';
  error: string | null;
  rows: number | null;
}

export interface AnalysisRun {
  analysis_run_id: string;
  case_id: string;
  mode: AnalysisMode;
  weights_version: string;
  algorithm: string;
  status: 'running' | 'completed' | 'partial' | 'failed';
  error: string | null;
  started_at: string;
  completed_at: string | null;
  parameters: {
    weights_version?: string;
    algorithm?: string;
    stages?: Record<string, StageStatus>;
    warnings?: string[];
    model_status?: string;
  };
}

export interface CaseSummaryResponse {
  case: CaseRecord;
  counts: CaseCounts;
  latest_analysis: AnalysisRun | null;
  uncertainty: {
    vehicle_person_attribution: string;
    card_ownership: string;
    source_timezone: string;
  };
}

export interface VehicleAssignment {
  case_id: string;
  vehicle_id: string;
  person_id: string;
  relationship: string;
  source_car_id: string;
  department: string | null;
  owner_job_title: string | null;
  person_attribution: string;
}

export interface PersonRecord {
  case_id?: string;
  person_id: string;
  display_name: string;
  department: string | null;
  job_title: string | null;
  source_entity_id?: string | null;
  identity_basis?: string | null;
}

export interface PersonProfile extends PersonRecord {
  vehicle_assignments: VehicleAssignment[];
  counts: {
    emails: number;
    colocations: number;
    documents: number;
  };
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  score_note?: string;
  note?: string;
}

export interface TimelineEvent {
  event_time: string | null;
  event_id: string;
  event_type: 'email' | 'vehicle_stop' | string;
  evidence: Record<string, any>;
}

export interface PersonMetric {
  case_id?: string;
  analysis_run_id?: string;
  person_id: string;
  degree: number | null;
  weighted_degree: number | null;
  betweenness: number | null;
  pagerank: number | null;
  community_id: string | null;
  hub_flag: boolean;
}

export interface PredictedLink {
  case_id?: string;
  analysis_run_id?: string;
  person_a: string;
  person_b: string;
  method: string;
  score: number;
  rank_in_method: number;
  basis: 'evidence' | 'structural_pattern';
  basis_note?: string;
  factor_breakdown: Record<string, any>;
  evidence_refs: string[];
  review_status: 'unreviewed' | 'confirmed' | 'dismissed';
  review_reason?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  other_person?: string;
  other_name?: string;
}

export interface TopTie {
  person_id: string;
  display_name: string | null;
  strength: number;
  types: string[];
  inferred: boolean;
}

export interface PersonExplainResponse {
  person: PersonRecord;
  run: {
    analysis_run_id: string;
    mode: AnalysisMode;
    weights_version: string;
    status: string;
  };
  metrics: PersonMetric;
  ranks: {
    pagerank: number;
    betweenness: number;
    degree: number;
    weighted_degree: number;
  };
  people_in_case: number;
  community: {
    community_id: string | null;
    size: number;
    members: { person_id: string; display_name: string | null }[];
  };
  top_ties: TopTie[];
  suggested_links: PredictedLink[];
  reasons: string[];
  note: string;
}

export interface InferredRelationship {
  case_id: string;
  person_a: string;
  person_b: string;
  relationship_type: string;
  person_attribution: string;
  lead_strength: number;
  lead_level: string;
  factors: Record<string, any>;
  possible_innocent_explanations: string;
  supporting_colocation_ids: string[];
  email_ids: string[];
  is_inferred: boolean;
}

export interface PairEvidenceResponse {
  case_id: string;
  person_a: string;
  person_b: string;
  observed_relationships: any[];
  inferred_relationships: InferredRelationship[];
  emails: PaginatedResponse<any>;
  transfers?: PaginatedResponse<any>;
  colocation_events: PaginatedResponse<any>;
  uncertainty: {
    person_attribution: string | null;
    note: string;
  };
}

export interface AnalysisDetailResponse {
  run: AnalysisRun;
  person_metrics: PersonMetric[];
  predicted_links: PredictedLink[];
  predicted_links_by_method: Record<string, PredictedLink[]>;
  score_note: string;
}

export interface RankMover {
  person_id: string;
  display_name: string | null;
  pagerank_rank_a: number;
  pagerank_rank_b: number;
  rank_change: number;
  community_a: string | null;
  community_b: string | null;
  community_moved?: boolean;
  hub_a: boolean;
  hub_b: boolean;
}

export interface CompareRunsResponse {
  run_a: { analysis_run_id: string; mode: AnalysisMode; weights_version: string };
  run_b: { analysis_run_id: string; mode: AnalysisMode; weights_version: string };
  biggest_rank_changes: RankMover[];
  community_changes: number;
  hub_changes: RankMover[];
  links_only_in_b: {
    person_a: string;
    person_b: string;
    names: (string | null)[];
    method: string;
    score: number;
  }[];
  links_only_in_a: {
    person_a: string;
    person_b: string;
    names: (string | null)[];
    method: string;
    score: number;
  }[];
  links_in_both: number;
  note: string;
}

export interface GraphNode {
  id: string;
  label: string;
  department: string | null;
  pagerank: number | null;
  betweenness: number | null;
  community_id: string | null;
  hub_flag: boolean;
  degree: number;
  tier?: NodeTier;
  pagerankRank?: number;
  betweennessRank?: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface GraphEdge {
  id: string;
  source: string | GraphNode;
  target: string | GraphNode;
  kind: 'observed' | 'inferred' | 'predicted';
  type: string;
  weight: number;
  basis?: 'evidence' | 'structural_pattern';
  method?: string;
  lead_strength?: number | null;
  rank_in_method?: number;
  curvature?: number;
}

export interface GraphResponse {
  case_id: string;
  run_id: string | null;
  mode: AnalysisMode;
  graph_source: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  counts: {
    total_nodes: number;
    total_edges: number;
    shown_nodes: number;
    shown_edges: number;
  };
  shown_by_kind: {
    observed: number;
    inferred: number;
    predicted: number;
  };
  truncated: boolean;
  warnings: string[];
}

export interface UploadTemplateResponse {
  files: Record<string, {
    required_columns: string[];
    optional_columns: string[];
    required_file: boolean;
  }>;
  how: string;
  rules: string[];
  example: Record<string, string>;
}

export interface ValidationReport {
  valid: boolean;
  errors: string[];
  warnings: string[];
  counts?: {
    persons: number;
    relationships: number;
    communications: number;
    locations?: number;
    places?: number;
    meetings?: number;
    inferred_links?: number;
    transactions?: number;
  };
  relationship_types?: string[];
  sha256?: string;
  case_id?: string;
  next?: {
    run_analysis: string;
    summary: string;
  };
}

export interface AdminUser {
  user_id: string;
  email: string;
  display_name: string;
  role: PortalRole;
  phone: string | null;
  badge_number: string | null;
  active: boolean;
  is_demo: boolean;
  last_access: string | null;
  requests_24h: number;
  open_alerts: number;
  cases: 'all (admin)' | { case_id: string; access_level: 'viewer' | 'editor' }[];
  has_password?: boolean;
  last_login_at?: string | null;
}

export interface AccessSummaryResponse {
  since: string;
  users: {
    user_id: string | null;
    user_label: string;
    role: PortalRole;
    requests: number;
    denied: number;
    first_access: string;
    last_access: string;
    cases: string[];
    persons_viewed: number;
  }[];
  cases: {
    case_id: string;
    requests: number;
    users: number;
    last_access: string;
  }[];
  open_alerts: {
    high?: number;
    medium?: number;
    low?: number;
  };
}

export interface SecurityAlert {
  alert_id: number;
  at: string;
  rule: 'denied_access' | 'conflict_of_interest' | 'bulk_viewing' | 'after_hours' | 'sensitive_action' | string;
  severity: 'high' | 'medium' | 'low';
  user_id: string | null;
  user_label: string;
  case_id: string | null;
  title: string;
  detail: Record<string, any>;
  status: 'open' | 'acknowledged' | 'dismissed';
  email_status: 'sent' | 'failed' | 'disabled' | 'below_threshold' | string;
  email_error?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
}

export interface AccessLogRow {
  log_id: number;
  at: string;
  user_id: string | null;
  user_label: string;
  role: string | null;
  method: string;
  path: string;
  case_id: string | null;
  person_id: string | null;
  action: string;
  status_code: number;
  allowed: boolean;
  duration_ms: number;
}

export interface ConflictItem {
  user_id: string;
  user: string;
  email: string;
  is_demo: boolean;
  case_id: string;
  matches: {
    person_id: string;
    display_name?: string;
    matched_on: string;
  }[];
}

export interface AdminSettingsResponse {
  smtp: {
    enabled: boolean;
    host: string;
    port: number;
    username: string;
    from_address: string;
    to_addresses: string[];
    use_starttls: boolean;
    use_ssl: boolean;
    min_severity: 'low' | 'medium' | 'high';
    password_configured: boolean;
    password_source: string;
  };
  alert_rules: {
    timezone: string;
    work_hours: [number, number];
    flag_weekends: boolean;
    bulk_window_minutes: number;
    bulk_person_views: number;
    sensitive_actions: string[];
    notify_logins?: boolean;
  };
}

export interface StrongTie {
  person_a: string;
  person_b: string;
  name_a: string | null;
  name_b: string | null;
  strength: number;
  types: string[];
  sources: string[];
  corroboration: number;
  inferred: boolean;
}

/**
 * Typed client for the TriNetra backend.
 *
 * Every value shown in the UI comes from the backend. There is no offline or
 * fallback data: if the backend is unreachable the call fails and the screen
 * shows an error with a retry, never a stand-in result.
 */
import type {
  AccessLogRow,
  AccessSummaryResponse,
  AdminSettingsResponse,
  AdminUser,
  AnalysisDetailResponse,
  AnalysisMode,
  AnalysisRun,
  AuthMeResponse,
  CaseRecord,
  CaseRole,
  CaseSummaryResponse,
  CompareRunsResponse,
  ConflictItem,
  DatabaseHealthResponse,
  GraphResponse,
  HealthResponse,
  InferredRelationship,
  LoginResponse,
  PaginatedResponse,
  PairEvidenceResponse,
  PersonExplainResponse,
  PersonProfile,
  PersonRecord,
  PredictedLink,
  SecurityAlert,
  TimelineEvent,
  UploadTemplateResponse,
  ValidationReport,
} from './types';

const API_BASE = (import.meta.env.VITE_PUBLIC_API_BASE || '').replace(/\/$/, '');
const STORAGE_DEMO_KEY = 'sih26189_demo_user_id';

/** Short reads fail fast; analysis, uploads and admin writes may legitimately take longer. */
const READ_TIMEOUT_MS = 30_000;
const WRITE_TIMEOUT_MS = 120_000;

/** The demo identity header is only ever sent to a backend on this machine. */
const DEMO_ALLOWED =
  typeof window !== 'undefined' && ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);

let currentDemoUserId = '';
// Bearer tokens are kept in memory only (never in localStorage, where any injected script could read them).
let currentBearerToken: string | null = null;

try {
  currentDemoUserId = localStorage.getItem(STORAGE_DEMO_KEY) || '';
} catch {
  // Storage can be unavailable (private mode, sandboxed frames).
}

export function getDemoUserId(): string {
  return currentDemoUserId;
}

export function setDemoUserId(userId: string): void {
  currentDemoUserId = userId;
  try {
    if (userId) localStorage.setItem(STORAGE_DEMO_KEY, userId);
    else localStorage.removeItem(STORAGE_DEMO_KEY);
  } catch {
    // Ignore storage failures; the in-memory value still applies.
  }
}

export function setBearerToken(token: string | null): void {
  currentBearerToken = token;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function errorMessage(status: number, payload: unknown): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message);
  if (status === 0) return 'The backend could not be reached.';
  return `Request failed (HTTP ${status})`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');
  if (!(options.body instanceof FormData) && options.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  // Writes carry the CSRF header the backend requires for cookie sessions.
  if (method !== 'GET' && method !== 'HEAD') headers.set('X-TRACE-CSRF', '1');
  if (currentBearerToken) headers.set('Authorization', `Bearer ${currentBearerToken}`);
  else if (DEMO_ALLOWED && currentDemoUserId) headers.set('X-Demo-User', currentDemoUserId);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), method === 'GET' ? READ_TIMEOUT_MS : WRITE_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...options, headers, signal: controller.signal });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === 'AbortError';
    throw new ApiError(0, timedOut ? 'The backend took too long to respond.' : 'The backend could not be reached.');
  } finally {
    clearTimeout(timer);
  }

  const text = await res.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { detail: text || res.statusText };
  }
  if (res.status === 401 && path !== '/api/auth/login' && typeof window !== 'undefined') {
    // Session missing or expired: the shell shows the sign-in page.
    window.dispatchEvent(new CustomEvent('trace:unauthorized'));
  }
  if (!res.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail;
    throw new ApiError(res.status, errorMessage(res.status, payload), detail);
  }
  return payload as T;
}

const enc = encodeURIComponent;
const casePath = (caseId: string) => `/api/cases/${enc(caseId)}`;
const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export const api = {
  getHealth: () => request<HealthResponse>('/health'),
  getDatabaseHealth: () => request<DatabaseHealthResponse>('/health/database'),
  getMe: () => request<AuthMeResponse>('/api/auth/me'),
  login: (email: string, password: string) => request<LoginResponse>('/api/auth/login', json({ email, password })),
  logout: () => request<{ signed_out: boolean }>('/api/auth/logout', { method: 'POST' }),
  changePassword: (current_password: string, new_password: string) =>
    request<{ changed: boolean; signed_out: boolean }>('/api/auth/password', json({ current_password, new_password })),
  resetUserPassword: (userId: string, password: string) =>
    request<{ password_reset: boolean; sessions_ended: number }>(`/api/admin/users/${enc(userId)}/password`, json({ password })),
  getAdminSessions: () => request<Record<string, any>[]>('/api/admin/sessions'),
  revokeAdminSession: (sessionId: number) => request<{ revoked: boolean }>(`/api/admin/sessions/${sessionId}/revoke`, { method: 'POST' }),

  getCases: () => request<CaseRecord[]>('/api/cases'),
  getCaseSummary: (caseId: string) => request<CaseSummaryResponse>(`${casePath(caseId)}/summary`),

  getPersons: (caseId: string, params: { q?: string; department?: string; limit?: number; offset?: number } = {}) => {
    const sp = new URLSearchParams();
    if (params.q) sp.set('q', params.q);
    if (params.department) sp.set('department', params.department);
    sp.set('limit', String(params.limit ?? 50));
    sp.set('offset', String(params.offset ?? 0));
    return request<PaginatedResponse<PersonRecord>>(`${casePath(caseId)}/persons?${sp}`);
  },
  getPersonProfile: (caseId: string, personId: string) =>
    request<PersonProfile>(`${casePath(caseId)}/persons/${enc(personId)}`),
  getPersonTimeline: (caseId: string, personId: string, limit = 40, offset = 0) =>
    request<PaginatedResponse<TimelineEvent>>(`${casePath(caseId)}/persons/${enc(personId)}/timeline?limit=${limit}&offset=${offset}`),
  getPersonExplain: (caseId: string, personId: string, params: { run_id?: string; mode?: AnalysisMode } = {}) => {
    const sp = new URLSearchParams();
    if (params.run_id) sp.set('run_id', params.run_id);
    if (params.mode) sp.set('mode', params.mode);
    return request<PersonExplainResponse>(`${casePath(caseId)}/persons/${enc(personId)}/explain?${sp}`);
  },

  getGraph: (
    caseId: string,
    params: { run_id?: string; mode?: AnalysisMode; include?: string; limit?: number; edge_limit?: number; focus?: string } = {},
  ) => {
    const sp = new URLSearchParams();
    if (params.run_id) sp.set('run_id', params.run_id);
    if (params.mode) sp.set('mode', params.mode);
    sp.set('include', params.include ?? 'observed,inferred,predicted');
    sp.set('limit', String(params.limit ?? 60));
    sp.set('edge_limit', String(params.edge_limit ?? 200));
    if (params.focus) sp.set('focus', params.focus);
    return request<GraphResponse>(`${casePath(caseId)}/graph?${sp}`);
  },

  listAnalysisRuns: (caseId: string) => request<AnalysisRun[]>(`${casePath(caseId)}/analysis`),
  getAnalysisDetail: (caseId: string, runId: string) =>
    request<AnalysisDetailResponse>(`${casePath(caseId)}/analysis/${enc(runId)}`),
  runAnalysis: (caseId: string, mode: AnalysisMode) =>
    request<AnalysisDetailResponse>(`${casePath(caseId)}/analysis`, json({ mode, weights_version: 'v1.2' })),
  getPredictedLinks: (
    caseId: string,
    runId: string,
    params: { method?: string; basis?: 'evidence' | 'structural_pattern'; person_id?: string; limit?: number; offset?: number } = {},
  ) => {
    const sp = new URLSearchParams();
    if (params.method) sp.set('method', params.method);
    if (params.basis) sp.set('basis', params.basis);
    if (params.person_id) sp.set('person_id', params.person_id);
    sp.set('limit', String(params.limit ?? 50));
    sp.set('offset', String(params.offset ?? 0));
    return request<PaginatedResponse<PredictedLink>>(`${casePath(caseId)}/analysis/${enc(runId)}/predicted_links?${sp}`);
  },
  getInferredLeads: (caseId: string, level = 'medium,weak', limit = 50, offset = 0) =>
    request<PaginatedResponse<InferredRelationship>>(`${casePath(caseId)}/leads?level=${enc(level)}&limit=${limit}&offset=${offset}`),
  getPairEvidence: (caseId: string, personA: string, personB: string) =>
    request<PairEvidenceResponse>(`${casePath(caseId)}/relationships/${enc(personA)}/${enc(personB)}`),
  reviewPredictedLink: (
    caseId: string,
    runId: string,
    personA: string,
    personB: string,
    body: { status: 'confirmed' | 'dismissed'; reason: string },
  ) =>
    request<{ reviews: PredictedLink[] }>(
      `${casePath(caseId)}/predicted_links/${enc(runId)}/${enc(personA)}/${enc(personB)}/review`,
      json(body),
    ),
  getPredictedLinkReviews: (caseId: string, runId: string, personA: string, personB: string) =>
    request<Record<string, unknown>[]>(`${casePath(caseId)}/predicted_links/${enc(runId)}/${enc(personA)}/${enc(personB)}/reviews`),
  compareRuns: (caseId: string, runA: string, runB: string, top = 12) =>
    request<CompareRunsResponse>(`${casePath(caseId)}/analysis/compare?run_a=${enc(runA)}&run_b=${enc(runB)}&top=${top}`),

  getDocument: (caseId: string, docId: string) =>
    request<Record<string, any>>(`${casePath(caseId)}/documents/${enc(docId)}`),
  reviewDocumentMention: (caseId: string, mentionId: number, body: { status: 'confirmed' | 'rejected'; reason: string }) =>
    request<Record<string, any>>(`${casePath(caseId)}/document_mentions/${mentionId}/review`, json(body)),
  getPlace: (caseId: string, placeId: string) => request<Record<string, any>>(`${casePath(caseId)}/places/${enc(placeId)}`),

  getUploadTemplate: () => request<UploadTemplateResponse>('/api/case-uploads/template'),
  // The second parameter is kept for call-site compatibility and ignored: results only come from the server.
  validateCaseUpload: (formData: FormData, _unused?: ValidationReport) =>
    request<ValidationReport>('/api/case-uploads/validate', { method: 'POST', body: formData }),
  createCaseUpload: (
    formData: FormData,
    _unused?: { name: string; description: string; role: CaseRole; is_synthetic: boolean; report: ValidationReport },
  ) => request<ValidationReport>('/api/case-uploads', { method: 'POST', body: formData }),

  getAdminAccessSummary: (hours = 24) => request<AccessSummaryResponse>(`/api/admin/access-summary?hours=${hours}`),
  getLatestAlerts: (afterId: number) =>
    request<{ items: SecurityAlert[]; latest_id: number; open: number }>(`/api/admin/alerts/latest?after_id=${afterId}`),
  getAdminAlerts: (params: { status?: string; severity?: string; rule?: string } = {}) => {
    const sp = new URLSearchParams();
    if (params.status) sp.set('status', params.status);
    if (params.severity) sp.set('severity', params.severity);
    if (params.rule) sp.set('rule', params.rule);
    return request<PaginatedResponse<SecurityAlert>>(`/api/admin/alerts?${sp}`);
  },
  reviewAdminAlert: (alertId: number, body: { status: 'acknowledged' | 'dismissed'; note: string }) =>
    request<SecurityAlert>(`/api/admin/alerts/${alertId}/review`, json(body)),
  getAdminAccessLog: (params: { case_id?: string; action?: string; allowed?: string } = {}) => {
    const sp = new URLSearchParams();
    if (params.case_id) sp.set('case_id', params.case_id);
    if (params.action) sp.set('action', params.action);
    if (params.allowed !== undefined && params.allowed !== '') sp.set('allowed', params.allowed);
    return request<PaginatedResponse<AccessLogRow>>(`/api/admin/access-log?${sp}`);
  },
  getAdminUsers: () => request<AdminUser[]>('/api/admin/users'),
  createAdminUser: (body: {
    email: string;
    display_name: string;
    role: 'viewer' | 'investigator' | 'admin';
    badge_number?: string;
    phone?: string;
    is_demo?: boolean;
    password?: string;
  }) => request<AdminUser>('/api/admin/users', json(body)),
  updateAdminUser: (userId: string, body: { role?: 'viewer' | 'investigator' | 'admin'; active?: boolean }) =>
    request<AdminUser>(`/api/admin/users/${enc(userId)}`, json(body)),
  assignCaseMember: (body: { user_id: string; case_id: string; access_level: 'viewer' | 'editor' }) =>
    request<Record<string, any>>('/api/admin/case-members', json(body)),
  removeCaseMember: (body: { user_id: string; case_id: string; access_level: 'viewer' | 'editor' }) =>
    request<{ removed: boolean }>('/api/admin/case-members/remove', json(body)),
  runConflictCheck: (raiseAlerts = false) =>
    request<{ conflicts: ConflictItem[]; checked_users: number; rule: string }>(`/api/admin/conflicts?raise_alerts=${raiseAlerts}`),
  getAdminSettings: () => request<AdminSettingsResponse>('/api/admin/settings'),
  saveAlertRules: (rules: AdminSettingsResponse['alert_rules']) =>
    request<AdminSettingsResponse>('/api/admin/settings/alert-rules', json(rules)),
  saveSmtpSettings: (smtp: Omit<AdminSettingsResponse['smtp'], 'password_configured' | 'password_source'>) =>
    request<AdminSettingsResponse>('/api/admin/settings/smtp', json(smtp)),
  testSmtpEmail: () => request<{ sent: boolean; to?: string[]; error?: string }>('/api/admin/settings/smtp/test', { method: 'POST' }),
};

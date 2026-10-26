import { fetchJson, getApiBase, getActiveTenantId, getTenantHeaders, isMockMode } from './apiClient';

const MOCK_MODE = import.meta.env.VITE_MOCK_MODE === 'true';
const ONBOARDING_KEY = 'capstone.phase3.onboarding';

export interface OnboardingSession {
  session_id: string;
  user_id: string;
  tenant_name: string;
  source_mode: 'synthetic' | 'live';
  status: string;
  steps: Record<string, Record<string, unknown>>;
  created_at: string;
}

export interface CandidateCause {
  cause_category: string;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  rule_id: string;
  supporting_evidence_keys: string[];
  contradicting_evidence_keys: string[];
}

export interface IncidentCase {
  rca_case_id: string;
  incident_id: string;
  tenant_id: string;
  entity_id: string;
  batch_ts: string;
  cloud_provider: string;
  region: string;
  final_score: number;
  severity: string;
  component_scores: Record<string, number>;
  changed_features: string[];
  behavioral_deviation: Record<string, unknown>;
  drift_evidence: Record<string, unknown>;
  similar_episodes: unknown[];
  related_incidents: string[];
  timeline: Array<Record<string, unknown>>;
  observed_window: Record<string, unknown>;
  baseline_window: Record<string, unknown>;
  unknowns: string[];
  candidate_causes: CandidateCause[];
  confidence: string;
  lifecycle_status?: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | string;
  regression_of?: string | null;
  recovering?: boolean;
}

export interface IncidentExplanation {
  rca_case_id: string;
  cause_category: string;
  headline: string;
  sections: Array<{ heading: string; body: string }>;
  kb_version: string;
  is_fallback: boolean;
  matched_threats: Array<{
    threat_id: string;
    title: string;
    match_confidence: string;
    matched_signals: string[];
    unmatched_signals: string[];
  }>;
  match_basis: string;
  mitigation_mode: 'threat_specific' | 'generic';
}

export interface RecommendedCheck {
  check: string;
  why: string;
  expected_result: string;
  risk: string;
}

export interface IncidentInvestigation {
  case: IncidentCase;
  explanation: IncidentExplanation;
  recommendations: RecommendedCheck[];
  notification_deliveries: Array<Record<string, unknown>>;
}

export interface IncidentLifecycle {
  incident_id: string;
  tenant_id: string;
  entity_id: string;
  status: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_type: string | null;
  resolution_note: string | null;
  regression_of: string | null;
  recovering: boolean;
}

export interface IncidentMitigation {
  incident_id: string;
  rca_case_id: string;
  cloud_provider: string;
  threat: { threat_id: string; title: string; match_confidence: string } | null;
  match_basis: string;
  mitigation_mode: 'threat_specific' | 'generic';
  is_retrospective: boolean;
  mitigation: {
    immediate: Array<{ text: string; provider_specific: boolean }>;
    short_term: Array<{ text: string; provider_specific: boolean }>;
    hardening: Array<{ text: string; provider_specific: boolean }>;
  };
  mitre_attack: Array<{ id: string; name: string; url: string }>;
  investigative_checks: RecommendedCheck[];
  resolution_criteria: string[];
  post_incident_review?: {
    promoted_phase: 'hardening';
    hardening: Array<{ text: string; provider_specific: boolean }>;
    resolution_record: { type: string | null; who: string | null; when: string | null; note: string | null };
  };
}

export interface ConnectionSummary {
  tenant_id: string;
  source_mode: string;
  connections: Array<{ provider: string; region: string; status: string; dry_run: boolean }>;
  notification_channels: Array<{ channel: string; status: string; detail: string }>;
}

const mockIncidents: Record<string, IncidentCase> = {
  'demo-high-confidence': {
    rca_case_id: 'rca-demo-high-confidence', incident_id: 'demo-high-confidence',
    tenant_id: 'google', entity_id: 'vol-g00g', batch_ts: '2026-10-09T09:42:00Z',
    cloud_provider: 'GCP', region: 'us-central1', final_score: 0.91, severity: 'CRITICAL',
    component_scores: { deviation: 0.88, drift: 0.71, similarity: 0.24 },
    changed_features: ['iam_policy_change', 'suspicious_login_location'],
    behavioral_deviation: { score: 0.88, entity_id: 'vol-g00g' }, drift_evidence: { score: 0.71 },
    similar_episodes: [], related_incidents: [],
    timeline: [{ event: 'alert_created', timestamp: '2026-10-09T09:42:00Z', severity: 'CRITICAL' }],
    observed_window: { duration: '15m', events: 184 }, baseline_window: { duration: '30d', events: 49212 },
    unknowns: [], confidence: 'HIGH',
    candidate_causes: [{ cause_category: 'BEHAVIOR_CHANGE', confidence: 'HIGH', rule_id: 'rca.behavior_change', supporting_evidence_keys: ['component_scores', 'behavioral_deviation'], contradicting_evidence_keys: [] }],
  },
  'demo-unknown': {
    rca_case_id: 'rca-demo-unknown', incident_id: 'demo-unknown',
    tenant_id: 'google', entity_id: 'vol-g00g', batch_ts: '2026-10-09T09:18:00Z',
    cloud_provider: 'GCP', region: 'us-central1', final_score: 0.42, severity: 'LOW',
    component_scores: { deviation: 0.31, drift: 0.22, similarity: 0.78 },
    changed_features: ['unclassified_metric_shift'], behavioral_deviation: { score: 0.31 },
    drift_evidence: { score: 0.22 }, similar_episodes: [], related_incidents: [],
    timeline: [{ event: 'alert_created', timestamp: '2026-10-09T09:18:00Z', severity: 'LOW' }],
    observed_window: { duration: '15m', events: 28 }, baseline_window: { duration: '30d', events: 50104 },
    unknowns: ['No hypothesis rule matched the observed evidence.'], confidence: 'LOW',
    candidate_causes: [{ cause_category: 'UNKNOWN', confidence: 'LOW', rule_id: 'rca.unknown', supporting_evidence_keys: [], contradicting_evidence_keys: ['component_scores'] }],
  },
  'demo-low-confidence': {
    rca_case_id: 'rca-demo-low-confidence', incident_id: 'demo-low-confidence',
    tenant_id: 'google', entity_id: 'vol-g00g', batch_ts: '2026-10-09T10:10:00Z',
    cloud_provider: 'GCP', region: 'us-central1', final_score: 0.53, severity: 'MEDIUM',
    component_scores: { deviation: 0.48, drift: 0.3, similarity: 0.61 },
    changed_features: ['metric_family:api_calls:increase'],
    behavioral_deviation: { score: 0.48 }, drift_evidence: { score: 0.3 },
    similar_episodes: [], related_incidents: [],
    timeline: [{ event: 'alert_created', timestamp: '2026-10-09T10:10:00Z', severity: 'MEDIUM' }],
    observed_window: { duration: '15m', events: 43 }, baseline_window: { duration: '30d', events: 49128 },
    unknowns: [], confidence: 'LOW',
    candidate_causes: [{ cause_category: 'BEHAVIOR_CHANGE', confidence: 'LOW', rule_id: 'rca.behavior_change', supporting_evidence_keys: ['changed_features'], contradicting_evidence_keys: [] }],
  },
};
mockIncidents['demo-resolved'] = {
  ...mockIncidents['demo-high-confidence'],
  rca_case_id: 'rca-demo-resolved',
  incident_id: 'demo-resolved',
  lifecycle_status: 'RESOLVED',
};
mockIncidents['demo-regression'] = {
  ...mockIncidents['demo-high-confidence'],
  rca_case_id: 'rca-demo-regression',
  incident_id: 'demo-regression',
  lifecycle_status: 'OPEN',
  regression_of: 'demo-high-confidence',
};
const mockLifecycleStates: Record<string, IncidentLifecycle> = {};
mockLifecycleStates['demo-resolved'] = {
  incident_id: 'demo-resolved',
  tenant_id: 'google',
  entity_id: 'vol-g00g',
  status: 'RESOLVED',
  acknowledged_at: '2026-10-10T10:00:00Z',
  resolved_at: '2026-10-10T10:30:00Z',
  resolved_by: 'demo-operator',
  resolution_type: 'FIXED',
  resolution_note: 'Credentials rotated and verified.',
  regression_of: null,
  recovering: false,
};
mockLifecycleStates['demo-regression'] = {
  incident_id: 'demo-regression',
  tenant_id: 'google',
  entity_id: 'vol-g00g',
  status: 'OPEN',
  acknowledged_at: null,
  resolved_at: null,
  resolved_by: null,
  resolution_type: null,
  resolution_note: null,
  regression_of: 'demo-high-confidence',
  recovering: false,
};

const mockExplanations: Record<string, IncidentExplanation> = {
  'demo-high-confidence': {
    rca_case_id: 'rca-demo-high-confidence', cause_category: 'BEHAVIOR_CHANGE', headline: 'Unusual behavioral change', kb_version: '2026.10.09', is_fallback: false,
    sections: [
      { heading: 'Summary', body: 'The observed activity differs substantially from this resource’s historical baseline.' },
      { heading: 'What this means', body: 'A resource is behaving differently from its established operating pattern.' },
      { heading: 'How it was detected', body: 'Behavioral deviation and drift scores exceeded configured thresholds.' },
      { heading: 'Common causes', body: 'Credential changes, new automation, or a workload migration can produce this pattern.' },
      { heading: 'Why it matters', body: 'Unexpected changes can signal misuse or an unreviewed operational change.' },
      { heading: 'Evidence for this case', body: 'IAM policy change and suspicious login location were observed in the same window.' },
      { heading: 'Limitations', body: 'This is contextual guidance, not a confirmed diagnosis.' },
    ],
    matched_threats: [{
      threat_id: 'cloud_credential_misuse', title: 'Possible cloud credential misuse',
      match_confidence: 'HIGH', matched_signals: ['changed_features.api_calls.increase'],
      unmatched_signals: [],
    }],
    match_basis: 'The observed API calls increased.',
    mitigation_mode: 'threat_specific',
  },
  'demo-unknown': {
    rca_case_id: 'rca-demo-unknown', cause_category: 'UNKNOWN', headline: 'No confident category', kb_version: '2026.10.09', is_fallback: true,
    sections: [
      { heading: 'Summary', body: 'No hypothesis rule matched this case; review the evidence before assigning a cause.' },
      { heading: 'What this means', body: 'The current evidence is insufficient to associate the event with a known cause category.' },
      { heading: 'How it was detected', body: 'The alert was produced by the anomaly score, but no RCA rule reached its evidence threshold.' },
      { heading: 'Common causes', body: 'A new workload pattern, sparse telemetry, or an unmodeled behavior may explain the signal.' },
      { heading: 'Why it matters', body: 'The signal remains visible for analyst review without overstating its meaning.' },
      { heading: 'Evidence for this case', body: 'Deviation 0.31, drift 0.22, and similarity 0.78.' },
      { heading: 'Limitations', body: 'No confident cause can be inferred from the available evidence.' },
    ],
    matched_threats: [],
    match_basis: '',
    mitigation_mode: 'generic',
  },
  'demo-low-confidence': {
    rca_case_id: 'rca-demo-low-confidence', cause_category: 'BEHAVIOR_CHANGE',
    headline: 'Behavioral drift', kb_version: '2026.10.09', is_fallback: false,
    sections: [
      { heading: 'Summary', body: 'The observed activity differs from this resource’s recent baseline.' },
      { heading: 'Limitations', body: 'A low-confidence signature is not a diagnosis; validate the evidence.' },
    ],
    matched_threats: [{
      threat_id: 'cloud_credential_misuse', title: 'Possible cloud credential misuse',
      match_confidence: 'LOW', matched_signals: ['changed_features.api_calls.increase'],
      unmatched_signals: ['changed_features.auth_failures.increase'],
    }],
    match_basis: 'The observed API calls increased.',
    mitigation_mode: 'generic',
  },
};

const mockRecommendations: Record<string, RecommendedCheck[]> = {
  'demo-high-confidence': [
    { check: 'Review recent IAM policy changes for the affected identity.', why: 'A policy change coincided with behavioral deviation.', expected_result: 'Confirm an authorized change or identify an unapproved permission grant.', risk: 'low' },
    { check: 'Validate the login location with the identity owner.', why: 'The observed location differs from the expected access pattern.', expected_result: 'Confirm whether the session was expected.', risk: 'low' },
  ],
  'demo-unknown': [
    { check: 'Compare the changed metric with the entity baseline window.', why: 'The current evidence does not map to a known cause.', expected_result: 'Determine whether the signal is persistent or transient.', risk: 'low' },
  ],
};

const mockMitigations: Record<string, IncidentMitigation> = {
  'demo-high-confidence': {
    incident_id: 'demo-high-confidence', rca_case_id: 'rca-demo-high-confidence',
    cloud_provider: 'GCP',
    threat: { threat_id: 'cloud_credential_misuse', title: 'Possible cloud credential misuse', match_confidence: 'HIGH' },
    match_basis: 'The observed API calls and authentication failures increased.',
    mitigation_mode: 'threat_specific', is_retrospective: false,
    mitigation: {
      immediate: [{ text: 'Your team can review Cloud Audit Logs and disable a confirmed exposed service-account key.', provider_specific: true }],
      short_term: [{ text: 'Consider IAM recommender findings and Cloud Audit Logs.', provider_specific: true }],
      hardening: [{ text: 'Consider workload identity federation and Security Command Center.', provider_specific: true }],
    },
    mitre_attack: [{ id: 'T1078.004', name: 'Cloud Accounts', url: 'https://attack.mitre.org/techniques/T1078/004/' }],
    investigative_checks: mockRecommendations['demo-high-confidence'],
    resolution_criteria: ['The identity and session are attributed.'],
  },
  'demo-low-confidence': {
    incident_id: 'demo-low-confidence', rca_case_id: 'rca-demo-low-confidence',
    cloud_provider: 'GCP',
    threat: null,
    match_basis: 'The observed API calls increased.',
    mitigation_mode: 'generic', is_retrospective: false,
    mitigation: { immediate: [], short_term: [], hardening: [] },
    mitre_attack: [],
    investigative_checks: mockRecommendations['demo-unknown'],
    resolution_criteria: [],
  },
  'demo-unknown': {
    incident_id: 'demo-unknown', rca_case_id: 'rca-demo-unknown',
    cloud_provider: 'GCP', threat: null, match_basis: '',
    mitigation_mode: 'generic', is_retrospective: false,
    mitigation: { immediate: [], short_term: [], hardening: [] },
    mitre_attack: [], investigative_checks: mockRecommendations['demo-unknown'],
    resolution_criteria: [],
  },
};

function mockSessions(): OnboardingSession[] {
  try {
    return JSON.parse(localStorage.getItem(ONBOARDING_KEY) || '[]') as OnboardingSession[];
  } catch {
    return [];
  }
}

function saveMockSession(session: OnboardingSession) {
  const sessions = mockSessions().filter((item) => item.session_id !== session.session_id);
  localStorage.setItem(ONBOARDING_KEY, JSON.stringify([...sessions, session]));
}

export async function startOnboarding(tenantName: string, sourceMode: 'synthetic' | 'live'): Promise<OnboardingSession> {
  if (MOCK_MODE) {
    const session: OnboardingSession = {
      session_id: `mock-${Date.now()}`, user_id: 'demo-user', tenant_name: tenantName,
      source_mode: sourceMode, status: 'in_progress', steps: {}, created_at: new Date().toISOString(),
    };
    saveMockSession(session);
    return session;
  }
  return fetchJson(`${getApiBase()}/onboarding`, {
    method: 'POST', body: JSON.stringify({ tenant_name: tenantName, source_mode: sourceMode }),
  });
}

export async function getOnboarding(sessionId: string): Promise<OnboardingSession> {
  if (MOCK_MODE) {
    const session = mockSessions().find((item) => item.session_id === sessionId);
    if (!session) throw new Error('Onboarding session not found');
    return session;
  }
  return fetchJson(`${getApiBase()}/onboarding/${encodeURIComponent(sessionId)}`);
}

export async function advanceOnboarding(sessionId: string, step: string, data: Record<string, unknown>, confirmLive = false): Promise<OnboardingSession> {
  if (MOCK_MODE) {
    const current = await getOnboarding(sessionId);
    const next = {
      ...current,
      status: step === 'enable_monitoring' ? 'complete' : 'in_progress',
      steps: { ...current.steps, [step]: data },
    };
    saveMockSession(next);
    return next;
  }
  return fetchJson(`${getApiBase()}/onboarding/${encodeURIComponent(sessionId)}/steps/${encodeURIComponent(step)}`, {
    method: 'POST',
    body: JSON.stringify({ payload: data, confirm_live: confirmLive }),
  });
}

export async function getConnections(): Promise<ConnectionSummary> {
  if (MOCK_MODE) {
    const tenantId = getActiveTenantId() || 'google';
    const providers: Record<string, [string, string]> = {
      google: ['GCP', 'us-central1'], microsoft: ['Azure', 'eastus'], amazon: ['AWS', 'us-east-1'],
      oracle: ['OCI', 'us-phoenix-1'], acme: ['AWS', 'us-west-2'],
    };
    const [provider, region] = providers[tenantId] || providers.google;
      return {
      tenant_id: tenantId,
      source_mode: 'synthetic',
      connections: [{ provider, region, status: 'synthetic', dry_run: true }],
      notification_channels: [
        { channel: 'PAGE', status: 'ready', detail: 'In-dashboard delivery' },
        { channel: 'EMAIL', status: 'credentials_required', detail: 'Gmail SMTP' },
        { channel: 'SLACK', status: 'simulated', detail: 'Demo response only' },
        { channel: 'SMS', status: 'credentials_required', detail: 'SMS provider credentials' },
        { channel: 'WEBHOOK', status: 'credentials_required', detail: 'Endpoint URL and signing secret' },
        { channel: 'PAGERDUTY', status: 'credentials_required', detail: 'PagerDuty routing key' },
      ],
    };
  }
  return fetchJson(`${getApiBase()}/connections`, { headers: getTenantHeaders() });
}

export async function getIncidents(): Promise<IncidentCase[]> {
  if (MOCK_MODE) {
    return Object.values(mockIncidents).map((incident) => ({
      ...incident,
      lifecycle_status: mockLifecycleStates[incident.incident_id]?.status
        || incident.lifecycle_status
        || 'OPEN',
      regression_of: mockLifecycleStates[incident.incident_id]?.regression_of
        ?? incident.regression_of
        ?? null,
    }));
  }
  return fetchJson(`${getApiBase()}/incidents`, { headers: getTenantHeaders() });
}

export async function getMembershipRole(): Promise<'OWNER' | 'OPERATOR' | 'VIEWER'> {
  if (isMockMode()) {
    const role = localStorage.getItem('capstone.role')?.toUpperCase();
    return role === 'OWNER' || role === 'VIEWER' ? role : 'OPERATOR';
  }
  const response = await fetchJson<{ role: string }>(`${getApiBase()}/membership/role`, {
    headers: getTenantHeaders(),
  });
  if (response.role !== 'OWNER' && response.role !== 'OPERATOR' && response.role !== 'VIEWER') {
    throw new Error(`Unexpected membership role: ${response.role}`);
  }
  return response.role;
}

export async function getIncident(incidentId: string): Promise<IncidentCase> {
  if (MOCK_MODE) return mockIncidents[incidentId] || mockIncidents['demo-unknown'];
  return fetchJson(`${getApiBase()}/incidents/${encodeURIComponent(incidentId)}`, { headers: getTenantHeaders() });
}

export async function getIncidentExplanation(incidentId: string): Promise<IncidentExplanation> {
  if (MOCK_MODE) {
    const key = incidentId === 'demo-resolved' || incidentId === 'demo-regression'
      ? 'demo-high-confidence'
      : incidentId;
    return mockExplanations[key] || mockExplanations['demo-unknown'];
  }
  return fetchJson(`${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/explanation`, { headers: getTenantHeaders() });
}

export async function getIncidentRecommendations(incidentId: string): Promise<RecommendedCheck[]> {
  if (MOCK_MODE) {
    const key = incidentId === 'demo-resolved' || incidentId === 'demo-regression'
      ? 'demo-high-confidence'
      : incidentId;
    return mockRecommendations[key] || mockRecommendations['demo-unknown'];
  }
  return fetchJson(`${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/recommendations`, { headers: getTenantHeaders() });
}

export async function getIncidentMitigation(incidentId: string): Promise<IncidentMitigation> {
  if (MOCK_MODE) {
    const key = incidentId === 'demo-resolved' || incidentId === 'demo-regression'
      ? 'demo-high-confidence'
      : incidentId;
    const mitigation = mockMitigations[key] || mockMitigations['demo-unknown'];
    const lifecycle = mockLifecycleStates[incidentId];
    if (lifecycle?.status !== 'RESOLVED') return { ...mitigation };
    return {
      ...mitigation,
      is_retrospective: true,
      post_incident_review: {
        promoted_phase: 'hardening',
        hardening: mitigation.mitigation.hardening,
        resolution_record: {
          type: lifecycle.resolution_type,
          who: lifecycle.resolved_by,
          when: lifecycle.resolved_at,
          note: lifecycle.resolution_note,
        },
      },
    };
  }
  return fetchJson(
    `${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/mitigation`,
    { headers: getTenantHeaders() },
  );
}

export async function getIncidentLifecycle(incidentId: string): Promise<IncidentLifecycle> {
  if (MOCK_MODE) {
    const cached = mockLifecycleStates[incidentId];
    if (cached) return cached;
    const incident = await getIncident(incidentId);
    return {
      incident_id: incidentId,
      tenant_id: incident.tenant_id,
      entity_id: incident.entity_id,
      status: 'OPEN',
      acknowledged_at: null,
      resolved_at: null,
      resolved_by: null,
      resolution_type: null,
      resolution_note: null,
      regression_of: null,
      recovering: false,
    };
  }
  return fetchJson(
    `${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/lifecycle`,
    { headers: getTenantHeaders() },
  );
}

export async function acknowledgeIncident(incidentId: string): Promise<IncidentLifecycle> {
  if (MOCK_MODE) {
    const state = await getIncidentLifecycle(incidentId);
    const next = { ...state, status: 'ACKNOWLEDGED', acknowledged_at: new Date().toISOString() };
    mockLifecycleStates[incidentId] = next;
    return next;
  }
  return fetchJson(
    `${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/acknowledge`,
    { method: 'POST', headers: getTenantHeaders() },
  );
}

export async function resolveIncident(
  incidentId: string,
  resolutionType: 'FIXED' | 'FALSE_POSITIVE' | 'EXPECTED_CHANGE' | 'AUTO_RECOVERED',
  note: string,
): Promise<IncidentLifecycle> {
  if (MOCK_MODE) {
    const state = await getIncidentLifecycle(incidentId);
    const next = {
      ...state,
      status: 'RESOLVED',
      resolved_at: new Date().toISOString(),
      resolved_by: 'demo-user',
      resolution_type: resolutionType,
      resolution_note: note,
    };
    mockLifecycleStates[incidentId] = next;
    return next;
  }
  return fetchJson(
    `${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/resolve`,
    {
      method: 'POST',
      headers: getTenantHeaders(),
      body: JSON.stringify({ resolution_type: resolutionType, note }),
    },
  );
}

export async function reopenIncident(incidentId: string): Promise<IncidentLifecycle> {
  if (MOCK_MODE) {
    const state = await getIncidentLifecycle(incidentId);
    const next = {
      ...state,
      status: 'OPEN',
      acknowledged_at: null,
      resolved_at: null,
      resolved_by: null,
      resolution_type: null,
      resolution_note: null,
    };
    mockLifecycleStates[incidentId] = next;
    return next;
  }
  return fetchJson(
    `${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/reopen`,
    { method: 'POST', headers: getTenantHeaders() },
  );
}

export async function getIncidentInvestigation(incidentId: string): Promise<IncidentInvestigation> {
  if (MOCK_MODE) {
    return {
      case: await getIncident(incidentId),
      explanation: await getIncidentExplanation(incidentId),
      recommendations: await getIncidentRecommendations(incidentId),
      notification_deliveries: [],
    };
  }
  return fetchJson<IncidentInvestigation>(
    `${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/investigation`,
    { headers: getTenantHeaders() },
  );
}

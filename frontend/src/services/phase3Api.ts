import { fetchJson, getApiBase, getActiveTenantId, getTenantHeaders } from './apiClient';

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
}

export interface IncidentExplanation {
  rca_case_id: string;
  cause_category: string;
  headline: string;
  sections: Array<{ heading: string; body: string }>;
  kb_version: string;
  is_fallback: boolean;
}

export interface RecommendedCheck {
  check: string;
  why: string;
  expected_result: string;
  risk: string;
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
      oracle: ['OCI', 'us-phoenix-1'], openai: ['AWS', 'us-west-2'],
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
  if (MOCK_MODE) return Object.values(mockIncidents);
  return fetchJson(`${getApiBase()}/incidents`, { headers: getTenantHeaders() });
}

export async function getIncident(incidentId: string): Promise<IncidentCase> {
  if (MOCK_MODE) return mockIncidents[incidentId] || mockIncidents['demo-unknown'];
  return fetchJson(`${getApiBase()}/incidents/${encodeURIComponent(incidentId)}`, { headers: getTenantHeaders() });
}

export async function getIncidentExplanation(incidentId: string): Promise<IncidentExplanation> {
  if (MOCK_MODE) return mockExplanations[incidentId] || mockExplanations['demo-unknown'];
  return fetchJson(`${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/explanation`, { headers: getTenantHeaders() });
}

export async function getIncidentRecommendations(incidentId: string): Promise<RecommendedCheck[]> {
  if (MOCK_MODE) return mockRecommendations[incidentId] || mockRecommendations['demo-unknown'];
  return fetchJson(`${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/recommendations`, { headers: getTenantHeaders() });
}

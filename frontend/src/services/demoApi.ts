import { getActiveTenantId, getTenantHeaders, isMockMode } from './apiClient';
import type { AlertPayload } from '../types/contracts';
import { getIncidentInvestigation } from './phase3Api';
import type { IncidentExplanation, RecommendedCheck } from './phase3Api';
import { MOCK_TENANTS } from './mockData';

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8001";
// expose for debugging in the browser console
console.info('[demoApi] API_BASE =', API_BASE);
let mockDemoPaused = false;
let mockActiveAlerts = 1;

const MOCK_SCENARIOS: DemoScenario[] = [
  {
    value: 'credential_theft',
    label: 'Credential misuse',
    description: 'Unusual access patterns consistent with a credential being used from a new context.',
    category: 'malicious',
    default_notify_method: 'PAGE',
    severity: 'CRITICAL',
    minimum_severity: 'HIGH',
    providers: ['AWS', 'Azure', 'GCP', 'OCI'],
    entity_types: ['compute_instance'],
    signature: [],
  },
  {
    value: 'planned_deployment',
    label: 'Planned deployment',
    description: 'A routine workload rollout that creates a measurable but expected change.',
    category: 'benign',
    default_notify_method: 'SLACK',
    severity: 'LOW',
    minimum_severity: 'LOW',
    providers: ['AWS', 'Azure', 'GCP', 'OCI'],
    entity_types: ['compute_instance'],
    signature: [],
  },
  {
    value: 'ambiguous_activity',
    label: 'Ambiguous activity',
    description: 'A synthetic change without enough evidence to support a confident category.',
    category: 'ambiguous',
    default_notify_method: 'PAGE',
    severity: 'MEDIUM',
    minimum_severity: 'LOW',
    providers: ['AWS', 'Azure', 'GCP', 'OCI'],
    entity_types: ['compute_instance'],
    signature: [],
  },
];

export interface DemoTenant {
  id: string;
  name: string;
  live_alert_count: number;
  health: string;
}

export interface DemoScenario {
  value: string;
  label: string;
  description: string;
  category: 'malicious' | 'benign' | 'ambiguous';
  default_notify_method: string;
  severity: string;
  minimum_severity: string;
  providers: string[];
  entity_types: string[];
  signature: Array<{
    metric_family: string;
    direction: 'increase' | 'decrease';
    magnitude: number;
    shape: 'step' | 'ramp' | 'spike';
    duration_minutes: number;
  }>;
}

export type NotifyMethod = 'PAGE' | 'SLACK' | 'EMAIL';

export interface DemoAlertResponse {
  status: string;
  tenant_id: string;
  notify_method: NotifyMethod;
  notification?: DemoNotification;
  alert_payload: AlertPayload;
  heartbeat: Record<string, unknown>;
  phase3: {
    rca_case_id: string;
    candidate_causes: Array<{ cause_category: string; confidence: string; rule_id: string }>;
    confidence: string;
    notification_deliveries: Array<Record<string, unknown>>;
    explanation: IncidentExplanation;
    recommendations: RecommendedCheck[];
  };
}

export interface DemoNotification {
  notify_method: string;
  status: string;
  message: string;
  email_to?: string;
}

export interface DemoStatusResponse {
  tenant_id: string;
  paused: boolean;
  active_alerts: number;
}

export interface SummaryPayload {
  model_confidence: number;
  critical_alerts: number;
  [key: string]: unknown;
}

export async function getDemoTenants(): Promise<DemoTenant[]> {
  if (isMockMode()) return MOCK_TENANTS;
  const res = await fetch(`${API_BASE}/tenants`);
  if (!res.ok) throw new Error(`Tenants API error: ${res.status}`);
  return res.json();
}

export async function getSummary(): Promise<SummaryPayload> {
  if (isMockMode()) {
    return {
      active_alerts: mockActiveAlerts,
      active_incidents: mockActiveAlerts,
      critical_alerts: mockActiveAlerts,
      event_volume: 184,
      model_confidence: 0.91,
      mean_time_to_resolve_minutes: 18,
      resolved_today: 2,
    };
  }
  const res = await fetch(`${API_BASE}/stats/summary`, {
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Stats API error: ${res.status}`);
  return res.json();
}

export async function getDemoScenarios(): Promise<DemoScenario[]> {
  if (isMockMode()) return MOCK_SCENARIOS;
  const res = await fetch(`${API_BASE}/demo/scenarios`);
  if (!res.ok) throw new Error(`Scenarios API error: ${res.status}`);
  return res.json();
}

export async function getNotifyMethods(): Promise<NotifyMethod[]> {
  if (isMockMode()) return ['PAGE', 'SLACK', 'EMAIL'];
  const res = await fetch(`${API_BASE}/demo/notify-methods`);
  if (!res.ok) throw new Error(`Notify methods API error: ${res.status}`);
  return res.json();
}

export async function triggerDemoAlert(
  tenant_id: string,
  scenario: string,
  notify_method: NotifyMethod,
  cloud_provider: string,
  intensity: 'low' | 'medium' | 'high',
): Promise<DemoAlertResponse> {
  if (isMockMode()) {
    const investigation = await getIncidentInvestigation('demo-high-confidence');
    const now = new Date().toISOString();
    const alertPayload: AlertPayload = {
      alert_id: `mock-${Date.now()}`,
      entity_id: investigation.case.entity_id,
      batch_ts: now,
      final_score: investigation.case.final_score,
      severity: investigation.case.severity as AlertPayload['severity'],
      sev_level: 'SEV1',
      deviation_score: Number(investigation.case.component_scores.deviation || 0),
      drift_score: Number(investigation.case.component_scores.drift || 0),
      similarity_score: Number(investigation.case.component_scores.similarity || 0),
      similar_episodes: [],
      related_ids: [],
      group_type: 'ISOLATED',
      target_team: 'cloud-security',
      notify_method,
      cloud_provider,
      region: investigation.case.region,
    };
    mockActiveAlerts += 1;
    return {
      status: 'success',
      tenant_id,
      notify_method,
      notification: {
        notify_method,
        status: 'sent',
        message: `Mock ${notify_method.toLowerCase()} notification sent`,
        email_to: notify_method === 'EMAIL' ? 'operator@example.test' : undefined,
      },
      alert_payload: alertPayload,
      heartbeat: { status: 'connected', timestamp: now },
      phase3: {
        rca_case_id: investigation.case.rca_case_id,
        candidate_causes: investigation.case.candidate_causes.map((cause) => ({
          cause_category: cause.cause_category,
          confidence: cause.confidence,
          rule_id: cause.rule_id,
        })),
        confidence: investigation.case.confidence,
        notification_deliveries: [],
        explanation: investigation.explanation,
        recommendations: investigation.recommendations,
      },
    };
  }
  const res = await fetch(`${API_BASE}/demo/generate/alert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getTenantHeaders() },
    body: JSON.stringify({ tenant_id, scenario, notify_method, cloud_provider, intensity }),
  });
  if (!res.ok) throw new Error(`Demo API error: ${res.status}`);
  return res.json();
}

export async function triggerDemoScenario(tenant_id: string, scenario: string) {
  const res = await fetch(`${API_BASE}/demo/generate/attack`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getTenantHeaders() },
    body: JSON.stringify({ tenant_id, scenario }),
  });
  if (!res.ok) throw new Error(`Demo API error: ${res.status}`);
  return res.json();
}

export async function getDemoStatus(): Promise<DemoStatusResponse> {
  if (isMockMode()) {
    return {
      tenant_id: getActiveTenantId() || 'google',
      paused: mockDemoPaused,
      active_alerts: mockActiveAlerts,
    };
  }
  const res = await fetch(`${API_BASE}/demo/status`, {
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Demo status API error: ${res.status}`);
  return res.json();
}

export async function pauseDemo(): Promise<DemoStatusResponse> {
  if (isMockMode()) {
    mockDemoPaused = true;
    return getDemoStatus();
  }
  const res = await fetch(`${API_BASE}/demo/pause`, {
    method: 'POST',
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Demo pause API error: ${res.status}`);
  return res.json();
}

export async function resumeDemo(): Promise<DemoStatusResponse> {
  if (isMockMode()) {
    mockDemoPaused = false;
    return getDemoStatus();
  }
  const res = await fetch(`${API_BASE}/demo/resume`, {
    method: 'POST',
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Demo resume API error: ${res.status}`);
  return res.json();
}

export async function resetDemo(): Promise<DemoStatusResponse> {
  if (isMockMode()) {
    mockActiveAlerts = 0;
    mockDemoPaused = false;
    return getDemoStatus();
  }
  const res = await fetch(`${API_BASE}/demo/reset`, {
    method: 'POST',
    headers: getTenantHeaders(),
  });
  if (!res.ok) throw new Error(`Demo reset API error: ${res.status}`);
  return res.json();
}

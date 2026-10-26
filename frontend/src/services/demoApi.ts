import { fetchJson, getActiveTenantId, getApiBase, isMockMode } from './apiClient';
import type { AlertPayload } from '../types/contracts';
import { getIncidentInvestigation } from './phase3Api';
import type { IncidentExplanation, RecommendedCheck } from './phase3Api';
import { MOCK_TENANTS } from './mockData';
import { publishLocalAlert } from './notificationBus';
import { getTenants } from './tenantsApi';

const API_BASE = getApiBase();
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
  // Only the workspaces the signed-in user belongs to.
  return getTenants();
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
  return fetchJson<SummaryPayload>(`${API_BASE}/stats/summary`);
}

export async function getDemoScenarios(): Promise<DemoScenario[]> {
  if (isMockMode()) return MOCK_SCENARIOS;
  return fetchJson<DemoScenario[]>(`${API_BASE}/demo/scenarios`);
}

export async function getNotifyMethods(): Promise<NotifyMethod[]> {
  if (isMockMode()) return ['PAGE', 'SLACK', 'EMAIL'];
  return fetchJson<NotifyMethod[]>(`${API_BASE}/demo/notify-methods`);
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
    publishLocalAlert({ type: 'alert', tenant_id, payload: alertPayload });
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
  return fetchJson<DemoAlertResponse>(`${API_BASE}/demo/generate/alert`, {
    method: 'POST',
    body: JSON.stringify({ tenant_id, scenario, notify_method, cloud_provider, intensity }),
  });
}

export async function triggerDemoScenario(tenant_id: string, scenario: string) {
  return fetchJson<DemoAlertResponse>(`${API_BASE}/demo/generate/attack`, {
    method: 'POST',
    body: JSON.stringify({ tenant_id, scenario }),
  });
}

export async function getDemoStatus(): Promise<DemoStatusResponse> {
  if (isMockMode()) {
    return {
      tenant_id: getActiveTenantId() || 'google',
      paused: mockDemoPaused,
      active_alerts: mockActiveAlerts,
    };
  }
  return fetchJson<DemoStatusResponse>(`${API_BASE}/demo/status`);
}

export async function pauseDemo(): Promise<DemoStatusResponse> {
  if (isMockMode()) {
    mockDemoPaused = true;
    return getDemoStatus();
  }
  return fetchJson<DemoStatusResponse>(`${API_BASE}/demo/pause`, { method: 'POST' });
}

export async function resumeDemo(): Promise<DemoStatusResponse> {
  if (isMockMode()) {
    mockDemoPaused = false;
    return getDemoStatus();
  }
  return fetchJson<DemoStatusResponse>(`${API_BASE}/demo/resume`, { method: 'POST' });
}

export async function resetDemo(): Promise<DemoStatusResponse> {
  if (isMockMode()) {
    mockActiveAlerts = 0;
    mockDemoPaused = false;
    return getDemoStatus();
  }
  return fetchJson<DemoStatusResponse>(`${API_BASE}/demo/reset`, { method: 'POST' });
}

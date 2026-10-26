import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import IncidentPage from './[incidentId]/page';
import type { IncidentCase, IncidentExplanation, IncidentInvestigation } from '../../services/phase3Api';

const api = vi.hoisted(() => ({
  getIncidentInvestigation: vi.fn(),
  getIncidentMitigation: vi.fn(),
  getIncidentLifecycle: vi.fn(),
  getMembershipRole: vi.fn(),
  acknowledgeIncident: vi.fn(),
  resolveIncident: vi.fn(),
  reopenIncident: vi.fn(),
}));

vi.mock('../../services/phase3Api', () => api);

const incident: IncidentCase = {
  rca_case_id: 'rca-demo',
  incident_id: 'incident-demo',
  tenant_id: 'tenant-demo',
  entity_id: 'entity-demo',
  batch_ts: '2026-10-12T10:00:00Z',
  cloud_provider: 'AWS',
  region: 'us-east-1',
  final_score: 0.91,
  severity: 'HIGH',
  component_scores: { deviation: 0.9 },
  changed_features: ['policy_change'],
  behavioral_deviation: {},
  drift_evidence: {},
  similar_episodes: [],
  related_incidents: [],
  timeline: [],
  observed_window: {},
  baseline_window: {},
  unknowns: [],
  candidate_causes: [{
    cause_category: 'BEHAVIOR_CHANGE',
    confidence: 'HIGH',
    rule_id: 'rca.behavior_change',
    supporting_evidence_keys: ['component_scores'],
    contradicting_evidence_keys: [],
  }],
  confidence: 'HIGH',
};

const highConfidenceExplanation: IncidentExplanation = {
  rca_case_id: incident.rca_case_id,
  cause_category: 'BEHAVIOR_CHANGE',
  headline: 'Unusual behavioral change',
  kb_version: '2026.10.09',
  is_fallback: false,
  matched_threats: [{
    threat_id: 'credential_theft',
    title: 'Possible cloud credential misuse',
    match_confidence: 'HIGH',
    matched_signals: ['API calls increased', 'Authentication failures increased'],
    unmatched_signals: [],
  }],
  match_basis: 'API calls and authentication failures increased together.',
  mitigation_mode: 'threat_specific',
  sections: [
    { heading: 'Summary', body: 'The resource differs from its baseline.' },
    { heading: 'What this means', body: 'The operating pattern changed.' },
    { heading: 'How it was detected', body: 'Deviation exceeded its threshold.' },
    { heading: 'Common causes', body: 'A policy change may explain this.' },
    { heading: 'Why it matters', body: 'Unexpected changes need review.' },
    { heading: 'Evidence for this case', body: 'A policy change was observed.' },
    { heading: 'Limitations', body: 'This is guidance, not a diagnosis.' },
  ],
};

const highConfidenceInvestigation: IncidentInvestigation = {
  case: incident,
  explanation: highConfidenceExplanation,
  recommendations: [],
  notification_deliveries: [],
};

function renderIncident(incidentId = 'demo-high-confidence') {
  return render(
    <MemoryRouter initialEntries={[`/incidents/${incidentId}`]}>
      <Routes>
        <Route path="/incidents/:incidentId" element={<IncidentPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('IncidentPage RCA explanation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getIncidentInvestigation.mockResolvedValue(highConfidenceInvestigation);
    api.getIncidentMitigation.mockResolvedValue({
      incident_id: incident.incident_id, rca_case_id: incident.rca_case_id,
      cloud_provider: 'GCP',
      threat: { threat_id: 'credential_theft', title: 'Possible cloud credential misuse', match_confidence: 'HIGH' },
      match_basis: highConfidenceExplanation.match_basis,
      mitigation_mode: 'threat_specific', is_retrospective: false,
      mitigation: {
        immediate: [{ text: 'Review recent identity sessions.', provider_specific: false }],
        short_term: [{ text: 'Validate GCP identity audit events.', provider_specific: true }],
        hardening: [],
      },
      mitre_attack: [{
        id: 'T1078.004',
        name: 'Cloud Accounts',
        url: 'https://attack.mitre.org/techniques/T1078/004/',
      }],
      investigative_checks: [],
      resolution_criteria: [],
    });
    api.getIncidentLifecycle.mockResolvedValue({
      incident_id: incident.incident_id,
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
    });
    api.getMembershipRole.mockResolvedValue('OPERATOR');
  });

  it('renders all structured sections and the knowledge-base version for high confidence', async () => {
    renderIncident();
    await screen.findByText('entity-demo');
    expect(api.getIncidentInvestigation).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('tab', { name: 'Explanation' }));

    expect(screen.getByRole('heading', { name: highConfidenceExplanation.headline })).toBeInTheDocument();
    for (const section of highConfidenceExplanation.sections) {
      expect(screen.getByRole('heading', { name: section.heading })).toBeInTheDocument();
      expect(screen.getByText(section.body)).toBeInTheDocument();
    }
    expect(screen.getByText(/Knowledge base 2026\.10\.09/)).toBeInTheDocument();
  });

  it('shows an explicit fallback state and the UNKNOWN explanation instead of a blank panel', async () => {
    const fallbackExplanation: IncidentExplanation = {
      ...highConfidenceExplanation,
      cause_category: 'UNKNOWN',
      headline: 'No confident category',
      is_fallback: true,
      sections: [{
        heading: 'Summary',
        body: 'No hypothesis matched; review the available evidence.',
      }],
    };
    api.getIncidentInvestigation.mockResolvedValue({
      ...highConfidenceInvestigation,
      explanation: fallbackExplanation,
    });

    renderIncident('demo-unknown');
    await screen.findByText('entity-demo');

    expect(screen.getByRole('status')).toHaveTextContent('No confident category');
    fireEvent.click(screen.getByRole('tab', { name: 'Explanation' }));
    expect(screen.getByRole('heading', { name: 'No confident category' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Summary' })).toBeInTheDocument();
    expect(screen.getByText('No hypothesis matched; review the available evidence.')).toBeInTheDocument();
  });

  it('labels a low-confidence threat as generic guidance, not a threat-specific match', async () => {
    api.getIncidentInvestigation.mockResolvedValue({
      ...highConfidenceInvestigation,
      explanation: {
        ...highConfidenceExplanation,
        mitigation_mode: 'generic',
        matched_threats: [{
          threat_id: 'cloud_credential_misuse',
          title: 'Possible cloud credential misuse',
          match_confidence: 'LOW',
          matched_signals: ['changed_features.api_calls.increase'],
          unmatched_signals: ['changed_features.auth_failures.increase'],
        }],
        match_basis: 'API calls increased without a corresponding authentication-failure signal.',
      },
    });
    api.getIncidentMitigation.mockResolvedValue({
      incident_id: incident.incident_id,
      rca_case_id: incident.rca_case_id,
      cloud_provider: 'AWS',
      threat: null,
      match_basis: '',
      mitigation_mode: 'generic',
      is_retrospective: false,
      mitigation: { immediate: [], short_term: [], hardening: [] },
      mitre_attack: [],
      investigative_checks: [],
      resolution_criteria: [],
    });

    renderIncident('demo-low-confidence');
    await screen.findByText('entity-demo');
    fireEvent.click(screen.getByRole('tab', { name: 'Explanation' }));
    expect(screen.getByText(/generic cause-category guidance/)).toBeInTheDocument();
    expect(screen.getByText('LOW')).toBeInTheDocument();
  });

  it('renders explanation text as escaped text rather than markup', async () => {
    const unsafeText = '<img src=x onerror=alert(1)>';
    api.getIncidentInvestigation.mockResolvedValue({
      ...highConfidenceInvestigation,
      explanation: {
        ...highConfidenceExplanation,
        sections: [{ heading: 'Evidence for this case', body: unsafeText }],
      },
    });
    const { container } = renderIncident();
    await screen.findByText('entity-demo');
    fireEvent.click(screen.getByRole('tab', { name: 'Explanation' }));

    expect(screen.getByText(unsafeText)).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
    expect(container.innerHTML).toContain('&lt;img');
  });

  it('shows threat-specific confidence, match basis, provider steps, and verified ATT&CK links', async () => {
    renderIncident();
    await screen.findByText('entity-demo');
    // The matched pattern sits beside the RCA change type instead of replacing it.
    const patternCard = screen.getByText('Matched pattern').closest('section') as HTMLElement;
    expect(within(patternCard).getByText('Possible cloud credential misuse')).toBeInTheDocument();
    expect(screen.getByText('Root cause category').closest('section')).toHaveTextContent(/behavior change/i);
    fireEvent.click(screen.getByRole('tab', { name: 'Explanation' }));
    const matches = screen.getByRole('region', { name: 'Threat signature matches' });
    expect(within(matches).getByText('Possible cloud credential misuse')).toBeInTheDocument();
    expect(within(matches).getByText(/API calls increased, Authentication failures increased/)).toBeInTheDocument();
    expect(screen.getAllByText('HIGH').length).toBeGreaterThan(1);
    expect(screen.getByText(highConfidenceExplanation.match_basis)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Mitigation' }));
    expect(screen.getByText(/guidance for your cloud team/i)).toBeInTheDocument();
    expect(screen.getByText('GCP specific')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /T1078\.004 · Cloud Accounts/ })).toHaveAttribute(
      'href',
      'https://attack.mitre.org/techniques/T1078/004/',
    );
  });

  it('renders multi-line knowledge sections as lists with safe links', async () => {
    api.getIncidentInvestigation.mockResolvedValue({
      ...highConfidenceInvestigation,
      explanation: {
        ...highConfidenceExplanation,
        sections: [
          { heading: 'Investigative checks', body: '1. Review the audit record.\n2. Compare the session.' },
          { heading: 'Further reading', body: 'Cloud Accounts — https://attack.mitre.org/techniques/T1078/004/\njavascript:alert(1)' },
        ],
      },
    });
    renderIncident();
    await screen.findByText('entity-demo');
    fireEvent.click(screen.getByRole('tab', { name: 'Explanation' }));

    const checks = screen.getByRole('heading', { name: 'Investigative checks' }).closest('article') as HTMLElement;
    const items = within(checks).getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual(['Review the audit record.', 'Compare the session.']);
    expect(checks.querySelector('ol')).not.toBeNull();

    const reading = screen.getByRole('heading', { name: 'Further reading' }).closest('article') as HTMLElement;
    expect(within(reading).getByRole('link')).toHaveAttribute('href', 'https://attack.mitre.org/techniques/T1078/004/');
    expect(within(reading).getAllByRole('link')).toHaveLength(1);
    expect(within(reading).getByText('javascript:alert(1)')).toBeInTheDocument();
  });

  it('requires the operator to confirm resolution criteria before resolving', async () => {
    api.getIncidentMitigation.mockResolvedValue({
      incident_id: incident.incident_id,
      rca_case_id: incident.rca_case_id,
      cloud_provider: 'AWS',
      threat: { threat_id: 'credential_misuse', title: 'Possible credential misuse', match_confidence: 'HIGH' },
      match_basis: 'API calls and authentication failures rose together.',
      mitigation_mode: 'threat_specific',
      is_retrospective: false,
      mitigation: { immediate: [], short_term: [], hardening: [] },
      mitre_attack: [],
      investigative_checks: [],
      resolution_criteria: ['Identity attributed', 'Credential rotation verified'],
    });
    api.resolveIncident.mockResolvedValue({
      incident_id: incident.incident_id,
      tenant_id: incident.tenant_id,
      entity_id: incident.entity_id,
      status: 'RESOLVED',
      acknowledged_at: null,
      resolved_at: '2026-10-14T10:00:00Z',
      resolved_by: 'operator-demo',
      resolution_type: 'FIXED',
      resolution_note: 'Credential rotated.',
      regression_of: null,
      recovering: false,
    });

    renderIncident();
    await screen.findByText('entity-demo');
    fireEvent.click(screen.getByRole('button', { name: 'Resolve incident' }));
    const confirm = screen.getByRole('button', { name: 'Confirm resolution' });
    expect(confirm).toBeDisabled();

    fireEvent.click(screen.getByLabelText('Identity attributed'));
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Credential rotation verified'));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    expect(await screen.findByText('RESOLVED')).toBeInTheDocument();
    expect(api.resolveIncident).toHaveBeenCalledWith('demo-high-confidence', 'FIXED', '');
    expect(api.getIncidentMitigation).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('hides lifecycle actions for viewers', async () => {
    api.getMembershipRole.mockResolvedValue('VIEWER');
    api.getIncidentLifecycle.mockResolvedValue({
      incident_id: incident.incident_id,
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
    });

    renderIncident();
    await screen.findByText('entity-demo');
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resolve incident' })).not.toBeInTheDocument();
    expect(screen.getByText(/Viewer access is read-only/)).toBeInTheDocument();
  });

  it('shows a resolved post-incident review and links a regression to its original', async () => {
    api.getIncidentLifecycle.mockResolvedValue({
      incident_id: 'demo-resolved',
      tenant_id: incident.tenant_id,
      entity_id: incident.entity_id,
      status: 'RESOLVED',
      acknowledged_at: null,
      resolved_at: '2026-10-14T10:00:00Z',
      resolved_by: 'operator-demo',
      resolution_type: 'FIXED',
      resolution_note: 'Credential rotated.',
      regression_of: null,
      recovering: false,
    });
    api.getIncidentMitigation.mockResolvedValue({
      incident_id: incident.incident_id,
      rca_case_id: incident.rca_case_id,
      cloud_provider: 'AWS',
      threat: null,
      match_basis: '',
      mitigation_mode: 'generic',
      is_retrospective: true,
      mitigation: { immediate: [], short_term: [], hardening: [] },
      mitre_attack: [],
      investigative_checks: [],
      resolution_criteria: [],
      post_incident_review: {
        promoted_phase: 'hardening',
        hardening: [],
        resolution_record: {
          type: 'FIXED',
          who: 'operator-demo',
          when: '2026-10-14T10:00:00Z',
          note: 'Credential rotated.',
        },
      },
    });

    renderIncident('demo-resolved');
    await screen.findByText('entity-demo');
    expect(screen.getByText('RESOLVED')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Mitigation' }));
    expect(screen.getByText('Post-incident review (retrospective)')).toBeInTheDocument();
    expect(screen.getAllByText(/Credential rotated\./).length).toBeGreaterThan(1);
    expect(screen.getByRole('button', { name: 'Reopen' })).toBeInTheDocument();

    cleanup();
    api.getIncidentLifecycle.mockResolvedValue({
      incident_id: 'demo-regression',
      tenant_id: incident.tenant_id,
      entity_id: incident.entity_id,
      status: 'OPEN',
      acknowledged_at: null,
      resolved_at: null,
      resolved_by: null,
      resolution_type: null,
      resolution_note: null,
      regression_of: 'demo-high-confidence',
      recovering: false,
    });
    renderIncident('demo-regression');
    await screen.findByText('entity-demo');
    expect(screen.getByText('Regression')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'demo-high-confidence' })).toHaveAttribute(
      'href',
      '/incidents/demo-high-confidence',
    );
  });
});

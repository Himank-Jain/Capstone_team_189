import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  acknowledgeIncident,
  getIncidentInvestigation,
  getIncidentLifecycle,
  getIncidentMitigation,
  getMembershipRole,
  IncidentCase,
  IncidentExplanation,
  IncidentLifecycle,
  IncidentMitigation,
  RecommendedCheck,
  reopenIncident,
  resolveIncident,
} from '../../../services/phase3Api';
import {
  Button,
  Card,
  ConfirmDialog,
  ConfidenceBadge,
  EmptyState,
  FormField,
  PageHeader,
  SeverityBadge,
  Skeleton,
  StatusBadge,
  Tabs,
  Toast,
} from '../../../components/ui';

type IncidentTab = 'Evidence' | 'Timeline' | 'Causes' | 'Explanation' | 'Checks' | 'Mitigation' | 'Response';
type IncidentResolutionType = 'FIXED' | 'FALSE_POSITIVE' | 'EXPECTED_CHANGE' | 'AUTO_RECOVERED';
const TABS: IncidentTab[] = ['Evidence', 'Timeline', 'Causes', 'Explanation', 'Checks', 'Mitigation', 'Response'];

function isVerifiedMitreReference(item: { id: string; url: string }): boolean {
  return /^T\d{4}(?:\.\d{3})?$/.test(item.id)
    && item.url === `https://attack.mitre.org/techniques/${item.id.replace('.', '/')}/`;
}

export default function IncidentPage() {
  const { incidentId = '' } = useParams();
  const [incident, setIncident] = useState<IncidentCase | null>(null);
  const [explanation, setExplanation] = useState<IncidentExplanation | null>(null);
  const [checks, setChecks] = useState<RecommendedCheck[]>([]);
  const [mitigation, setMitigation] = useState<IncidentMitigation | null>(null);
  const [lifecycle, setLifecycle] = useState<IncidentLifecycle | null>(null);
  const [role, setRole] = useState<'OWNER' | 'OPERATOR' | 'VIEWER' | null>(null);
  const [deliveries, setDeliveries] = useState<Array<Record<string, unknown>>>([]);
  const [tab, setTab] = useState<IncidentTab>('Evidence');
  const [error, setError] = useState<string | null>(null);
  const [loadedForIncidentId, setLoadedForIncidentId] = useState('');
  const loading = loadedForIncidentId !== incidentId;
  const [resolutionType, setResolutionType] = useState<IncidentResolutionType>('FIXED');
  const [resolutionNote, setResolutionNote] = useState('');
  const [resolveDialogOpen, setResolveDialogOpen] = useState(false);
  const [checkedCriteria, setCheckedCriteria] = useState<number[]>([]);

  useEffect(() => {
    Promise.all([
      getIncidentInvestigation(incidentId),
      getIncidentMitigation(incidentId),
      getMembershipRole(),
      getIncidentLifecycle(incidentId).catch((err: unknown) => {
        if (err instanceof Error && err.message.startsWith('HTTP 404:')) return null;
        throw err;
      }),
    ])
      .then(([investigation, advisory, membershipRole, state]) => {
        setIncident(investigation.case);
        setExplanation(investigation.explanation);
        setChecks(investigation.recommendations);
        setDeliveries(investigation.notification_deliveries);
        setMitigation(advisory);
        setRole(membershipRole);
        setLifecycle(state);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unable to load incident RCA'))
      .finally(() => setLoadedForIncidentId(incidentId));
  }, [incidentId]);

  async function runTransition(
    transition: 'acknowledge' | 'resolve' | 'reopen',
  ) {
    try {
      setError(null);
      const state = transition === 'acknowledge'
        ? await acknowledgeIncident(incidentId)
        : transition === 'reopen'
          ? await reopenIncident(incidentId)
          : await resolveIncident(incidentId, resolutionType, resolutionNote);
      setLifecycle(state);
      if (transition === 'resolve') setResolveDialogOpen(false);
      setMitigation(await getIncidentMitigation(incidentId));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unable to update incident lifecycle');
    }
  }

  const canManageIncident = role === 'OWNER' || role === 'OPERATOR';
  const criteriaComplete = !mitigation?.resolution_criteria.length
    || checkedCriteria.length === mitigation.resolution_criteria.length;

  return (
    <main className="p3-shell"><div className="p3-content">
      <PageHeader
        eyebrow="Incident investigation"
        title={incident?.entity_id || 'Incident details'}
        description={`${incident?.incident_id || incidentId} · ${incident?.cloud_provider || '—'} · ${incident?.region || '—'}`}
        actions={<><Link className="p3-link-button" to="/incidents">All incidents</Link><Link className="p3-link-button" to="/alerts">Alert feed</Link></>}
      />
      {error ? <Toast message={error} tone="error" /> : null}
      {loading ? <Card><Skeleton rows={5} /></Card> : null}
      {incident ? <>
        {lifecycle ? <Card aria-label="Incident lifecycle">
          <div className="p3-row">
            <div>
              <span className="p3-label">Lifecycle</span>
              <StatusBadge status={lifecycle.status} />
              {lifecycle.regression_of ? <span className="ui-badge ui-status-regression">Regression</span> : null}
              {lifecycle.recovering ? <p className="p3-notice" role="status">Scores have remained below the LOW threshold; this incident is recovering.</p> : null}
              {lifecycle.status === 'RESOLVED' && lifecycle.resolution_note ? <p>{lifecycle.resolution_note}</p> : null}
              {lifecycle.regression_of ? <p>Regression of <Link to={`/incidents/${encodeURIComponent(lifecycle.regression_of)}`}>{lifecycle.regression_of}</Link></p> : null}
            </div>
            <div className="p3-actions">
              {canManageIncident && lifecycle.status === 'OPEN' ? <Button type="button" onClick={() => void runTransition('acknowledge')}>Acknowledge</Button> : null}
              {canManageIncident && lifecycle.status !== 'RESOLVED' ? <Button variant="primary" type="button" onClick={() => setResolveDialogOpen(true)}>Resolve incident</Button> : null}
              {canManageIncident && lifecycle.status === 'RESOLVED' ? <Button type="button" onClick={() => void runTransition('reopen')}>Reopen</Button> : null}
              {role === 'VIEWER' ? <p className="p3-footer">Viewer access is read-only; an operator or owner can change incident state.</p> : null}
            </div>
          </div>
        </Card> : null}
        {explanation?.is_fallback ? <div className="p3-notice p3-notice-fallback" role="status"><strong>No confident category — here is the evidence we do have.</strong> This fallback is based on the UNKNOWN knowledge entry; it is not a diagnosis.</div> : null}
        <section className="p3-grid incident-metrics">
          <Card><span className="p3-label">Severity</span><SeverityBadge severity={incident.severity} /></Card>
          <Card><span className="p3-label">Final score</span><div className="p3-metric">{incident.final_score.toFixed(2)}</div></Card>
          <Card><span className="p3-label">RCA confidence</span><ConfidenceBadge confidence={incident.confidence} /></Card>
          <Card><span className="p3-label">Category</span><div className="p3-metric">{explanation?.cause_category || 'UNKNOWN'}</div></Card>
        </section>
        <Card className="incident-investigation-card">
          <Tabs items={TABS} active={tab} onChange={(next) => setTab(next as IncidentTab)} label="Incident investigation views" />
          {tab === 'Evidence' ? <div className="p3-grid">
            <div><h2>Component scores</h2>{Object.entries(incident.component_scores).map(([name, value]) => <div className="p3-row" key={name}><span>{name}</span><strong>{Number(value).toFixed(2)}</strong></div>)}</div>
            <div><h2>Observed changes</h2>{incident.changed_features.length ? incident.changed_features.map((feature) => <div className="p3-row" key={feature}>{feature}</div>) : <p>No feature changes supplied.</p>}<h3 className="incident-subheading">Window</h3><p>Observed: {JSON.stringify(incident.observed_window)}</p><p>Baseline: {JSON.stringify(incident.baseline_window)}</p></div>
          </div> : null}
          {tab === 'Timeline' ? <div>{incident.timeline.map((item, index) => <div className="p3-row" key={`${String(item.event)}-${index}`}><strong>{String(item.event || 'event')}</strong><span>{String(item.timestamp || '')}</span></div>)}</div> : null}
          {tab === 'Causes' ? <div className="p3-grid">{incident.candidate_causes.map((cause) => <article className="p3-panel" key={cause.rule_id}><div className="p3-row"><h2>{cause.cause_category}</h2><span className={`p3-badge ${cause.confidence === 'HIGH' ? 'p3-badge-high' : cause.confidence === 'MEDIUM' ? 'p3-badge-medium' : 'p3-badge-low'}`}>{cause.confidence}</span></div><p>Rule: {cause.rule_id}</p><p>Supporting evidence: {cause.supporting_evidence_keys.join(', ') || 'None recorded'}</p><p>Contradicting evidence: {cause.contradicting_evidence_keys.join(', ') || 'None recorded'}</p></article>)}</div> : null}
          {tab === 'Explanation' && explanation ? <div>
            <h2>{explanation.headline}</h2>
            {explanation.match_basis ? <p>{explanation.match_basis}</p> : null}
            {explanation.mitigation_mode === 'generic' ? <p className="p3-notice" role="note">No eligible threat signature matched; this explanation uses generic cause-category guidance.</p> : null}
            {explanation.matched_threats.length ? <section aria-label="Threat signature matches">
              <h3>Possible matching patterns — not a diagnosis</h3>
              {explanation.matched_threats.map((threat) => <article className="p3-row" key={threat.threat_id}>
                <strong>{threat.title}</strong><ConfidenceBadge confidence={threat.match_confidence} />
                <p>Matched signals: {threat.matched_signals.join(', ') || 'None'}</p>
                <p>Not observed: {threat.unmatched_signals.join(', ') || 'None'}</p>
              </article>)}
            </section> : null}
            {explanation.sections.map((section) => <article className="incident-explanation-section" key={section.heading}><h3>{section.heading}</h3><p>{section.body}</p></article>)}
            <footer className="p3-footer">Knowledge base {explanation.kb_version} · Textbook context plus case evidence</footer>
          </div> : null}
          {tab === 'Checks' ? <div className="p3-grid">{checks.map((check) => <article className="p3-panel" key={`${check.check}-${check.why}`}><h2>{check.check}</h2><p>{check.why}</p><div className="p3-row"><span>Expected result</span><strong>{check.expected_result}</strong></div><span className="p3-badge">Risk: {check.risk}</span></article>)}</div> : null}
          {tab === 'Mitigation' && mitigation ? <div>
            <p className="p3-notice" role="note">These are guidance for your cloud team. The platform is read-only and never executes remediation.</p>
            {mitigation.threat ? <><h2>{mitigation.threat.title}</h2><p>{mitigation.match_basis}</p><p>Match confidence: <ConfidenceBadge confidence={mitigation.threat.match_confidence} /></p></> : <><h2>Generic investigation guidance</h2><p>No eligible threat signature matched. Review these generic checks with your cloud team.</p></>}
            {(['immediate', 'short_term', 'hardening'] as const).map((phase) => <section key={phase}>
              <h3>{phase === 'immediate' ? 'Immediate' : phase === 'short_term' ? 'Short term' : 'Hardening'}</h3>
              {mitigation.mitigation[phase].length ? mitigation.mitigation[phase].map((step, index) => <p className="p3-row" key={`${phase}-${index}`}>{step.text}<span className="ui-badge">{step.provider_specific ? `${mitigation.cloud_provider} specific` : 'Generic guidance'}</span></p>) : <p>No advisory steps are available for this phase.</p>}
            </section>)}
            {mitigation.mitre_attack.some(isVerifiedMitreReference) ? <section><h3>Verified MITRE ATT&CK references</h3><div className="incident-mitre-chips">{mitigation.mitre_attack.filter(isVerifiedMitreReference).map((item) => <a className="ui-badge incident-mitre-chip" href={item.url} key={item.id} target="_blank" rel="noreferrer">{item.id} · {item.name}</a>)}</div></section> : null}
            {mitigation.resolution_criteria.length ? <section><h3>Resolution criteria</h3>{mitigation.resolution_criteria.map((item) => <p className="p3-row" key={item}>{item}</p>)}</section> : null}
            {mitigation.post_incident_review ? <section><h3>Post-incident review (retrospective)</h3><p>Promoted phase: {mitigation.post_incident_review.promoted_phase}</p><p>Resolution: {mitigation.post_incident_review.resolution_record.type || 'Unspecified'} · {mitigation.post_incident_review.resolution_record.who || 'Unknown actor'} · {mitigation.post_incident_review.resolution_record.when || 'Unknown time'}</p><p>{mitigation.post_incident_review.resolution_record.note || 'No resolution note recorded.'}</p></section> : null}
          </div> : null}
          {tab === 'Response' ? <div className="p3-grid">{deliveries.map((delivery, index) => <article className="p3-panel" key={`${String(delivery.endpoint_id || delivery.channel || 'delivery')}-${index}`}><h2>{String(delivery.channel || 'Notification')}</h2><p>Status: {String(delivery.status || (delivery.success ? 'sent' : 'unknown'))}</p><p>{String(delivery.detail || delivery.message || 'No delivery detail recorded.')}</p></article>)}{!deliveries.length ? <p>No notification delivery records were returned for this incident.</p> : null}</div> : null}
        </Card>
        <ConfirmDialog
          open={resolveDialogOpen}
          title="Resolve incident"
          description="Record the outcome and confirm the threat-specific resolution criteria before closing this incident."
          confirmLabel="Confirm resolution"
          confirmDisabled={!criteriaComplete}
          onConfirm={() => void runTransition('resolve')}
          onCancel={() => setResolveDialogOpen(false)}
        >
          <div className="incident-resolve-form">
            <FormField label="Resolution type">
              <select value={resolutionType} onChange={(event) => setResolutionType(event.target.value as IncidentResolutionType)}>
                <option value="FIXED">Fixed</option>
                <option value="FALSE_POSITIVE">False positive</option>
                <option value="EXPECTED_CHANGE">Expected change</option>
                <option value="AUTO_RECOVERED">Auto recovered</option>
              </select>
            </FormField>
            <FormField label="Resolution note">
              <textarea value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} maxLength={2000} rows={3} />
            </FormField>
            {mitigation?.resolution_criteria.length ? <fieldset className="incident-resolution-checklist">
              <legend>Resolution criteria</legend>
              {mitigation.resolution_criteria.map((criterion, index) => <label key={`${index}-${criterion}`}>
                <input
                  type="checkbox"
                  checked={checkedCriteria.includes(index)}
                  onChange={(event) => setCheckedCriteria((previous) => event.target.checked
                    ? [...previous, index]
                    : previous.filter((checkedIndex) => checkedIndex !== index))}
                />
                <span>{criterion}</span>
              </label>)}
              <small>{checkedCriteria.length} of {mitigation.resolution_criteria.length} criteria confirmed</small>
            </fieldset> : <p className="p3-footer">No threat-specific resolution checklist is available; review the evidence and add a clear note.</p>}
          </div>
        </ConfirmDialog>
      </> : !loading && !error ? (
        <Card><EmptyState title="Incident not found" description="This incident is not available in the selected tenant or has no investigation record." action={<Link className="p3-button" to="/incidents">Return to incidents</Link>} /></Card>
      ) : null}
    </div></main>
  );
}

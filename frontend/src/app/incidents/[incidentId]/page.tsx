import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getIncident, getIncidentExplanation, getIncidentRecommendations, IncidentCase, IncidentExplanation, RecommendedCheck } from '../../../services/phase3Api';

type IncidentTab = 'Evidence' | 'Timeline' | 'Causes' | 'Explanation' | 'Checks';
const TABS: IncidentTab[] = ['Evidence', 'Timeline', 'Causes', 'Explanation', 'Checks'];

export default function IncidentPage() {
  const { incidentId = '' } = useParams();
  const [incident, setIncident] = useState<IncidentCase | null>(null);
  const [explanation, setExplanation] = useState<IncidentExplanation | null>(null);
  const [checks, setChecks] = useState<RecommendedCheck[]>([]);
  const [tab, setTab] = useState<IncidentTab>('Evidence');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getIncident(incidentId), getIncidentExplanation(incidentId), getIncidentRecommendations(incidentId)])
      .then(([caseData, explanationData, recommendationData]) => {
        setIncident(caseData);
        setExplanation(explanationData);
        setChecks(recommendationData);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unable to load incident RCA'));
  }, [incidentId]);

  return (
    <main className="p3-shell"><div className="p3-content">
      <header className="p3-header">
        <div><p className="p3-kicker">Incident investigation</p><h1 className="p3-title">{incident?.entity_id || 'Incident details'}</h1><p className="p3-subtitle">{incident?.incident_id || incidentId} · {incident?.cloud_provider || '—'} · {incident?.region || '—'}</p></div>
        <div className="p3-actions"><Link className="p3-link-button" to="/incidents">All incidents</Link><Link className="p3-link-button" to="/alerts">Alert feed</Link></div>
      </header>
      {error ? <p className="p3-error" role="alert">{error}</p> : null}
      {incident ? <>
        {explanation?.is_fallback ? <div className="p3-notice p3-notice-fallback" role="status"><strong>No confident category — here is the evidence we do have.</strong> This fallback is based on the UNKNOWN knowledge entry; it is not a diagnosis.</div> : null}
        <section className="p3-grid" style={{ marginTop: 14 }}>
          <article className="p3-panel"><span className="p3-label">Severity</span><div className="p3-metric">{incident.severity}</div></article>
          <article className="p3-panel"><span className="p3-label">Final score</span><div className="p3-metric">{incident.final_score.toFixed(2)}</div></article>
          <article className="p3-panel"><span className="p3-label">RCA confidence</span><div className="p3-metric">{incident.confidence}</div></article>
          <article className="p3-panel"><span className="p3-label">Category</span><div className="p3-metric">{explanation?.cause_category || 'UNKNOWN'}</div></article>
        </section>
        <section className="p3-panel" style={{ marginTop: 14 }}>
          <div className="p3-tabs" role="tablist" aria-label="Incident investigation views">
            {TABS.map((item) => <button className="p3-tab" type="button" role="tab" aria-selected={tab === item} key={item} onClick={() => setTab(item)}>{item}</button>)}
          </div>
          {tab === 'Evidence' ? <div className="p3-grid">
            <div><h2>Component scores</h2>{Object.entries(incident.component_scores).map(([name, value]) => <div className="p3-row" key={name}><span>{name}</span><strong>{Number(value).toFixed(2)}</strong></div>)}</div>
            <div><h2>Observed changes</h2>{incident.changed_features.length ? incident.changed_features.map((feature) => <div className="p3-row" key={feature}>{feature}</div>) : <p>No feature changes supplied.</p>}<h3 style={{ marginTop: 18 }}>Window</h3><p>Observed: {JSON.stringify(incident.observed_window)}</p><p>Baseline: {JSON.stringify(incident.baseline_window)}</p></div>
          </div> : null}
          {tab === 'Timeline' ? <div>{incident.timeline.map((item, index) => <div className="p3-row" key={`${String(item.event)}-${index}`}><strong>{String(item.event || 'event')}</strong><span>{String(item.timestamp || '')}</span></div>)}</div> : null}
          {tab === 'Causes' ? <div className="p3-grid">{incident.candidate_causes.map((cause) => <article className="p3-panel" key={cause.rule_id}><div className="p3-row"><h2>{cause.cause_category}</h2><span className={`p3-badge ${cause.confidence === 'HIGH' ? 'p3-badge-high' : cause.confidence === 'MEDIUM' ? 'p3-badge-medium' : 'p3-badge-low'}`}>{cause.confidence}</span></div><p>Rule: {cause.rule_id}</p><p>Supporting evidence: {cause.supporting_evidence_keys.join(', ') || 'None recorded'}</p><p>Contradicting evidence: {cause.contradicting_evidence_keys.join(', ') || 'None recorded'}</p></article>)}</div> : null}
          {tab === 'Explanation' && explanation ? <div>
            <h2>{explanation.headline}</h2>
            {explanation.sections.map((section) => <article className="p3-row" key={section.heading} style={{ alignItems: 'flex-start', display: 'block' }}><h3>{section.heading}</h3><p>{section.body}</p></article>)}
            <footer className="p3-footer">Knowledge base {explanation.kb_version} · Textbook context plus case evidence</footer>
          </div> : null}
          {tab === 'Checks' ? <div className="p3-grid">{checks.map((check) => <article className="p3-panel" key={`${check.check}-${check.why}`}><h2>{check.check}</h2><p>{check.why}</p><div className="p3-row"><span>Expected result</span><strong>{check.expected_result}</strong></div><span className="p3-badge">Risk: {check.risk}</span></article>)}</div> : null}
        </section>
      </> : !error ? <p>Loading incident…</p> : null}
    </div></main>
  );
}

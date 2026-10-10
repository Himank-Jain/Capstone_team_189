import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getIncidents, IncidentCase } from '../../services/phase3Api';

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<IncidentCase[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getIncidents().then(setIncidents).catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unable to load incidents'));
  }, []);

  return (
    <main className="p3-shell"><div className="p3-content">
      <header className="p3-header">
        <div><p className="p3-kicker">Investigation</p><h1 className="p3-title">Incidents & RCA</h1><p className="p3-subtitle">Evidence-linked context and deterministic knowledge guidance for tenant incidents.</p></div>
        <div className="p3-actions"><Link className="p3-link-button" to="/alerts">Alert feed</Link><Link className="p3-link-button" to="/">Dashboard</Link></div>
      </header>
      {error ? <p className="p3-error" role="alert">{error}</p> : null}
      <div className="p3-panel">
        {incidents.length === 0 ? <p>No RCA cases are available for this tenant yet. Run a scenario from the live demo to create one.</p> : incidents.map((incident) => {
          const cause = incident.candidate_causes[0];
          return <Link className="p3-row" key={incident.incident_id} to={`/incidents/${encodeURIComponent(incident.incident_id)}`} style={{ color: 'inherit', textDecoration: 'none' }}>
            <div><strong>{incident.entity_id}</strong><div className="p3-footer">{incident.incident_id} · {incident.cloud_provider} · {incident.region}</div></div>
            <div style={{ textAlign: 'right' }}><span className={`p3-badge ${cause?.confidence === 'HIGH' ? 'p3-badge-high' : 'p3-badge-medium'}`}>{cause?.cause_category || 'UNKNOWN'}</span><div className="p3-footer">{incident.severity} · score {incident.final_score.toFixed(2)}</div></div>
          </Link>;
        })}
      </div>
    </div></main>
  );
}

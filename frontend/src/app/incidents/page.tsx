import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, ConfidenceBadge, EmptyState, PageHeader, SeverityBadge, Skeleton, StatusBadge, Tabs, Toast } from '../../components/ui';
import { getIncidents, IncidentCase } from '../../services/phase3Api';

type IncidentFilter = 'Active' | 'Resolved';

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<IncidentCase[]>([]);
  const [filter, setFilter] = useState<IncidentFilter>('Active');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getIncidents()
      .then(setIncidents)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unable to load incidents'))
      .finally(() => setLoading(false));
  }, []);

  const visibleIncidents = incidents.filter((incident) => (
    filter === 'Resolved'
      ? incident.lifecycle_status === 'RESOLVED'
      : incident.lifecycle_status !== 'RESOLVED'
  ));

  return (
    <main className="p3-shell"><div className="p3-content">
      <PageHeader
        eyebrow="Investigation"
        title="Incidents & RCA"
        description="Evidence-linked context and deterministic knowledge guidance for tenant incidents."
        actions={<><Link className="p3-link-button" to="/alerts">Alert feed</Link><Link className="p3-link-button" to="/">Dashboard</Link></>}
      />
      {error ? <Toast message={error} tone="error" /> : null}
      <Card>
        <Tabs items={['Active', 'Resolved']} active={filter} onChange={(value) => setFilter(value as IncidentFilter)} label="Incident status filter" />
        {loading ? <Skeleton rows={5} /> : incidents.length === 0 ? (
          <EmptyState
            title="No incidents available"
            description="Run a scenario from the live demo to create an evidence-linked investigation."
            action={<Link className="p3-button p3-button-primary" to="/demo">Open live demo</Link>}
          />
        ) : visibleIncidents.length === 0 ? (
          <EmptyState
            title={filter === 'Resolved' ? 'No resolved incidents' : 'No active incidents'}
            description={filter === 'Resolved'
              ? 'Resolved investigations will appear here with their post-incident review.'
              : 'Resolved incidents are excluded from the active list. New active incidents will appear here.'}
          />
        ) : (
          <div className="incident-list">
            {visibleIncidents.map((incident) => {
              const cause = incident.candidate_causes[0];
              return (
                <article className="incident-list-row" key={incident.incident_id}>
                  <div>
                    <Link className="incident-list-main-link" to={`/incidents/${encodeURIComponent(incident.incident_id)}`}>
                      <strong>{incident.entity_id}</strong>
                      <span>{incident.incident_id} · {incident.cloud_provider} · {incident.region}</span>
                    </Link>
                  </div>
                  <div className="incident-list-meta">
                    {incident.regression_of ? <StatusBadge status="REGRESSION" /> : <StatusBadge status={incident.lifecycle_status || 'OPEN'} />}
                    <ConfidenceBadge confidence={cause?.confidence || 'LOW'} />
                    <span>{cause?.cause_category || 'UNKNOWN'}</span>
                    <SeverityBadge severity={incident.severity} />
                    <span>Score {incident.final_score.toFixed(2)}</span>
                    {incident.regression_of ? <Link to={`/incidents/${encodeURIComponent(incident.regression_of)}`}>Original incident</Link> : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Card>
    </div></main>
  );
}

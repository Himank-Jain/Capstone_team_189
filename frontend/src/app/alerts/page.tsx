import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, EmptyState, PageHeader, SeverityBadge, Skeleton, Toast } from '../../components/ui';
import { getRecentAlerts } from '../../services/alertsApi';
import { getErrorMessage } from '../../services/errors';

interface AlertRow {
  alert_id: string;
  entity_id: string;
  final_score: number;
  severity: string;
  batch_ts: string;
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadAlerts() {
      try {
        setAlerts((await getRecentAlerts()).slice(0, 20));
      } catch (err: unknown) {
        setError(getErrorMessage(err, 'Unable to load alerts'));
      } finally {
        setLoading(false);
      }
    }
    void loadAlerts();
  }, []);

  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Detection activity"
          title="Live alert feed"
          description="Recent tenant-scoped alerts. Select an item to review its evidence, explanation, and lifecycle."
        />
        {error ? <Toast message={error} tone="error" /> : null}
        <Card>
          {loading ? <Skeleton rows={5} /> : alerts.length === 0 ? (
            <EmptyState
              title="No alerts yet"
              description="Run a synthetic scenario to add the first alert to this tenant's feed."
              action={<Link className="p3-button p3-button-primary" to="/demo">Open live demo</Link>}
            />
          ) : (
            <div className="dashboard-alert-list">
              {alerts.map((alert) => (
                <Link
                  className="dashboard-alert-row"
                  to={`/incidents/${encodeURIComponent(alert.alert_id)}`}
                  key={alert.alert_id}
                >
                  <div>
                    <span className="dashboard-alert-entity">{alert.batch_ts}</span>
                    <strong>{alert.entity_id}</strong>
                    <span className="dashboard-alert-entity">{alert.alert_id}</span>
                  </div>
                  <div className="dashboard-alert-score">
                    <SeverityBadge severity={alert.severity} />
                    <strong>{alert.final_score.toFixed(2)}</strong>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </Card>
      </div>
    </main>
  );
}

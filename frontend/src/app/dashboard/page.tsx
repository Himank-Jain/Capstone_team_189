import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, EmptyState, PageHeader, SeverityBadge, Skeleton, StatCard, Toast } from '../../components/ui';
import { getRecentAlerts } from '../../services/alertsApi';
import { getSummary } from '../../services/demoApi';
import { getErrorMessage } from '../../services/errors';

interface DashboardSummary {
  active_alerts?: number;
  critical_alerts?: number;
  event_volume?: number;
  model_confidence?: number;
  mean_time_to_resolve_minutes?: number;
  resolved_today?: number;
}

interface DashboardAlert {
  alert_id: string;
  entity_id: string;
  final_score: number;
  severity: string;
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [alerts, setAlerts] = useState<DashboardAlert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [summaryData, alertsData] = await Promise.all([getSummary(), getRecentAlerts()]);
        setSummary(summaryData);
        setAlerts(alertsData.slice(0, 5));
      } catch (err: unknown) {
        setError(getErrorMessage(err, 'Unable to load dashboard data'));
      } finally {
        setLoading(false);
      }
    }

    void loadData();
  }, []);

  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Security operations"
          title="SOC overview"
          description="A focused view of tenant activity, detection health, and incidents requiring investigation."
          actions={
            <>
              <Link className="p3-link-button" to="/demo">Open live demo</Link>
              <Link className="p3-button p3-button-primary" to="/incidents">Investigate RCA</Link>
            </>
          }
        />

        {error ? <Toast message={error} tone="error" /> : null}

        {loading ? (
          <Card><Skeleton rows={4} /></Card>
        ) : (
          <>
            <section className="p3-grid dashboard-stats" aria-label="Security metrics">
              <StatCard label="Active incidents" value={summary?.active_alerts ?? 0} detail="Open or acknowledged" />
              <StatCard label="Critical alerts" value={summary?.critical_alerts ?? 0} tone="critical" />
              <StatCard label="Event volume" value={summary?.event_volume ?? 0} tone="neutral" />
              <StatCard
                label="Model confidence"
                value={summary?.model_confidence ? `${Math.round(summary.model_confidence * 100)}%` : '—'}
                tone="success"
              />
              <StatCard
                label="Mean time to resolve"
                value={`${summary?.mean_time_to_resolve_minutes ?? 0} min`}
                tone="neutral"
              />
              <StatCard label="Resolved today" value={summary?.resolved_today ?? 0} tone="success" />
            </section>

            <Card className="dashboard-alerts">
              <div className="section-heading">
                <div>
                  <p className="ui-eyebrow">Latest activity</p>
                  <h2>Recent alerts</h2>
                </div>
                <Link className="ui-link" to="/alerts">View alert feed</Link>
              </div>
              {alerts.length === 0 ? (
                <EmptyState
                  title="No recent alerts"
                  description="No alerts are available for this tenant. Trigger a synthetic scenario to populate the investigation feed."
                  action={<Link className="p3-button p3-button-primary" to="/demo">Open live demo</Link>}
                />
              ) : (
                <div className="dashboard-alert-list">
                  {alerts.map((alert) => (
                    <Link
                      to={`/incidents/${encodeURIComponent(alert.alert_id)}`}
                      key={alert.alert_id}
                      className="dashboard-alert-row"
                    >
                      <div>
                        <span className="dashboard-alert-entity">{alert.entity_id}</span>
                        <strong>{alert.alert_id}</strong>
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
          </>
        )}
      </div>
    </main>
  );
}

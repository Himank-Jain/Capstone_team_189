import { useEffect, useState } from 'react';
import { getSummary } from '../../services/demoApi';
import { getRecentAlerts } from '../../services/alertsApi';

export default function DashboardPage() {
  const [summary, setSummary] = useState<{ active_alerts?: number; critical_alerts?: number; event_volume?: number; model_confidence?: number } | null>(null);
  const [alerts, setAlerts] = useState<Array<{ alert_id: string; entity_id: string; final_score: number; severity: string }>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [summaryData, alertsData] = await Promise.all([getSummary(), getRecentAlerts()]);
        setSummary(summaryData);
        setAlerts(alertsData.slice(0, 5));
      } catch (err: any) {
        setError(err?.message || 'Unable to load dashboard data');
      }
    }

    loadData();
  }, []);

  return (
    <main style={{ padding: '24px', color: '#f3f4f6', background: '#0b0f17', minHeight: '100vh' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '16px' }}>
        <div>
          <h1 style={{ fontSize: '32px', marginBottom: '8px' }}>CAPSTONE-189 · SOC Overview</h1>
          <p style={{ color: '#94a3b8', margin: 0 }}>Live multi-tenant anomaly dashboard with synthetic demo generation.</p>
        </div>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <a href="/demo" style={{ padding: '10px 16px', borderRadius: '14px', background: '#2563eb', color: 'white', textDecoration: 'none' }}>Open Live Demo</a>
          <a href="/alerts" style={{ padding: '10px 16px', borderRadius: '14px', background: '#111827', color: '#f8fafc', border: '1px solid #1f2937', textDecoration: 'none' }}>View Alert Feed</a>
        </div>
      </div>

      {error ? <p style={{ color: '#fca5a5' }}>{error}</p> : null}

      <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', marginBottom: '24px' }}>
        <div style={{ padding: '20px', borderRadius: '18px', background: '#111827', border: '1px solid #1f2937' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>Active Alerts</p>
          <h2 style={{ margin: '12px 0 0', fontSize: '28px' }}>{summary?.active_alerts ?? '--'}</h2>
        </div>
        <div style={{ padding: '20px', borderRadius: '18px', background: '#111827', border: '1px solid #1f2937' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>Critical Alerts</p>
          <h2 style={{ margin: '12px 0 0', fontSize: '28px' }}>{summary?.critical_alerts ?? '--'}</h2>
        </div>
        <div style={{ padding: '20px', borderRadius: '18px', background: '#111827', border: '1px solid #1f2937' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>Event Volume</p>
          <h2 style={{ margin: '12px 0 0', fontSize: '28px' }}>{summary?.event_volume ?? '--'}</h2>
        </div>
        <div style={{ padding: '20px', borderRadius: '18px', background: '#111827', border: '1px solid #1f2937' }}>
          <p style={{ margin: 0, color: '#94a3b8' }}>Model Confidence</p>
          <h2 style={{ margin: '12px 0 0', fontSize: '28px' }}>{summary?.model_confidence ? `${Math.round(summary.model_confidence * 100)}%` : '--'}</h2>
        </div>
      </div>

      <section style={{ padding: '20px', borderRadius: '18px', background: '#111827', border: '1px solid #1f2937' }}>
        <h2 style={{ margin: '0 0 16px', fontSize: '22px' }}>Recent alerts</h2>
        {alerts.length === 0 ? (
          <p style={{ margin: 0, color: '#94a3b8' }}>No recent alerts for this tenant. Trigger a demo scenario from the Live Demo page.</p>
        ) : (
          <div style={{ display: 'grid', gap: '12px' }}>
            {alerts.map((alert) => (
              <div key={alert.alert_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px', borderRadius: '14px', background: '#0f172a' }}>
                <div>
                  <p style={{ margin: 0, color: '#94a3b8' }}>{alert.entity_id}</p>
                  <strong style={{ fontSize: '16px' }}>{alert.alert_id}</strong>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <p style={{ margin: 0, color: '#94a3b8' }}>{alert.severity}</p>
                  <strong>{alert.final_score.toFixed(2)}</strong>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

import { useEffect, useState } from 'react';
import { getRecentAlerts } from '../../services/alertsApi';

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Array<{ alert_id: string; entity_id: string; final_score: number; severity: string; batch_ts: string }>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadAlerts() {
      try {
        const data = await getRecentAlerts();
        setAlerts(data.slice(0, 20));
      } catch (err: any) {
        setError(err?.message || 'Unable to load alerts');
      }
    }
    loadAlerts();
  }, []);

  return (
    <main style={{ minHeight: '100vh', padding: '24px', background: '#0b0f17', color: '#f8fafc' }}>
      <div style={{ maxWidth: '1080px', margin: '0 auto' }}>
        <h1 style={{ fontSize: '32px', marginBottom: '12px' }}>Live Alert Feed</h1>
        <p style={{ color: '#94a3b8', marginBottom: '24px' }}>
          Real-time alerts from the demo backend with tenant-scoped alert history.
        </p>
        {error ? <p style={{ color: '#fca5a5' }}>{error}</p> : null}
        <div style={{ display: 'grid', gap: '12px' }}>
          {alerts.length === 0 ? (
            <div style={{ padding: '20px', borderRadius: '16px', background: '#111827', border: '1px solid #1f2937' }}>
              <p style={{ margin: 0, color: '#94a3b8' }}>No alerts yet. Run a demo scenario to populate the feed.</p>
            </div>
          ) : (
            alerts.map((alert) => (
              <div key={alert.alert_id} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '12px', padding: '18px', borderRadius: '16px', background: '#111827', border: '1px solid #1f2937' }}>
                <div>
                  <p style={{ margin: 0, color: '#94a3b8' }}>{alert.batch_ts}</p>
                  <h2 style={{ margin: '8px 0 0' }}>{alert.entity_id}</h2>
                  <p style={{ margin: '4px 0 0', color: '#cbd5e1' }}>{alert.alert_id}</p>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <span style={{ display: 'inline-block', padding: '6px 12px', borderRadius: '999px', background: alert.severity === 'CRITICAL' ? '#b91c1c' : '#1f2937', color: '#f8fafc', fontWeight: 600, marginBottom: '8px' }}>
                    {alert.severity}
                  </span>
                  <div style={{ color: '#f8fafc', fontSize: '24px', fontWeight: 700 }}>{alert.final_score.toFixed(2)}</div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </main>
  );
}

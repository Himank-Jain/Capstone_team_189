import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ConnectionSummary, getConnections } from '../../services/phase3Api';

export default function ConnectionsPage() {
  const [data, setData] = useState<ConnectionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getConnections().then(setData).catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unable to load connections'));
  }, []);

  return (
    <main className="p3-shell"><div className="p3-content">
      <header className="p3-header">
        <div><p className="p3-kicker">Settings / Integrations</p><h1 className="p3-title">Connections</h1><p className="p3-subtitle">Review the tenant’s current data source and notification channels.</p></div>
        <div className="p3-actions"><Link className="p3-link-button" to="/onboarding">Onboarding</Link><Link className="p3-link-button" to="/settings">Settings</Link></div>
      </header>
      {error ? <p className="p3-error" role="alert">{error}</p> : null}
      {data ? <>
        <section className="p3-grid">
          <article className="p3-panel"><p className="p3-kicker">Tenant</p><h2>{data.tenant_id}</h2><span className="p3-badge p3-badge-high">{data.source_mode} source</span></article>
          {data.connections.map((connection) => <article className="p3-panel" key={`${connection.provider}-${connection.region}`}>
            <p className="p3-kicker">Cloud connection</p><h2>{connection.provider}</h2>
            <div className="p3-row"><span>Region</span><strong>{connection.region}</strong></div>
            <div className="p3-row"><span>Status</span><span className="p3-badge p3-badge-medium">{connection.status}</span></div>
            <div className="p3-row"><span>Dry run</span><strong>{connection.dry_run ? 'On' : 'Off'}</strong></div>
          </article>)}
        </section>
        <section className="p3-panel" style={{ marginTop: 14 }}>
          <h2>Notification channels</h2>
          <p>Endpoint readiness is shown without exposing provider secrets.</p>
          <div className="p3-grid">{data.notification_channels.map(({ channel, status, detail }) => <div className="p3-row" key={channel}>
            <div><strong>{channel}</strong><div className="p3-footer">{detail}</div></div>
            <span className={`p3-badge ${status === 'ready' ? 'p3-badge-high' : status === 'simulated' ? 'p3-badge-medium' : 'p3-badge-low'}`}>{status.replace('_', ' ')}</span>
          </div>)}</div>
        </section>
      </> : <p>Loading connection status…</p>}
    </div></main>
  );
}

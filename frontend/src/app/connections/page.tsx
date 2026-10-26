import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ConnectionSummary, getConnections } from '../../services/phase3Api';
import { useAuth } from '../../auth/authContext';
import NotificationChannelsPanel from '../../components/NotificationChannelsPanel';
import { Card, EmptyState, PageHeader, Skeleton, StatusBadge, Toast } from '../../components/ui';

export default function ConnectionsPage() {
  const [data, setData] = useState<ConnectionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { role, activeTenantId } = useAuth();

  useEffect(() => {
    getConnections()
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Unable to load connections'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="p3-shell"><div className="p3-content">
      <PageHeader
        eyebrow="Settings / Integrations"
        title="Connections"
        description="Review the tenant’s current data source and notification channels."
        actions={<><Link className="p3-link-button" to="/onboarding">Onboarding</Link><Link className="p3-link-button" to="/settings">Settings</Link></>}
      />
      {error ? <Toast message={error} tone="error" /> : null}
      {loading ? <Card><Skeleton rows={4} /></Card> : data ? <>
        <section className="p3-grid">
          <Card><p className="p3-kicker">Tenant</p><h2>{data.tenant_id}</h2><span className="ui-badge ui-status-acknowledged">{data.source_mode} source</span></Card>
          {data.connections.map((connection) => <article className="p3-panel" key={`${connection.provider}-${connection.region}`}>
            <p className="p3-kicker">Cloud connection</p><h2>{connection.provider}</h2>
            <div className="p3-row"><span>Region</span><strong>{connection.region}</strong></div>
            <div className="p3-row"><span>Status</span><StatusBadge status={connection.status} /></div>
            <div className="p3-row"><span>Dry run</span><strong>{connection.dry_run ? 'On' : 'Off'}</strong></div>
          </article>)}
        </section>
        {!data.connections.length ? <Card><EmptyState title="No cloud connections" description="Connect a cloud provider during onboarding. Connections remain read-only and dry-run by default." action={<Link className="p3-button p3-button-primary" to="/onboarding">Continue onboarding</Link>} /></Card> : null}
        <NotificationChannelsPanel canSendTest={role === 'OWNER' || role === 'OPERATOR'} tenantId={activeTenantId} />
      </> : <Card><EmptyState title="Connection status unavailable" description="We could not load this tenant’s connection details. Try again after confirming the selected workspace." /></Card>}
    </div></main>
  );
}

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, EmptyState, PageHeader, Skeleton, Toast } from '../../components/ui';
import { getTenants } from '../../services/tenantsApi';
import { setActiveTenantId } from '../../services/apiClient';
import { getErrorMessage } from '../../services/errors';

interface TenantChoice {
  id: string;
  name: string;
  live_alert_count: number;
  health: string;
}

export default function SelectOrgPage() {
  const navigate = useNavigate();
  const [tenants, setTenants] = useState<TenantChoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadTenants() {
      try {
        setTenants(await getTenants());
      } catch (err: unknown) {
        setError(getErrorMessage(err, 'Unable to load tenants'));
      } finally {
        setLoading(false);
      }
    }
    void loadTenants();
  }, []);

  const handleSelect = (tenantId: string) => {
    setActiveTenantId(tenantId);
    navigate('/');
  };

  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Workspace"
          title="Select your organization"
          description="Choose a tenant to view its isolated multi-cloud alerts and demonstration controls."
        />
        {error ? <Toast message={error} tone="error" /> : null}
        {loading ? <Card><Skeleton rows={4} /></Card> : tenants.length ? (
          <div className="tenant-choice-grid">
            {tenants.map((tenant) => (
              <Card className="tenant-choice-card" key={tenant.id}>
                <div className="tenant-choice-header">
                  <div>
                    <p className="ui-eyebrow">Tenant workspace</p>
                    <h2>{tenant.name}</h2>
                  </div>
                  <span className={`ui-badge ${tenant.health === 'healthy' ? 'ui-status-resolved' : 'ui-severity-medium'}`}>
                    {tenant.health}
                  </span>
                </div>
                <p>{tenant.live_alert_count} recent alerts</p>
                <Button variant="primary" type="button" onClick={() => handleSelect(tenant.id)}>
                  Open workspace
                </Button>
              </Card>
            ))}
          </div>
        ) : (
          <Card>
            <EmptyState title="No organizations available" description="No tenant memberships were returned for this account." />
          </Card>
        )}
      </div>
    </main>
  );
}

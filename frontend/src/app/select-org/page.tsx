import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, EmptyState, PageHeader, Skeleton, Toast } from '../../components/ui';
import { getTenants, type TenantSummary } from '../../services/tenantsApi';
import { useAuth } from '../../auth/authContext';
import { getErrorMessage } from '../../services/errors';

export default function SelectOrgPage() {
  const navigate = useNavigate();
  const { switchTenant, activeTenantId } = useAuth();
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
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
    switchTenant(tenantId);
    navigate('/');
  };

  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Workspace"
          title="Select your organization"
          description="Workspaces you are a member of. Each one keeps its alerts, incidents, and members separate."
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
                <p>Your role: {tenant.role ? tenant.role.toLowerCase() : 'member'}</p>
                <Button variant="primary" type="button" onClick={() => handleSelect(tenant.id)} disabled={tenant.id === activeTenantId}>
                  {tenant.id === activeTenantId ? 'Current workspace' : 'Open workspace'}
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

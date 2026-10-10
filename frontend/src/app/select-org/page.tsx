import { useEffect, useState } from 'react';
import { getTenants } from '../../services/tenantsApi';
import { setActiveTenantId } from '../../services/apiClient';

export default function SelectOrgPage() {
  const [tenants, setTenants] = useState<Array<{ id: string; name: string; live_alert_count: number; health: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadTenants() {
      try {
        const data = await getTenants();
        setTenants(data);
      } catch (err: any) {
        setError(err?.message || 'Unable to load tenants');
      } finally {
        setLoading(false);
      }
    }
    loadTenants();
  }, []);

  const handleSelect = (tenantId: string) => {
    setActiveTenantId(tenantId);
    window.location.href = '/';
  };

  return (
    <main style={{ minHeight: '100vh', padding: '24px', background: '#0b0f17', color: '#f8fafc' }}>
      <div style={{ maxWidth: '980px', margin: '0 auto' }}>
        <h1 style={{ fontSize: '32px', marginBottom: '12px' }}>Select your organization</h1>
        <p style={{ color: '#94a3b8', marginBottom: '24px' }}>
          Choose a tenant to view isolated multi-cloud alerts and live demo controls.
        </p>
        {loading ? (
          <p>Loading tenants…</p>
        ) : error ? (
          <p style={{ color: '#fca5a5' }}>{error}</p>
        ) : (
          <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            {tenants.map((tenant) => (
              <button
                key={tenant.id}
                type="button"
                onClick={() => handleSelect(tenant.id)}
                style={{
                  textAlign: 'left',
                  padding: '20px',
                  borderRadius: '18px',
                  border: '1px solid #1f2937',
                  background: '#111827',
                  color: '#f8fafc',
                  cursor: 'pointer',
                }}
              >
                <h2 style={{ margin: '0 0 8px', fontSize: '20px' }}>{tenant.name}</h2>
                <p style={{ margin: 0, color: '#94a3b8' }}>Live alerts: {tenant.live_alert_count}</p>
                <p style={{ margin: '8px 0 0', color: tenant.health === 'healthy' ? '#22c55e' : '#facc15' }}>
                  {tenant.health.toUpperCase()}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

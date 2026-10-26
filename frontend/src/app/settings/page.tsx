import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth/authContext';
import EmailSettingsCard from '../../components/EmailSettingsCard';
import NotificationChannelsPanel from '../../components/NotificationChannelsPanel';
import { Badge, Button, Card, PageHeader } from '../../components/ui';

export default function SettingsPage() {
  const navigate = useNavigate();
  const { session, role, activeTenantId, activeMembership, signOut } = useAuth();
  const [channelsVersion, setChannelsVersion] = useState(0);
  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Administration"
          title="Settings"
          description="Your account, this workspace, and where its alerts are delivered."
          actions={<><Link className="p3-link-button" to="/users">Members</Link><Link className="p3-link-button" to="/connections">Connections</Link></>}
        />
        <section className="p3-grid">
          <Card>
            <p className="ui-eyebrow">Account</p>
            <h2>{session?.user.email}</h2>
            <p className="p3-footer">Signed in. Sessions expire automatically; sign in again when prompted.</p>
            <Button type="button" onClick={() => { signOut(); navigate('/login', { replace: true }); }}>Sign out</Button>
          </Card>
          <Card>
            <p className="ui-eyebrow">Workspace</p>
            <h2>{activeMembership?.tenant_name || activeTenantId}</h2>
            <p>
              Your role: <Badge>{role?.toLowerCase() || 'none'}</Badge>
              {session?.user.is_admin ? <> <Badge className="ui-confidence-high">admin</Badge> <Link to="/admin">Admin console</Link></> : null}
            </p>
            <p className="p3-footer">Member of {session?.memberships.length ?? 0} workspace(s). Switch workspaces from the top bar.</p>
          </Card>
        </section>
        <EmailSettingsCard
          canEdit={role === 'OWNER'}
          tenantId={activeTenantId}
          onSaved={() => setChannelsVersion((version) => version + 1)}
        />
        <NotificationChannelsPanel
          canSendTest={role === 'OWNER' || role === 'OPERATOR'}
          tenantId={activeTenantId}
          refreshKey={channelsVersion}
        />
      </div>
    </main>
  );
}

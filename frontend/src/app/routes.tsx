import { Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import AuthProvider from '../auth/AuthProvider';
import { useAuth } from '../auth/authContext';
import NotificationCenter from '../components/NotificationCenter';
import { isMockMode } from '../services/apiClient';
import DashboardPage from './dashboard/page';
import AlertsPage from './alerts/page';
import AnalyticsPage from './analytics/page';
import DemoPage from './demo/page';
import LoginPage from './login/page';
import SelectOrgPage from './select-org/page';
import EntityPage from './entities/[entityId]/page';
import SettingsPage from './settings/page';
import UsersPage from './users/page';
import SystemHealthPage from './system-health/page';
import ModelHealthPage from './model-health/page';
import OnboardingPage from './onboarding/page';
import ConnectionsPage from './connections/page';
import IncidentsPage from './incidents/page';
import IncidentPage from './incidents/[incidentId]/page';
import AdminPage from './admin/page';
import './phase3.css';
import '../theme.css';
import { Button, Skeleton } from '../components/ui';

const NAV_LINKS = [
  { label: 'Overview', path: '/', section: 'Workspace' },
  { label: 'Live demo', path: '/demo' },
  { label: 'Alert feed', path: '/alerts' },
  { label: 'Incidents & RCA', path: '/incidents' },
  { label: 'Analytics', path: '/analytics' },
  { label: 'Entity profiles', path: '/entities/demo-entity', section: 'Operations' },
  { label: 'Model health', path: '/model-health' },
  { label: 'System health', path: '/system-health' },
  { label: 'Onboarding', path: '/onboarding', section: 'Administration' },
  { label: 'Connections', path: '/connections' },
  { label: 'Users', path: '/users' },
  { label: 'Settings', path: '/settings' },
  { label: 'Organization', path: '/select-org' },
];

function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { status, session, activeTenantId, activeMembership, role, signOut, switchTenant } = useAuth();
  if (status === 'loading') {
    return (
      <main className="login-page" aria-busy="true">
        <div className="login-card ui-card"><Skeleton rows={3} /></div>
      </main>
    );
  }
  if (status !== 'authenticated' || !session) {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  const isAdmin = Boolean(session.user.is_admin);
  const navLinks = isAdmin ? [...NAV_LINKS, { label: 'Admin console', path: '/admin' }] : NAV_LINKS;
  const currentLink = navLinks.find(({ path }) =>
    path === '/' ? location.pathname === '/' : location.pathname.startsWith(path),
  );
  const tenantLabel = activeMembership?.tenant_name || activeTenantId || 'No workspace';
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <NavLink className="app-brand" to="/" aria-label="CAPSTONE-189 home">
          <span className="app-brand-mark" aria-hidden="true">C</span>
          <span>CAPSTONE-189</span>
        </NavLink>
        <div className="app-nav-links">
          {navLinks.map(({ label, path, section }, index) => (
            <div key={path}>
              {section ? <p className="app-nav-section">{section}</p> : null}
              <NavLink
                to={path}
                end={path === '/'}
                className={({ isActive }) => `app-nav-link${isActive ? ' app-nav-link-active' : ''}`}
                aria-current={currentLink?.path === path ? 'page' : undefined}
              >
                <span className="app-nav-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                {label}
              </NavLink>
            </div>
          ))}
        </div>
        <div className="app-sidebar-footer">
          <div className="app-session-user">
            <span className="app-session-email" title={session.user.email}>
              {session.user.email}
              {isAdmin ? <span className="ui-badge ui-confidence-high app-admin-badge">admin</span> : null}
            </span>
            <span className="app-session-label">{role ? `${role.toLowerCase()} · ${tenantLabel}` : `No access to ${tenantLabel}`}</span>
          </div>
          <Button
            variant="ghost"
            onClick={() => {
              signOut();
              navigate('/login', { replace: true });
            }}
          >
            Sign out
          </Button>
        </div>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <span className="app-breadcrumb">Workspace / {currentLink?.label || 'Incident details'}</span>
          <div className="app-topbar-meta">
            {session.memberships.length > 1 ? (
              <label className="app-tenant-switch">
                <span className="visually-hidden">Active workspace</span>
                <select
                  value={activeTenantId ?? ''}
                  onChange={(event) => {
                    switchTenant(event.target.value);
                    navigate('/', { replace: true });
                  }}
                >
                  {session.memberships.map((membership) => (
                    <option key={membership.tenant_id} value={membership.tenant_id}>
                      {membership.tenant_name} · {membership.role.toLowerCase()}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <span className="app-tenant-pill">Tenant · {tenantLabel}</span>
            )}
            {isMockMode() ? <span className="ui-badge ui-status-resolved">Mock mode</span> : null}
            <NotificationCenter tenantId={activeTenantId} />
          </div>
        </header>
        {/* Remount pages when the workspace changes so tenant data reloads. */}
        <Outlet key={activeTenantId ?? 'none'} />
      </div>
    </div>
  );
}

export default function AppRoutes() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/select-org" element={<SelectOrgPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/entities/:entityId" element={<EntityPage />} />
          <Route path="/demo" element={<DemoPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/system-health" element={<SystemHealthPage />} />
          <Route path="/model-health" element={<ModelHealthPage />} />
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/incidents" element={<IncidentsPage />} />
          <Route path="/incidents/:incidentId" element={<IncidentPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}

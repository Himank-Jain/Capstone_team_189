import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from 'react-router-dom';
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
import './phase3.css';
import '../theme.css';
import { Button } from '../components/ui';

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
  if (!localStorage.getItem('capstone.userId')) {
    return <Navigate to="/login" replace />;
  }
  const currentLink = NAV_LINKS.find(({ path }) =>
    path === '/' ? location.pathname === '/' : location.pathname.startsWith(path),
  );
  const tenantId = localStorage.getItem('capstone.activeTenantId') || 'google';
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <NavLink className="app-brand" to="/" aria-label="CAPSTONE-189 home">
          <span className="app-brand-mark" aria-hidden="true">C</span>
          <span>CAPSTONE-189</span>
        </NavLink>
        <div className="app-nav-links">
          {NAV_LINKS.map(({ label, path, section }, index) => (
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
          <span className="app-session-label">Local demonstration workspace</span>
          <Button
            variant="ghost"
            onClick={() => {
              localStorage.removeItem('capstone.userId');
              window.location.assign('/login');
            }}
          >
            End demo session
          </Button>
        </div>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <span className="app-breadcrumb">Workspace / {currentLink?.label || 'Incident details'}</span>
          <div className="app-topbar-meta">
            <span className="app-tenant-pill">Tenant · {tenantId}</span>
            <span className="ui-badge ui-status-resolved">Mock-ready</span>
          </div>
        </header>
        <Outlet />
      </div>
    </div>
  );
}

export default function AppRoutes() {
  return (
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
        <Route path="/system-health" element={<SystemHealthPage />} />
        <Route path="/model-health" element={<ModelHealthPage />} />
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/connections" element={<ConnectionsPage />} />
        <Route path="/incidents" element={<IncidentsPage />} />
        <Route path="/incidents/:incidentId" element={<IncidentPage />} />
      </Route>
    </Routes>
  );
}

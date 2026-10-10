import { Route, Routes } from 'react-router-dom';
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

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/login" element={<LoginPage />} />
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
    </Routes>
  );
}

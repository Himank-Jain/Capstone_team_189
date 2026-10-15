import { FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Badge,
  Card,
  FormField,
  PageHeader,
  Skeleton,
  Stepper,
  Toast,
} from '../../components/ui';
import { advanceOnboarding, getOnboarding, OnboardingSession, startOnboarding } from '../../services/phase3Api';

const SESSION_KEY = 'capstone.phase3.onboardingSessionId';
const STEPS = [
  ['tenant', 'Tenant'],
  ['cloud_connection', 'Cloud connection'],
  ['credential_validation', 'Credential validation'],
  ['resource_discovery', 'Resource discovery'],
  ['notification_setup', 'Notification setup'],
  ['test_notification', 'Test notification'],
  ['enable_monitoring', 'Enable monitoring'],
] as const;

export default function OnboardingPage() {
  const [session, setSession] = useState<OnboardingSession | null>(null);
  const [tenantName, setTenantName] = useState('');
  const [sourceMode, setSourceMode] = useState<'synthetic' | 'live'>('synthetic');
  const [stepIndex, setStepIndex] = useState(0);
  const [confirmLive, setConfirmLive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingSession, setLoadingSession] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function restoreSession() {
      const sessionId = localStorage.getItem(SESSION_KEY);
      if (!sessionId) {
        setLoadingSession(false);
        return;
      }
      try {
        const value = await getOnboarding(sessionId);
        if (cancelled) return;
        setSession(value);
        setTenantName(value.tenant_name);
        setSourceMode(value.source_mode);
        const firstIncomplete = STEPS.findIndex(([key]) => !value.steps[key]);
        setStepIndex(firstIncomplete < 0 ? STEPS.length - 1 : firstIncomplete);
      } catch (err: unknown) {
        if (!cancelled) {
          localStorage.removeItem(SESSION_KEY);
          setError(err instanceof Error ? err.message : 'Unable to restore onboarding progress');
        }
      } finally {
        if (!cancelled) setLoadingSession(false);
      }
    }
    void restoreSession();
    return () => { cancelled = true; };
  }, []);

  const begin = async (event: FormEvent) => {
    event.preventDefault();
    if (!tenantName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const value = await startOnboarding(tenantName.trim(), sourceMode);
      localStorage.setItem(SESSION_KEY, value.session_id);
      setSession(value);
      setStepIndex(0);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unable to start onboarding');
    } finally {
      setBusy(false);
    }
  };

  const completeStep = async () => {
    if (!session) return;
    const [step] = STEPS[stepIndex];
    setBusy(true);
    setError(null);
    try {
      const value = await advanceOnboarding(
        session.session_id,
        step,
        { completed_at: new Date().toISOString() },
        confirmLive,
      );
      setSession(value);
      setConfirmLive(false);
      if (stepIndex < STEPS.length - 1) setStepIndex((index) => index + 1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unable to save onboarding progress');
    } finally {
      setBusy(false);
    }
  };

  const completedCount = session ? STEPS.filter(([key]) => Boolean(session.steps[key])).length : 0;
  const currentStep = STEPS[stepIndex];

  return (
    <main className="p3-shell">
      <div className="p3-content">
        <PageHeader
          eyebrow="Workspace setup"
          title="Onboarding"
          description="Create a tenant, validate a read-only cloud connection, and explicitly enable monitoring when the setup is ready."
          actions={
            <>
              <Link className="p3-link-button" to="/connections">Connections</Link>
              <Link className="p3-link-button" to="/">Dashboard</Link>
            </>
          }
        />

        {error ? <Toast message={error} tone="error" /> : null}
        {loadingSession ? <Card><Skeleton rows={3} /></Card> : !session ? (
          <Card className="onboarding-start-card">
            <p className="ui-eyebrow">Create a workspace</p>
            <h2>Set up a tenant</h2>
            <p>Choose a source mode. Live monitoring stays off until an operator confirms the final step.</p>
            <form className="onboarding-form" onSubmit={begin}>
              <FormField label="Tenant name">
                <input
                  value={tenantName}
                  onChange={(event) => setTenantName(event.target.value)}
                  placeholder="Operations team"
                  required
                />
              </FormField>
              <FormField label="Source mode">
                <select
                  value={sourceMode}
                  onChange={(event) => setSourceMode(event.target.value as 'synthetic' | 'live')}
                >
                  <option value="synthetic">Synthetic demo</option>
                  <option value="live">Live connection</option>
                </select>
              </FormField>
              {sourceMode === 'live' ? (
                <div className="ui-notice">Live monitoring remains disabled until you explicitly confirm the final step.</div>
              ) : null}
              <Button variant="primary" type="submit" disabled={busy}>
                {busy ? 'Starting…' : 'Create onboarding session'}
              </Button>
            </form>
          </Card>
        ) : (
          <div className="onboarding-layout">
            <Card>
              <div className="onboarding-summary">
                <div>
                  <p className="ui-eyebrow">Tenant setup</p>
                  <h2>{session.tenant_name}</h2>
                </div>
                <Badge>{session.source_mode} mode</Badge>
              </div>
              <p className="onboarding-progress-copy">{completedCount} of {STEPS.length} steps complete</p>
              <Stepper items={STEPS.map(([, label]) => label)} activeIndex={stepIndex} />
              <ol className="p3-step-list">
                {STEPS.map(([key, label], index) => {
                  const done = Boolean(session.steps[key]);
                  return (
                    <li className={`p3-step${index === stepIndex ? ' p3-step-current' : ''}`} key={key}>
                      <span className={`p3-step-number${done ? ' p3-step-done' : ''}`}>{done ? '✓' : index + 1}</span>
                      <span>{label}</span>
                      <span className="ui-badge">{done ? 'Complete' : index === stepIndex ? 'Current' : 'Pending'}</span>
                    </li>
                  );
                })}
              </ol>
            </Card>
            <Card className="onboarding-current-step">
              <p className="ui-eyebrow">Step {stepIndex + 1} / {STEPS.length}</p>
              <h2>{currentStep[1]}</h2>
              <p>
                {stepIndex === STEPS.length - 1
                  ? 'Monitoring is only enabled after an explicit confirmation.'
                  : 'Record this setup step to save progress and continue later.'}
              </p>
              {currentStep[0] === 'enable_monitoring' && session.source_mode === 'live' ? (
                <label className="onboarding-confirm-row">
                  <input
                    type="checkbox"
                    checked={confirmLive}
                    onChange={(event) => setConfirmLive(event.target.checked)}
                  />
                  <span>I confirm that live monitoring should be enabled.</span>
                </label>
              ) : null}
              <Button
                variant="primary"
                type="button"
                onClick={() => void completeStep()}
                disabled={busy || (
                  currentStep[0] === 'enable_monitoring'
                  && session.source_mode === 'live'
                  && !confirmLive
                )}
              >
                {busy ? 'Saving…' : currentStep[0] === 'enable_monitoring' ? 'Complete setup' : 'Mark step complete'}
              </Button>
              {stepIndex === STEPS.length - 1 || session.status === 'complete' ? (
                <Link className="p3-link-button onboarding-demo-link" to="/demo">Run a demo scenario</Link>
              ) : null}
              <p className="p3-footer">Progress is resumable in this browser.</p>
            </Card>
          </div>
        )}
      </div>
    </main>
  );
}

import { FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sessionId = localStorage.getItem(SESSION_KEY);
    if (!sessionId) return;
    getOnboarding(sessionId).then((value) => {
      setSession(value);
      setTenantName(value.tenant_name);
      setSourceMode(value.source_mode);
      const firstIncomplete = STEPS.findIndex(([key]) => !value.steps[key]);
      setStepIndex(firstIncomplete < 0 ? STEPS.length - 1 : firstIncomplete);
    }).catch(() => localStorage.removeItem(SESSION_KEY));
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
    } catch (err) {
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
      const value = await advanceOnboarding(session.session_id, step, { completed_at: new Date().toISOString() }, confirmLive);
      setSession(value);
      setConfirmLive(false);
      if (stepIndex < STEPS.length - 1) setStepIndex((index) => index + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save onboarding progress');
    } finally {
      setBusy(false);
    }
  };

  const currentStep = STEPS[stepIndex];
  const completedCount = session ? STEPS.filter(([key]) => Boolean(session.steps[key])).length : 0;

  return (
    <main className="p3-shell"><div className="p3-content">
      <header className="p3-header">
        <div><p className="p3-kicker">Workspace setup</p><h1 className="p3-title">Onboarding</h1><p className="p3-subtitle">Create a tenant, validate a connection, and explicitly enable monitoring when the setup is ready.</p></div>
        <div className="p3-actions"><Link className="p3-link-button" to="/connections">Connections</Link><Link className="p3-link-button" to="/">Dashboard</Link></div>
      </header>

      {!session ? (
        <form className="p3-panel" onSubmit={begin}>
          <h2>Start a workspace</h2>
          <div className="p3-grid">
            <label className="p3-field"><span className="p3-label">Tenant name</span><input className="p3-input" value={tenantName} onChange={(event) => setTenantName(event.target.value)} placeholder="Operations team" required /></label>
            <label className="p3-field"><span className="p3-label">Source mode</span><select className="p3-select" value={sourceMode} onChange={(event) => setSourceMode(event.target.value as 'synthetic' | 'live')}><option value="synthetic">Synthetic demo</option><option value="live">Live connection</option></select></label>
          </div>
          {sourceMode === 'live' ? <p className="p3-notice">Live monitoring stays disabled until the final step is explicitly confirmed.</p> : null}
          {error ? <p className="p3-error" role="alert">{error}</p> : null}
          <button className="p3-button p3-button-primary" type="submit" disabled={busy}>{busy ? 'Starting…' : 'Create onboarding session'}</button>
        </form>
      ) : (
        <div className="p3-grid">
          <section className="p3-panel">
            <span className="p3-badge">{session.source_mode} mode</span>
            <h2 style={{ marginTop: 14 }}>{session.tenant_name}</h2>
            <p>{completedCount} of {STEPS.length} steps complete</p>
            <ol className="p3-step-list">
              {STEPS.map(([key, label], index) => {
                const done = Boolean(session.steps[key]);
                return <li className={`p3-step${index === stepIndex ? ' p3-step-current' : ''}`} key={key}>
                  <span className={`p3-step-number${done ? ' p3-step-done' : ''}`}>{done ? '✓' : index + 1}</span><span>{label}</span><span className="p3-badge">{done ? 'Complete' : index === stepIndex ? 'Current' : 'Pending'}</span>
                </li>;
              })}
            </ol>
          </section>
          <section className="p3-panel">
            <p className="p3-kicker">Step {stepIndex + 1} / {STEPS.length}</p>
            <h2>{currentStep[1]}</h2>
            <p>{stepIndex === STEPS.length - 1 ? 'Monitoring is only enabled after an explicit confirmation.' : 'Record this setup step to save progress and continue later.'}</p>
            {currentStep[0] === 'enable_monitoring' && session.source_mode === 'live' ? (
              <label className="p3-row"><span>I confirm that live monitoring should be enabled.</span><input type="checkbox" checked={confirmLive} onChange={(event) => setConfirmLive(event.target.checked)} /></label>
            ) : null}
            {error ? <p className="p3-error" role="alert">{error}</p> : null}
            <button className="p3-button p3-button-primary" type="button" onClick={completeStep} disabled={busy || (currentStep[0] === 'enable_monitoring' && session.source_mode === 'live' && !confirmLive)}>
              {busy ? 'Saving…' : currentStep[0] === 'enable_monitoring' ? 'Complete setup' : 'Mark step complete'}
            </button>
            <p className="p3-footer">Session {session.session_id} · Progress is resumable in this browser.</p>
          </section>
        </div>
      )}
    </div></main>
  );
}

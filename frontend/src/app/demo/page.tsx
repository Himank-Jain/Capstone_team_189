import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import ExplanationSectionBody from '../../components/ExplanationSectionBody';
import AlertResponseCard from '../../components/AlertResponseCard';
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  FormField,
  PageHeader,
  SeverityBadge,
  Skeleton,
  StatCard,
  Stepper,
  Toast,
} from '../../components/ui';
import useAlertStream from '../../hooks/useAlertStream';
import { getActiveTenantId, setActiveTenantId } from '../../services/apiClient';
import {
  DemoAlertResponse,
  DemoNotification,
  DemoScenario,
  DemoTenant,
  getDemoScenarios,
  getDemoStatus,
  getDemoTenants,
  getNotifyMethods,
  getSummary,
  NotifyMethod,
  pauseDemo,
  resetDemo,
  resumeDemo,
  SummaryPayload,
  triggerDemoAlert,
} from '../../services/demoApi';
import { getErrorMessage } from '../../services/errors';

const PROVIDERS = ['AWS', 'Azure', 'GCP', 'OCI'];
const TENANT_PROVIDERS: Record<string, string> = {
  amazon: 'AWS',
  microsoft: 'Azure',
  google: 'GCP',
  oracle: 'OCI',
  acme: 'AWS',
};

interface TenantScorePoint {
  ts: string;
  score: number;
  severity: string;
}

export default function DemoPage() {
  const navigate = useNavigate();
  const [tenants, setTenants] = useState<DemoTenant[]>([]);
  const [selectedTenant, setSelectedTenant] = useState(getActiveTenantId() || 'google');
  const [selectedScenario, setSelectedScenario] = useState('credential_theft');
  const [selectedProvider, setSelectedProvider] = useState(
    TENANT_PROVIDERS[getActiveTenantId() || 'google'] || 'AWS',
  );
  const [selectedIntensity, setSelectedIntensity] = useState<'low' | 'medium' | 'high'>('medium');
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [summary, setSummary] = useState<SummaryPayload | null>(null);
  const [parsedResult, setParsedResult] = useState<DemoAlertResponse | null>(null);
  const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
  const [heartbeatCount, setHeartbeatCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState('Ready');
  const [demoPaused, setDemoPaused] = useState(false);
  const [activeAlerts, setActiveAlerts] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingData, setLoadingData] = useState(true);
  const [selectedNotifyMethod, setSelectedNotifyMethod] = useState<NotifyMethod>('PAGE');
  const [notifyMethods, setNotifyMethods] = useState<NotifyMethod[]>([]);
  const [notificationData, setNotificationData] = useState<DemoNotification | undefined>();
  const [tenantScoreHistory, setTenantScoreHistory] = useState<Record<string, TenantScorePoint[]>>({});
  const [confirmReset, setConfirmReset] = useState(false);

  const { connectionState, error: wsError } = useAlertStream(() => {
    setLastHeartbeat(new Date());
    setHeartbeatCount((count) => count + 1);
  });

  const selectedTenantTrend = useMemo(
    () => tenantScoreHistory[selectedTenant] ?? [],
    [tenantScoreHistory, selectedTenant],
  );
  const selectedScenarioSpec = useMemo(
    () => scenarios.find((scenario) => scenario.value === selectedScenario) ?? null,
    [scenarios, selectedScenario],
  );
  const latestTrendPoint = selectedTenantTrend[selectedTenantTrend.length - 1] || null;
  const previousTrendPoint = selectedTenantTrend[selectedTenantTrend.length - 2] || null;
  const scoreDelta = latestTrendPoint && previousTrendPoint
    ? latestTrendPoint.score - previousTrendPoint.score
    : 0;
  const stepIndex = parsedResult ? 2 : loading ? 1 : 0;
  const heartbeatLabel = connectionState === 'connected'
    ? 'Live'
    : connectionState === 'connecting' || connectionState === 'reconnecting'
      ? 'Reconnecting'
      : 'Offline';
  const emailStatus = notificationData?.notify_method === 'EMAIL'
    ? notificationData.status === 'sent'
      ? 'Email delivered'
      : notificationData.status === 'failed'
        ? 'Email delivery failed'
        : 'Email pending'
    : 'Email not tested';

  useEffect(() => {
    let cancelled = false;
    async function loadData() {
      try {
        const [tenantData, summaryData, scenarioData, notifyData] = await Promise.all([
          getDemoTenants(),
          getSummary(),
          getDemoScenarios(),
          getNotifyMethods(),
        ]);
        if (cancelled) return;
        setTenants(tenantData);
        setScenarios(scenarioData);
        setNotifyMethods(notifyData);
        setSummary(summaryData);
        const storedTenant = getActiveTenantId();
        const initialTenant = tenantData.find((tenant) => tenant.id === storedTenant)?.id
          || tenantData[0]?.id;
        if (initialTenant) {
          setSelectedTenant(initialTenant);
          setActiveTenantId(initialTenant);
        }
        const initialScenario = scenarioData[0];
        if (initialScenario) {
          setSelectedScenario(initialScenario.value);
          setSelectedProvider((current) => (
            (initialScenario.providers || []).includes(current)
              ? current
              : initialScenario.providers?.[0] || 'AWS'
          ));
        }
        if (notifyData[0]) setSelectedNotifyMethod(notifyData[0]);
      } catch (err: unknown) {
        if (!cancelled) setError(getErrorMessage(err, 'Unable to load demo data'));
      } finally {
        if (!cancelled) setLoadingData(false);
      }
    }
    void loadData();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedTenant) return;
    setActiveTenantId(selectedTenant);
    async function refreshSummaryAndStatus() {
      try {
        const [summaryData, statusData] = await Promise.all([getSummary(), getDemoStatus()]);
        setSummary(summaryData);
        setDemoPaused(statusData.paused);
        setActiveAlerts(statusData.active_alerts ?? 0);
      } catch (err: unknown) {
        setError(getErrorMessage(err, 'Unable to refresh demo status'));
      }
    }
    void refreshSummaryAndStatus();
  }, [selectedTenant]);

  const handleTenantChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const tenantId = event.target.value;
    setSelectedTenant(tenantId);
    setActiveTenantId(tenantId);
    setSelectedProvider(TENANT_PROVIDERS[tenantId] || 'AWS');
  };

  const handleScenarioChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const scenarioId = event.target.value;
    setSelectedScenario(scenarioId);
    const scenario = scenarios.find((item) => item.value === scenarioId);
    if (scenario && !(scenario.providers || []).includes(selectedProvider)) {
      setSelectedProvider(scenario.providers?.[0] || 'AWS');
    }
  };

  const runDemo = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await triggerDemoAlert(
        selectedTenant,
        selectedScenario,
        selectedNotifyMethod,
        selectedProvider,
        selectedIntensity,
      );
      if (!data.phase3?.explanation || !Array.isArray(data.phase3.recommendations)) {
        throw new Error('Demo response did not include the Phase 3 RCA explanation and checks.');
      }
      setParsedResult(data);
      setNotificationData(data.notification);
      setStatusMessage('Scenario injected');
      const payload = data.alert_payload;
      if (Number.isFinite(payload.final_score)) {
        setTenantScoreHistory((previous) => {
          const existing = previous[selectedTenant] ?? [];
          const nextPoint: TenantScorePoint = {
            ts: payload.batch_ts || new Date().toISOString(),
            score: payload.final_score,
            severity: payload.severity || 'UNKNOWN',
          };
          return { ...previous, [selectedTenant]: [...existing, nextPoint].slice(-12) };
        });
      }
      const statusData = await getDemoStatus();
      setDemoPaused(statusData.paused);
      setActiveAlerts(statusData.active_alerts ?? 0);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Demo generation failed'));
    } finally {
      setLoading(false);
    }
  };

  const togglePause = async (action: 'pause' | 'resume') => {
    try {
      const result = action === 'pause' ? await pauseDemo() : await resumeDemo();
      setDemoPaused(result.paused);
      setStatusMessage(action === 'pause' ? 'Demo paused' : 'Demo resumed');
      setError(null);
    } catch (err: unknown) {
      setError(getErrorMessage(err, `Failed to ${action} demo`));
    }
  };

  const clearDemo = async () => {
    try {
      const result = await resetDemo();
      setActiveAlerts(result.active_alerts ?? 0);
      setDemoPaused(result.paused);
      setStatusMessage('Tenant reset to baseline');
      setParsedResult(null);
      setNotificationData(undefined);
      setTenantScoreHistory((previous) => ({ ...previous, [selectedTenant]: [] }));
      setConfirmReset(false);
      setError(null);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to reset demo tenant'));
    }
  };

  return (
    <main className="p3-shell">
      <div className="p3-content">
        <PageHeader
          eyebrow="Guided simulation"
          title="Live demo control"
          description="Inject a reproducible synthetic scenario and inspect its alert, evidence, and knowledge-based investigation."
          actions={<Link className="p3-link-button" to="/incidents">Browse incidents</Link>}
        />
        <Card className="demo-stepper-card">
          <Stepper items={['Configure', 'Inject', 'Investigate']} activeIndex={stepIndex} />
        </Card>

        {error ? <Toast message={error} tone="error" /> : null}
        {loadingData ? <Card><Skeleton rows={5} /></Card> : (
          <div className="demo-layout">
            <section className="demo-main-column">
              <Card>
                <div className="section-heading">
                  <div>
                    <p className="ui-eyebrow">Scenario setup</p>
                    <h2>Configure an injection</h2>
                  </div>
                  <span className="ui-badge ui-status-acknowledged">Deterministic demo</span>
                </div>
                <div className="demo-form-grid">
                  <FormField label="Tenant">
                    <select value={selectedTenant} onChange={handleTenantChange}>
                      {tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
                    </select>
                  </FormField>
                  <FormField label="Scenario">
                    <select value={selectedScenario} onChange={handleScenarioChange}>
                      {(['malicious', 'benign', 'ambiguous'] as const).map((category) => (
                        <optgroup key={category} label={category[0].toUpperCase() + category.slice(1)}>
                          {scenarios.filter((scenario) => scenario.category === category).map((scenario) => (
                            <option key={scenario.value} value={scenario.value}>{scenario.label}</option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                  </FormField>
                  <FormField label="Cloud provider">
                    <select value={selectedProvider} onChange={(event) => setSelectedProvider(event.target.value)}>
                      {PROVIDERS.map((provider) => <option key={provider} value={provider}>{provider}</option>)}
                    </select>
                  </FormField>
                  <FormField label="Intensity">
                    <select
                      value={selectedIntensity}
                      onChange={(event) => setSelectedIntensity(event.target.value as 'low' | 'medium' | 'high')}
                    >
                      {(['low', 'medium', 'high'] as const).map((intensity) => (
                        <option key={intensity} value={intensity}>{intensity[0].toUpperCase() + intensity.slice(1)}</option>
                      ))}
                    </select>
                  </FormField>
                  <FormField label="Notification channel">
                    <select
                      value={selectedNotifyMethod}
                      onChange={(event) => setSelectedNotifyMethod(event.target.value as NotifyMethod)}
                    >
                      {notifyMethods.map((method) => <option key={method} value={method}>{method}</option>)}
                    </select>
                  </FormField>
                </div>
                {selectedScenarioSpec ? (
                  <div className="demo-scenario-summary">
                    <div className="demo-scenario-heading">
                      <h3>{selectedScenarioSpec.label}</h3>
                      <span className="ui-badge">{selectedScenarioSpec.category}</span>
                    </div>
                    <p>{selectedScenarioSpec.description}</p>
                    <small>Minimum severity target: {selectedScenarioSpec.minimum_severity}</small>
                  </div>
                ) : <EmptyState title="No scenarios available" description="Scenario definitions have not loaded for this workspace." />}
                <Button
                  className="demo-inject-button"
                  variant="primary"
                  type="button"
                  onClick={() => void runDemo()}
                  disabled={loading || !selectedTenant || !selectedScenarioSpec?.providers?.includes(selectedProvider)}
                >
                  {loading ? 'Injecting…' : 'Inject scenario'}
                </Button>
              </Card>

              <Card>
                <div className="section-heading">
                  <div>
                    <p className="ui-eyebrow">Live control</p>
                    <h2>Demo tenant status</h2>
                  </div>
                  <span className={`ui-badge ${demoPaused ? 'ui-severity-medium' : 'ui-status-resolved'}`}>
                    {demoPaused ? 'Paused' : 'Running'}
                  </span>
                </div>
                <div className="demo-stat-grid">
                  <StatCard label="Active alerts" value={activeAlerts} tone="critical" />
                  <StatCard label="Last action" value={statusMessage} tone="brand" />
                  <StatCard label="Heartbeat" value={heartbeatLabel} tone={connectionState === 'connected' ? 'success' : 'warning'} />
                </div>
                <div className="demo-control-actions">
                  <Button type="button" onClick={() => void togglePause('pause')} disabled={demoPaused}>Pause</Button>
                  <Button type="button" onClick={() => void togglePause('resume')} disabled={!demoPaused}>Resume</Button>
                  <Button type="button" variant="danger" onClick={() => setConfirmReset(true)}>
                    Reset demo tenant to baseline
                  </Button>
                </div>
                <p className="demo-system-detail">
                  {lastHeartbeat ? `Last heartbeat ${lastHeartbeat.toLocaleTimeString()}` : 'Waiting for a backend heartbeat'}
                  {' · '}{heartbeatCount} events received
                </p>
                {wsError ? <Toast message={wsError} tone="error" /> : null}
                <p className="demo-system-detail">{emailStatus}</p>
              </Card>

              <Card>
                <div className="section-heading">
                  <div>
                    <p className="ui-eyebrow">Score history</p>
                    <h2>Tenant trend</h2>
                  </div>
                  <span className="ui-badge">{selectedTenantTrend.length} recent points</span>
                </div>
                <div className="demo-stat-grid">
                  <StatCard label="Model confidence" value={summary?.model_confidence ? `${(summary.model_confidence * 100).toFixed(0)}%` : '—'} tone="success" />
                  <StatCard label="Critical alerts" value={summary?.critical_alerts ?? '—'} tone="critical" />
                  <StatCard label="Score delta" value={latestTrendPoint && previousTrendPoint ? `${scoreDelta >= 0 ? '+' : ''}${(scoreDelta * 100).toFixed(1)}%` : '—'} tone={scoreDelta >= 0 ? 'warning' : 'success'} />
                </div>
                {selectedTenantTrend.length ? (
                  <div className="demo-trend-list" aria-label="Recent tenant score history">
                    {selectedTenantTrend.slice().reverse().map((point, index) => (
                      <div className="demo-trend-row" key={`${point.ts}-${index}`}>
                        <span>{new Date(point.ts).toLocaleTimeString()}</span>
                        <meter min="0" max="1" value={point.score} aria-label={`Score ${Math.round(point.score * 100)} percent`} />
                        <SeverityBadge severity={point.severity} />
                        <strong>{(point.score * 100).toFixed(1)}%</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No score history yet" description="Inject a scenario to record the first score for this tenant." />
                )}
              </Card>

              <Card className="demo-threat-library">
                <div className="section-heading">
                  <div>
                    <p className="ui-eyebrow">Scenario catalog</p>
                    <h2>Threat library</h2>
                  </div>
                  <span className="ui-badge">{scenarios.length} scenarios</span>
                </div>
                {(['malicious', 'benign', 'ambiguous'] as const).map((category) => {
                  const categoryScenarios = scenarios.filter((scenario) => scenario.category === category);
                  if (!categoryScenarios.length) return null;
                  return (
                    <section className="demo-library-group" key={category}>
                      <h3>{category[0].toUpperCase() + category.slice(1)}</h3>
                      {categoryScenarios.map((scenario) => (
                        <button
                          className="demo-library-item"
                          type="button"
                          key={scenario.value}
                          onClick={() => {
                            setSelectedScenario(scenario.value);
                            if (!scenario.providers.includes(selectedProvider)) {
                              setSelectedProvider(scenario.providers[0] || 'AWS');
                            }
                          }}
                        >
                          <strong>{scenario.label}</strong>
                          <span>{scenario.description}</span>
                        </button>
                      ))}
                    </section>
                  );
                })}
                {!scenarios.length ? <EmptyState title="Threat library unavailable" description="Scenario definitions could not be loaded." /> : null}
              </Card>
            </section>

            <aside className="demo-side-column">
              {parsedResult ? (
                <>
                  <AlertResponseCard alert={parsedResult.alert_payload} notification={notificationData} />
                  <Card>
                    <p className="ui-eyebrow">Evidence-based explanation</p>
                    <h2>{parsedResult.phase3.explanation.headline}</h2>
                    <p className="incident-explanation-context">
                      Root cause category <strong>{parsedResult.phase3.explanation.cause_category.replace(/_/g, ' ').toLowerCase()}</strong>
                      {parsedResult.phase3.explanation.mitigation_mode === 'threat_specific' && parsedResult.phase3.explanation.match_basis
                        ? <> · {parsedResult.phase3.explanation.match_basis}</>
                        : null}
                    </p>
                    {parsedResult.phase3.explanation.is_fallback ? (
                      <Toast message="No confident category. Review the evidence and recommended checks; this is not a diagnosis." />
                    ) : null}
                    {parsedResult.phase3.explanation.sections.map((section) => (
                      <article className="demo-explanation-section" key={section.heading}>
                        <h3>{section.heading}</h3>
                        <ExplanationSectionBody body={section.body} />
                      </article>
                    ))}
                    <p className="p3-footer">
                      Knowledge base {parsedResult.phase3.explanation.kb_version}
                      {' · '}Hypothesis only; unsupervised signals do not establish an attack diagnosis.
                    </p>
                    <Button
                      type="button"
                      onClick={() => navigate(`/incidents/${encodeURIComponent(parsedResult.alert_payload.alert_id)}`)}
                    >
                      View full investigation
                    </Button>
                  </Card>
                  <Card>
                    <p className="ui-eyebrow">Recommended investigation</p>
                    {parsedResult.phase3.recommendations.length ? (
                      <div className="demo-check-list">
                        {parsedResult.phase3.recommendations.map((check) => (
                          <article key={`${check.check}-${check.why}`}>
                            <h3>{check.check}</h3>
                            <p>{check.why}</p>
                            <span>Expected: {check.expected_result}</span>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <EmptyState title="No checks returned" description="The investigation did not produce any recommended checks." />
                    )}
                  </Card>
                </>
              ) : (
                <Card>
                  <EmptyState
                    title="Ready to investigate"
                    description="Choose a tenant, scenario, provider, and intensity. After injection, the alert and structured RCA will appear here."
                  />
                </Card>
              )}
            </aside>
          </div>
        )}
        <ConfirmDialog
          open={confirmReset}
          title="Reset this synthetic tenant?"
          description="This clears the demo tenant’s incidents and local demo state. No cloud resources are changed."
          confirmLabel="Reset tenant"
          onConfirm={() => void clearDemo()}
          onCancel={() => setConfirmReset(false)}
        />
      </div>
    </main>
  );
}

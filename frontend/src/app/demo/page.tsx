'use client';

import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useAlertStream from '../../hooks/useAlertStream';
import {
  getDemoTenants,
  getSummary,
  getDemoScenarios,
  getNotifyMethods,
  triggerDemoAlert,
  getDemoStatus,
  pauseDemo,
  resumeDemo,
  resetDemo,
  callExplainableApi,
  DemoTenant,
  SummaryPayload,
  DemoScenario,
  NotifyMethod,
} from '../../services/demoApi';
import { getActiveTenantId, setActiveTenantId } from '../../services/apiClient';
import DemoStatusCard from '../../components/DemoStatusCard';
import AlertResponseCard from '../../components/AlertResponseCard';

const MODES = [
  { value: 'attack', label: 'Attack' },
  { value: 'normal', label: 'Normal baseline' },
];

export default function DemoPage() {
  const navigate = useNavigate();
  const [tenants, setTenants] = useState<DemoTenant[]>([]);
  const [selectedTenant, setSelectedTenant] = useState(getActiveTenantId() || 'google');
  const [selectedScenario, setSelectedScenario] = useState('credential_theft');
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [status, setStatus] = useState('idle');
  const [summary, setSummary] = useState<SummaryPayload | null>(null);
  const [parsedResult, setParsedResult] = useState<any | null>(null);
  const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
  const [heartbeatCount, setHeartbeatCount] = useState(0);
  const [explainData, setExplainData] = useState<any | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState('idle');
  const [demoPaused, setDemoPaused] = useState(false);
  const [activeAlerts, setActiveAlerts] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [selectedNotifyMethod, setSelectedNotifyMethod] = useState<NotifyMethod>('PAGE');
  const [notifyMethods, setNotifyMethods] = useState<NotifyMethod[]>([]);
  const [mode, setMode] = useState<'attack' | 'normal'>('attack');
  const [notificationData, setNotificationData] = useState<any | null>(null);
  const [tenantScoreHistory, setTenantScoreHistory] = useState<Record<string, Array<{
    ts: string;
    scenario: string;
    mode: 'attack' | 'normal';
    score: number;
    severity: string;
  }>>>({});

  const { connectionState, error: wsError } = useAlertStream((_message) => {
    setLastHeartbeat(new Date());
    setHeartbeatCount((c) => c + 1);
  });

  const heartbeatPresentation = useMemo(() => {
    if (connectionState === 'connected') {
      return {
        label: 'Live',
        color: '#22c55e',
        detail: 'Heartbeat stream is healthy',
      };
    }

    if (connectionState === 'reconnecting' || connectionState === 'connecting') {
      return {
        label: 'Reconnecting',
        color: '#f59e0b',
        detail: 'Recovering the live stream',
      };
    }

    return {
      label: 'Offline',
      color: '#ef4444',
      detail: 'Backend heartbeat is unavailable',
    };
  }, [connectionState]);

  const selectedTenantTrend = useMemo(
    () => tenantScoreHistory[selectedTenant] ?? [],
    [tenantScoreHistory, selectedTenant]
  );

  const latestTrendPoint = selectedTenantTrend.length > 0
    ? selectedTenantTrend[selectedTenantTrend.length - 1]
    : null;

  const previousTrendPoint = selectedTenantTrend.length > 1
    ? selectedTenantTrend[selectedTenantTrend.length - 2]
    : null;

  const scoreDelta = latestTrendPoint && previousTrendPoint
    ? latestTrendPoint.score - previousTrendPoint.score
    : 0;

  const emailChannelPresentation = useMemo(() => {
    if (notificationData?.notify_method === 'EMAIL') {
      if (notificationData.status === 'sent') {
        return {
          label: 'Ready',
          color: '#22c55e',
          detail: 'Latest email delivery succeeded',
        };
      }

      if (notificationData.status === 'failed') {
        return {
          label: 'Auth / Delivery Error',
          color: '#ef4444',
          detail: notificationData.message || 'Latest email delivery failed',
        };
      }

      return {
        label: 'Pending',
        color: '#f59e0b',
        detail: 'Waiting for delivery confirmation',
      };
    }

    return {
      label: 'Untested',
      color: '#64748b',
      detail: 'Trigger an EMAIL alert to verify channel health',
    };
  }, [notificationData]);

  useEffect(() => {
    setStatus('ready');
    async function loadData() {
      try {
        const [tenantData, summaryData, scenarioData, notifyData] = await Promise.all([
          getDemoTenants(),
          getSummary(),
          getDemoScenarios(),
          getNotifyMethods(),
        ]);
        setTenants(tenantData);
        setScenarios(scenarioData);
        setNotifyMethods(notifyData);
        setSummary(summaryData);
        const storedTenant = getActiveTenantId();
        if (storedTenant && tenantData.some((t) => t.id === storedTenant)) {
          setSelectedTenant(storedTenant);
        } else if (tenantData.length) {
          setSelectedTenant(tenantData[0].id);
          setActiveTenantId(tenantData[0].id);
        }
        if (scenarioData.length) {
          setSelectedScenario(scenarioData[0].value);
        }
        if (notifyData.length) {
          setSelectedNotifyMethod(notifyData[0]);
        }
      } catch (err: any) {
        setError(err?.message || 'Unable to load demo data');
      }
    }
    loadData();
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
      } catch (err: any) {
        setError(err?.message || 'Unable to refresh demo status');
      }
    }
    refreshSummaryAndStatus();
  }, [selectedTenant]);

  const handleTenantChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const tenantId = event.target.value;
    setSelectedTenant(tenantId);
    setActiveTenantId(tenantId);
  };

  const handleScenarioChange = (event: ChangeEvent<HTMLSelectElement>) => {
    setSelectedScenario(event.target.value);
  };

  const handleNotifyMethodChange = (event: ChangeEvent<HTMLSelectElement>) => {
    setSelectedNotifyMethod(event.target.value as NotifyMethod);
  };

  const handleModeChange = (event: ChangeEvent<HTMLSelectElement>) => {
    setMode(event.target.value as 'attack' | 'normal');
  };

  const runDemo = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await triggerDemoAlert(selectedTenant, selectedScenario, selectedNotifyMethod, mode);
      setParsedResult(data);
      setNotificationData(data.notification);
      setStatusMessage('attack submitted');
      const alertPayload = data.alert_payload as any;
      if (alertPayload?.final_score !== undefined) {
        setTenantScoreHistory((prev) => {
          const existing = prev[selectedTenant] ?? [];
          const nextPoint = {
            ts: String(alertPayload.batch_ts || new Date().toISOString()),
            scenario: data.scenario,
            mode: data.mode as 'attack' | 'normal',
            score: Number(alertPayload.final_score),
            severity: String(alertPayload.severity ?? 'UNKNOWN'),
          };
          const nextHistory = [...existing, nextPoint].slice(-12);
          return {
            ...prev,
            [selectedTenant]: nextHistory,
          };
        });
      }
      const statusData = await getDemoStatus();
      setDemoPaused(statusData.paused);
      setActiveAlerts(statusData.active_alerts ?? 0);
    } catch (err: any) {
      setError(err?.message || 'Demo generation failed');
    } finally {
      setLoading(false);
    }
  };

  const fetchExplainability = async () => {
    setExplainError(null);
    setExplainData(null);
    if (!parsedResult) {
      setExplainError('No demo response available to explain');
      return;
    }
    const apiPath = parsedResult.explainable_api || '/phase2/alerting/api/alert_api';
    setExplainLoading(true);
    try {
      const resp = await callExplainableApi(apiPath, parsedResult.alert_payload || parsedResult.alert);
      setExplainData(resp);
    } catch (err: any) {
      setExplainError(err?.message || 'Explainability request failed');
    } finally {
      setExplainLoading(false);
    }
  };

  return (
    <main style={{ padding: '0', minHeight: '100vh', background: '#0b0f17', color: '#f3f4f6' }}>
      {/* Breadcrumb Navigation */}
      <nav style={{ padding: '16px 24px', background: '#111827', borderBottom: '1px solid #1f2937' }}>
        <div style={{ maxWidth: '1280px', margin: '0 auto', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            type="button"
            onClick={() => navigate('/')}
            style={{
              padding: '8px 12px',
              borderRadius: '8px',
              border: 'none',
              background: 'transparent',
              color: '#60a5fa',
              cursor: 'pointer',
              fontSize: '14px'
            }}
          >
            ← Back to Dashboard
          </button>
          <span style={{ color: '#4b5563' }}>/</span>
          <span style={{ fontSize: '14px', color: '#9ca3af' }}>Live Demo</span>
        </div>
      </nav>

      {/* Main Content */}
      <section style={{ padding: '24px', maxWidth: '1280px', margin: '0 auto' }}>
        <h1 style={{ fontSize: '32px', marginBottom: '8px', fontWeight: 'bold' }}>Live Demo Control</h1>
        <p style={{ color: '#9ca3af', marginBottom: '24px', fontSize: '15px' }}>
          Select a tenant, choose an attack scenario, and dispatch synthetic events to visualize the system response in real-time.
        </p>

        <div style={{ display: 'grid', gap: '20px' }}>
          {/* Configuration Card */}
          <div style={{ display: 'grid', gap: '14px', padding: '18px', borderRadius: '16px', background: '#111827', border: '1px solid #1f2937' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
              <div>
                <p style={{ margin: 0, color: '#9ca3af' }}>Pipeline status</p>
                <strong>{status}</strong>
              </div>
              <div>
                <p style={{ margin: 0, color: '#9ca3af' }}>Heartbeat stream</p>
                <strong>{heartbeatPresentation.label}</strong>
              </div>
            </div>

            <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: '1fr 1fr' }}>
              <label style={{ display: 'grid', gap: '8px' }}>
                Tenant
                <select value={selectedTenant} onChange={handleTenantChange} style={{ padding: '10px', borderRadius: '10px', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155' }}>
                  {tenants.map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
                  ))}
                </select>
              </label>

              <label style={{ display: 'grid', gap: '8px' }}>
                Scenario
                <select value={selectedScenario} onChange={handleScenarioChange} style={{ padding: '10px', borderRadius: '10px', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155' }}>
                  {scenarios.map((scenario) => (
                    <option key={scenario.value} value={scenario.value}>{scenario.label}</option>
                  ))}
                </select>
              </label>
            </div>

            <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: '1fr 1fr' }}>
              <label style={{ display: 'grid', gap: '8px' }}>
                Notify Method
                <select value={selectedNotifyMethod} onChange={handleNotifyMethodChange} style={{ padding: '10px', borderRadius: '10px', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155' }}>
                  {notifyMethods.map((method) => (
                    <option key={method} value={method}>{method}</option>
                  ))}
                </select>
              </label>

              <label style={{ display: 'grid', gap: '8px' }}>
                Mode
                <select value={mode} onChange={handleModeChange} style={{ padding: '10px', borderRadius: '10px', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155' }}>
                  {MODES.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>

            <button
              type="button"
              onClick={runDemo}
              disabled={loading || !selectedTenant}
              style={{ padding: '14px 18px', borderRadius: '12px', border: 'none', background: '#2563eb', color: 'white', cursor: 'pointer', maxWidth: '240px' }}
            >
              {loading ? 'Dispatching...' : mode === 'normal' ? 'Dispatch Normal Baseline' : 'Dispatch Demo Attack'}
            </button>

            {error ? <p style={{ color: '#fca5a5' }}>{error}</p> : null}
          </div>

          {/* Demo Controls Card */}
          <div style={{ display: 'grid', gap: '14px', padding: '18px', borderRadius: '16px', background: '#111827', border: '1px solid #1f2937' }}>
            <h2 style={{ margin: 0, fontSize: '20px' }}>Demo controls</h2>
            <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
              <DemoStatusCard title="Tenant status" value={demoPaused ? 'Paused' : 'Running'} accent="#f59e0b" />
              <DemoStatusCard title="Active alerts" value={activeAlerts} accent="#2563eb" />
              <DemoStatusCard title="Last action" value={statusMessage} accent="#22c55e" />
            </div>
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={async () => {
                  try {
                    const data = await pauseDemo();
                    setDemoPaused(data.paused);
                    setStatusMessage('paused');
                  } catch (err: any) {
                    setError(err?.message || 'Failed to pause');
                  }
                }}
                style={{ padding: '10px 14px', borderRadius: '10px', border: 'none', background: '#f97316', color: 'white', cursor: 'pointer' }}
              >
                Pause
              </button>
              <button
                type="button"
                onClick={async () => {
                  try {
                    const data = await resumeDemo();
                    setDemoPaused(data.paused);
                    setStatusMessage('resumed');
                  } catch (err: any) {
                    setError(err?.message || 'Failed to resume');
                  }
                }}
                style={{ padding: '10px 14px', borderRadius: '10px', border: 'none', background: '#22c55e', color: 'white', cursor: 'pointer' }}
              >
                Resume
              </button>
              <button
                type="button"
                onClick={async () => {
                  try {
                    const data = await resetDemo();
                    setActiveAlerts(data.active_alerts ?? 0);
                    setDemoPaused(data.paused);
                    setStatusMessage('reset');
                    setParsedResult(null);
                    setNotificationData(null);
                    setExplainData(null);
                    setTenantScoreHistory((prev) => ({
                      ...prev,
                      [selectedTenant]: [],
                    }));
                  } catch (err: any) {
                    setError(err?.message || 'Failed to reset');
                  }
                }}
                style={{ padding: '10px 14px', borderRadius: '10px', border: 'none', background: '#ef4444', color: 'white', cursor: 'pointer' }}
              >
                Reset
              </button>
            </div>
          </div>

          {/* Insights Card */}
          <div style={{ display: 'grid', gap: '14px', padding: '18px', borderRadius: '16px', background: '#111827', border: '1px solid #1f2937' }}>
            <h2 style={{ margin: 0, fontSize: '20px' }}>Demo insights</h2>
            <div style={{ display: 'grid', gap: '12px', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
              <DemoStatusCard title="Loaded tenants" value={tenants.length} accent="#3b82f6" />
              <DemoStatusCard title="Model confidence" value={summary?.model_confidence ? `${(summary.model_confidence * 100).toFixed(0)}%` : '--'} accent="#8b5cf6" />
              <DemoStatusCard title="Critical alerts" value={summary?.critical_alerts ?? '--'} accent="#ef4444" />
            </div>
          </div>

          {/* System Status Card */}
          <div style={{ display: 'grid', gap: '14px', padding: '18px', borderRadius: '16px', background: '#111827', border: '1px solid #1f2937' }}>
            <h2 style={{ margin: 0, fontSize: '20px' }}>System Status</h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
              {/* WebSocket Connection Status */}
              <div style={{ padding: '12px', borderRadius: '12px', background: '#0f172a', border: '1px solid #1f2937' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                  <div
                    style={{
                      width: '10px',
                      height: '10px',
                      borderRadius: '50%',
                      background: heartbeatPresentation.color,
                      animation: connectionState !== 'disconnected' ? 'pulse 2s infinite' : 'none'
                    }}
                  />
                  <span style={{ fontSize: '14px', fontWeight: '600', color: heartbeatPresentation.color }}>
                    {heartbeatPresentation.label}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: '12px', color: '#9ca3af' }}>{heartbeatPresentation.detail}</p>
              </div>

              {/* Last Heartbeat */}
              <div style={{ padding: '12px', borderRadius: '12px', background: '#0f172a', border: '1px solid #1f2937' }}>
                <div style={{ marginBottom: '8px' }}>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: '600', color: '#f3f4f6' }}>
                    {lastHeartbeat ? (
                      <>
                        {lastHeartbeat.toLocaleTimeString()}
                      </>
                    ) : (
                      'Waiting...'
                    )}
                  </p>
                </div>
                <p style={{ margin: 0, fontSize: '12px', color: '#9ca3af' }}>Last Heartbeat</p>
              </div>

              {/* Heartbeat Count */}
              <div style={{ padding: '12px', borderRadius: '12px', background: '#0f172a', border: '1px solid #1f2937' }}>
                <div style={{ marginBottom: '8px' }}>
                  <p style={{ margin: 0, fontSize: '14px', fontWeight: '600', color: '#60a5fa' }}>
                    {heartbeatCount} events
                  </p>
                </div>
                <p style={{ margin: 0, fontSize: '12px', color: '#9ca3af' }}>Total Received</p>
              </div>

              {/* Email Channel Readiness */}
              <div style={{ padding: '12px', borderRadius: '12px', background: '#0f172a', border: '1px solid #1f2937' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                  <div
                    style={{
                      width: '10px',
                      height: '10px',
                      borderRadius: '50%',
                      background: emailChannelPresentation.color,
                    }}
                  />
                  <span style={{ fontSize: '14px', fontWeight: '600', color: emailChannelPresentation.color }}>
                    {emailChannelPresentation.label}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: '12px', color: '#9ca3af' }}>{emailChannelPresentation.detail}</p>
              </div>
            </div>
            {wsError && (
              <div style={{ padding: '10px', borderRadius: '8px', background: '#7f1d1d', border: '1px solid #dc2626', color: '#fca5a5', fontSize: '13px' }}>
                ⚠️ {wsError}
              </div>
            )}
            <style>{`
              @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
              }
            `}</style>
          </div>

          {/* Tenant Trend Panel */}
          <div style={{ display: 'grid', gap: '14px', padding: '18px', borderRadius: '16px', background: '#111827', border: '1px solid #1f2937' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ margin: 0, fontSize: '20px' }}>Tenant Score Trend</h2>
              <span style={{ color: '#9ca3af', fontSize: '12px' }}>{selectedTenantTrend.length} recent points</span>
            </div>

            <div style={{ display: 'grid', gap: '12px', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
              <DemoStatusCard
                title="Latest Score"
                value={latestTrendPoint ? `${(latestTrendPoint.score * 100).toFixed(1)}%` : '--'}
                accent="#38bdf8"
              />
              <DemoStatusCard
                title="Score Delta"
                value={latestTrendPoint && previousTrendPoint ? `${scoreDelta >= 0 ? '+' : ''}${(scoreDelta * 100).toFixed(1)}%` : '--'}
                accent={scoreDelta >= 0 ? '#f97316' : '#22c55e'}
              />
              <DemoStatusCard
                title="Latest Severity"
                value={latestTrendPoint ? latestTrendPoint.severity : '--'}
                accent="#a78bfa"
              />
            </div>

            {selectedTenantTrend.length > 0 ? (
              <div style={{ display: 'grid', gap: '8px' }}>
                {selectedTenantTrend.slice().reverse().map((point, index) => {
                  const intensity = Math.max(0.12, Math.min(0.95, point.score));
                  return (
                    <div
                      key={`${point.ts}-${index}`}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '140px 1fr 110px',
                        gap: '10px',
                        alignItems: 'center',
                        padding: '8px 10px',
                        borderRadius: '10px',
                        background: '#0f172a',
                        border: '1px solid #1f2937',
                      }}
                    >
                      <span style={{ color: '#94a3b8', fontSize: '12px' }}>
                        {new Date(point.ts).toLocaleTimeString()}
                      </span>
                      <div style={{ height: '10px', borderRadius: '999px', background: '#1e293b', overflow: 'hidden' }}>
                        <div
                          style={{
                            width: `${Math.round(point.score * 100)}%`,
                            height: '100%',
                            background: `rgba(56, 189, 248, ${intensity})`,
                          }}
                        />
                      </div>
                      <span style={{ color: '#e2e8f0', fontSize: '12px', textAlign: 'right' }}>
                        {(point.score * 100).toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p style={{ margin: 0, color: '#94a3b8', fontSize: '14px' }}>
                Dispatch alerts for this tenant to visualize score progression over time.
              </p>
            )}
          </div>

          {/* Alert Response & Explainability Card */}
          {parsedResult && parsedResult.alert_payload ? (
            <div style={{ display: 'grid', gap: '12px', padding: '18px', borderRadius: '16px', background: '#0b0f17', border: '1px solid #1f2937' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h2 style={{ margin: 0, fontSize: '20px' }}>Alert Details & Analysis</h2>
                <button
                  type="button"
                  onClick={fetchExplainability}
                  disabled={explainLoading}
                  style={{
                    padding: '8px 14px',
                    borderRadius: '8px',
                    border: 'none',
                    background: '#1f2937',
                    color: '#60a5fa',
                    cursor: 'pointer',
                    fontSize: '13px',
                    fontWeight: '500',
                  }}
                >
                  {explainLoading ? '🔄 Analyzing...' : '🔍 Get Explainability'}
                </button>
              </div>
              <AlertResponseCard
                alert={parsedResult.alert_payload}
                notification={notificationData}
                explainability={explainData}
              />
              {explainError && <p style={{ margin: 0, color: '#fca5a5', fontSize: '13px' }}>⚠️ {explainError}</p>}
            </div>
          ) : (
            <div style={{ display: 'grid', gap: '12px', padding: '18px', borderRadius: '16px', background: '#111827', border: '1px solid #1f2937' }}>
              <h2 style={{ margin: 0, fontSize: '20px' }}>Alert Details & Analysis</h2>
              <p style={{ margin: 0, color: '#9ca3af', fontSize: '14px' }}>
                🚀 Dispatch a demo attack above to see alert details, analysis, and model explainability insights.
              </p>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

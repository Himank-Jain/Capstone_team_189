interface AlertPayload {
  alert_id: string;
  entity_id: string;
  batch_ts: string;
  final_score: number;
  severity: string;
  sev_level: string;
  target_team: string;
  cloud_provider: string;
  region: string;
  [key: string]: any;
}

interface ExplainabilityData {
  alert_id: string;
  entity_id: string;
  explainability: {
    model_version: string;
    prediction_score: number;
    prediction_confidence: number;
    severity_prediction: string;
    key_factors: Array<{
      factor: string;
      impact: string;
      contribution: number;
      description: string;
    }>;
    model_components: {
      deviation_score: number;
      drift_score: number;
      similarity_score: number;
      ensemble_boosting: string;
      lstm_temporal_window: string;
    };
    recommendations: string[];
    timestamp: string;
  };
}

interface Notification {
  notify_method: string;
  status: string;
  message: string;
  email_to?: string;
}

interface AlertResponseCardProps {
  alert: AlertPayload;
  notification?: Notification;
  explainability?: ExplainabilityData;
}

const getSeverityColor = (severity: string): { bg: string; border: string; text: string; badge: string } => {
  const colors: Record<string, { bg: string; border: string; text: string; badge: string }> = {
    CRITICAL: { bg: '#7f1d1d', border: '#dc2626', text: '#fca5a5', badge: '#dc2626' },
    HIGH: { bg: '#7c2d12', border: '#f97316', text: '#fed7aa', badge: '#f97316' },
    MEDIUM: { bg: '#713f12', border: '#eab308', text: '#fef08a', badge: '#eab308' },
    LOW: { bg: '#143e1e', border: '#22c55e', text: '#bbf7d0', badge: '#22c55e' },
  };
  return colors[severity] || colors.LOW;
};

const formatDate = (dateString: string): string => {
  try {
    const date = new Date(dateString);
    return date.toLocaleString();
  } catch {
    return dateString;
  }
};

export default function AlertResponseCard({ alert, notification, explainability }: AlertResponseCardProps) {
  const severityColors = getSeverityColor(alert.severity);
  const notificationColor = notification?.status === 'failed'
    ? '#ef4444'
    : notification?.status === 'sent' || notification?.status === 'displayed'
      ? '#22c55e'
      : '#f59e0b';

  return (
    <div style={{ display: 'grid', gap: '16px' }}>
      {/* Main Alert Card */}
      <div
        style={{
          padding: '18px',
          borderRadius: '12px',
          background: '#111827',
          border: `2px solid ${severityColors.border}`,
          boxShadow: `0 0 12px ${severityColors.border}20`,
        }}
      >
        {/* Header with Severity Badge */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h3 style={{ margin: 0, fontSize: '18px', color: '#f3f4f6' }}>Security Alert</h3>
          <div
            style={{
              padding: '6px 14px',
              borderRadius: '8px',
              background: severityColors.badge,
              color: 'white',
              fontWeight: 'bold',
              fontSize: '12px',
              textTransform: 'uppercase',
            }}
          >
            {alert.severity}
          </div>
        </div>

        {/* Alert Metrics Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '14px',
            marginBottom: '16px',
            paddingBottom: '16px',
            borderBottom: `1px solid #1f2937`,
          }}
        >
          <div>
            <p style={{ margin: '0 0 4px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase' }}>Alert ID</p>
            <p style={{ margin: 0, color: '#f3f4f6', fontSize: '13px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
              {alert.alert_id.substring(0, 12)}...
            </p>
          </div>
          <div>
            <p style={{ margin: '0 0 4px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase' }}>Entity ID</p>
            <p style={{ margin: 0, color: '#f3f4f6', fontSize: '13px', fontWeight: '500' }}>{alert.entity_id}</p>
          </div>
          <div>
            <p style={{ margin: '0 0 4px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase' }}>Risk Score</p>
            <p style={{ margin: 0, color: severityColors.text, fontSize: '14px', fontWeight: 'bold' }}>
              {(alert.final_score * 100).toFixed(1)}%
            </p>
          </div>
          <div>
            <p style={{ margin: '0 0 4px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase' }}>Classification</p>
            <p style={{ margin: 0, color: '#f3f4f6', fontSize: '13px' }}>{alert.sev_level}</p>
          </div>
        </div>

        {/* Infrastructure Details */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '14px',
            marginBottom: '16px',
            paddingBottom: '16px',
            borderBottom: `1px solid #1f2937`,
          }}
        >
          <div>
            <p style={{ margin: '0 0 4px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase' }}>Cloud Provider</p>
            <p style={{ margin: 0, color: '#f3f4f6', fontSize: '13px' }}>{alert.cloud_provider}</p>
          </div>
          <div>
            <p style={{ margin: '0 0 4px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase' }}>Region</p>
            <p style={{ margin: 0, color: '#f3f4f6', fontSize: '13px' }}>{alert.region}</p>
          </div>
          <div>
            <p style={{ margin: '0 0 4px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase' }}>Target Team</p>
            <p style={{ margin: 0, color: '#f3f4f6', fontSize: '13px' }}>{alert.target_team}</p>
          </div>
          <div>
            <p style={{ margin: '0 0 4px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase' }}>Timestamp</p>
            <p style={{ margin: 0, color: '#f3f4f6', fontSize: '12px' }}>{formatDate(alert.batch_ts)}</p>
          </div>
        </div>

        {/* Component Breakdown */}
        <div style={{ marginBottom: '12px' }}>
          <p style={{ margin: '0 0 8px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase', fontWeight: 'bold' }}>
            Detection Scores
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
            <div style={{ padding: '8px', borderRadius: '6px', background: '#0f172a', border: '1px solid #1f2937' }}>
              <p style={{ margin: '0 0 2px 0', color: '#9ca3af', fontSize: '11px' }}>Deviation</p>
              <p style={{ margin: 0, color: '#60a5fa', fontWeight: 'bold' }}>
                {(alert.deviation_score * 100).toFixed(1)}%
              </p>
            </div>
            <div style={{ padding: '8px', borderRadius: '6px', background: '#0f172a', border: '1px solid #1f2937' }}>
              <p style={{ margin: '0 0 2px 0', color: '#9ca3af', fontSize: '11px' }}>Drift</p>
              <p style={{ margin: 0, color: '#60a5fa', fontWeight: 'bold' }}>
                {(alert.drift_score * 100).toFixed(1)}%
              </p>
            </div>
            <div style={{ padding: '8px', borderRadius: '6px', background: '#0f172a', border: '1px solid #1f2937' }}>
              <p style={{ margin: '0 0 2px 0', color: '#9ca3af', fontSize: '11px' }}>Similarity</p>
              <p style={{ margin: 0, color: '#60a5fa', fontWeight: 'bold' }}>
                {(alert.similarity_score * 100).toFixed(1)}%
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Notification Status Card */}
      {notification && (
        <div
          style={{
            padding: '14px',
            borderRadius: '12px',
            background: '#0f172a',
            border: '1px solid #1f2937',
          }}
        >
          <p style={{ margin: '0 0 8px 0', color: '#9ca3af', fontSize: '12px', textTransform: 'uppercase', fontWeight: 'bold' }}>
            📧 Notification Status
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '50%',
                background: notificationColor,
              }}
            />
            <span style={{ color: '#f3f4f6', fontSize: '13px' }}>
              {notification.message}
              {notification.email_to && ` to ${notification.email_to}`}
            </span>
          </div>
        </div>
      )}

      {/* Explainability Section */}
      {explainability && explainability.explainability && (
        <div
          style={{
            padding: '18px',
            borderRadius: '12px',
            background: '#071025',
            border: '2px solid #1e40af',
          }}
        >
          <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#60a5fa' }}>🤖 Model Explainability Analysis</h3>

          {/* Model Information */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: '12px',
              marginBottom: '16px',
              paddingBottom: '12px',
              borderBottom: '1px solid #1e3a8a',
            }}
          >
            <div>
              <p style={{ margin: '0 0 4px 0', color: '#93c5fd', fontSize: '11px', textTransform: 'uppercase' }}>Model Version</p>
              <p style={{ margin: 0, color: '#dbeafe', fontSize: '12px', fontWeight: '500' }}>
                {explainability.explainability.model_version}
              </p>
            </div>
            <div>
              <p style={{ margin: '0 0 4px 0', color: '#93c5fd', fontSize: '11px', textTransform: 'uppercase' }}>Prediction Confidence</p>
              <p style={{ margin: 0, color: '#dbeafe', fontSize: '12px', fontWeight: '500' }}>
                {explainability.explainability.prediction_confidence.toFixed(1)}%
              </p>
            </div>
            <div>
              <p style={{ margin: '0 0 4px 0', color: '#93c5fd', fontSize: '11px', textTransform: 'uppercase' }}>Temporal Window</p>
              <p style={{ margin: 0, color: '#dbeafe', fontSize: '12px', fontWeight: '500' }}>
                {explainability.explainability.model_components.lstm_temporal_window}
              </p>
            </div>
          </div>

          {/* Key Factors */}
          <div style={{ marginBottom: '16px' }}>
            <p style={{ margin: '0 0 8px 0', color: '#60a5fa', fontSize: '12px', textTransform: 'uppercase', fontWeight: 'bold' }}>
              Contributing Factors
            </p>
            <div style={{ display: 'grid', gap: '8px' }}>
              {explainability.explainability.key_factors.map((factor, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '10px',
                    borderRadius: '8px',
                    background: '#0f172a',
                    border: '1px solid #1e3a8a',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '4px' }}>
                    <span style={{ color: '#dbeafe', fontWeight: '500', fontSize: '12px' }}>{factor.factor}</span>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        background: factor.impact === 'HIGH' ? '#991b1b' : '#404040',
                        color: factor.impact === 'HIGH' ? '#fca5a5' : '#d1d5db',
                        fontSize: '10px',
                        fontWeight: 'bold',
                      }}
                    >
                      {factor.impact}
                    </span>
                  </div>
                  <p style={{ margin: '4px 0 0 0', color: '#93c5fd', fontSize: '11px' }}>
                    Contribution: {(factor.contribution * 100).toFixed(1)}%
                  </p>
                  <p style={{ margin: '2px 0 0 0', color: '#cbd5e1', fontSize: '11px' }}>{factor.description}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Recommendations */}
          <div>
            <p style={{ margin: '0 0 8px 0', color: '#60a5fa', fontSize: '12px', textTransform: 'uppercase', fontWeight: 'bold' }}>
              ⚠️ Recommended Actions
            </p>
            <div style={{ display: 'grid', gap: '6px' }}>
              {explainability.explainability.recommendations.map((rec, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '8px',
                    borderRadius: '6px',
                    background: '#0f172a',
                    border: '1px solid #1e3a8a',
                    borderLeft: `3px solid #60a5fa`,
                  }}
                >
                  <p style={{ margin: 0, color: '#dbeafe', fontSize: '12px' }}>{rec}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import type { DemoNotification } from '../services/demoApi';
import type { AlertPayload } from '../types/contracts';
import { Card, SeverityBadge, Toast } from './ui';

interface AlertResponseCardProps {
  alert: AlertPayload;
  notification?: DemoNotification;
}

const formatDate = (dateString: string): string => {
  const parsed = new Date(dateString);
  return Number.isNaN(parsed.getTime()) ? dateString : parsed.toLocaleString();
};

export default function AlertResponseCard({ alert, notification }: AlertResponseCardProps) {
  return (
    <Card className="alert-response-card">
      <div className="alert-response-header">
        <div>
          <p className="ui-eyebrow">Detection result</p>
          <h3>Security alert</h3>
        </div>
        <SeverityBadge severity={alert.severity} />
      </div>
      <dl className="alert-response-grid">
        <div><dt>Alert ID</dt><dd className="alert-monospace">{alert.alert_id}</dd></div>
        <div><dt>Entity</dt><dd>{alert.entity_id}</dd></div>
        <div><dt>Risk score</dt><dd>{(alert.final_score * 100).toFixed(1)}%</dd></div>
        <div><dt>Classification</dt><dd>{alert.sev_level}</dd></div>
        <div><dt>Cloud provider</dt><dd>{alert.cloud_provider}</dd></div>
        <div><dt>Region</dt><dd>{alert.region}</dd></div>
        <div><dt>Target team</dt><dd>{alert.target_team}</dd></div>
        <div><dt>Timestamp</dt><dd>{formatDate(alert.batch_ts)}</dd></div>
      </dl>
      <div className="alert-component-scores">
        <p className="ui-eyebrow">Detection scores</p>
        <div>
          <span>Deviation <strong>{(alert.deviation_score * 100).toFixed(1)}%</strong></span>
          <span>Drift <strong>{(alert.drift_score * 100).toFixed(1)}%</strong></span>
          <span>Similarity <strong>{(alert.similarity_score * 100).toFixed(1)}%</strong></span>
        </div>
      </div>
      {notification ? (
        <Toast
          tone={notification.status === 'failed' ? 'error' : notification.status === 'sent' ? 'success' : 'info'}
          message={`${notification.notify_method}: ${notification.message}${notification.email_to ? ` to ${notification.email_to}` : ''}`}
        />
      ) : null}
    </Card>
  );
}

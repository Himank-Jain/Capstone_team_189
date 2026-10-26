import { useEffect, useState } from 'react';
import { getErrorMessage } from '../services/errors';
import {
  getNotificationChannels,
  sendTestNotification,
  TESTABLE_CHANNELS,
  type NotificationChannel,
  type NotificationResult,
} from '../services/notificationsApi';
import { publishLocalAlert } from '../services/notificationBus';
import { Badge, Button, Card, Skeleton, Toast } from './ui';

const STATUS_LABEL: Record<string, string> = {
  ready: 'Ready',
  credentials_required: 'Not configured',
};

function statusClass(status: string) {
  return status === 'ready' ? 'ui-confidence-high' : 'ui-confidence-low';
}

function resultTone(result: NotificationResult): 'success' | 'error' | 'info' {
  if (result.sent) return 'success';
  return result.status === 'failed' ? 'error' : 'info';
}

export default function NotificationChannelsPanel({
  canSendTest,
  tenantId,
  refreshKey = 0,
  title = 'Notification channels',
  description = 'Where alerts for this workspace are delivered. Credentials stay on the server; only readiness is shown.',
}: {
  canSendTest: boolean;
  tenantId: string | null;
  /** Bump to reload channel readiness (e.g. after saving email settings). */
  refreshKey?: number;
  title?: string;
  description?: string;
}) {
  const [channels, setChannels] = useState<NotificationChannel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, NotificationResult>>({});

  useEffect(() => {
    let cancelled = false;
    setChannels(null);
    setError(null);
    getNotificationChannels()
      .then((data) => { if (!cancelled) setChannels(data); })
      .catch((err: unknown) => { if (!cancelled) setError(getErrorMessage(err, 'Unable to load notification channels')); });
    return () => {
      cancelled = true;
    };
  }, [tenantId, refreshKey]);

  const sendTest = async (channel: string) => {
    setSending(channel);
    try {
      const result = await sendTestNotification(channel);
      setResults((current) => ({ ...current, [channel]: result }));
      if (channel === 'PAGE' && result.sent && tenantId) {
        publishLocalAlert({
          type: 'alert',
          tenant_id: tenantId,
          payload: {
            alert_id: `test-${Date.now()}`,
            entity_id: 'notification-test',
            severity: 'LOW',
            final_score: 0,
            batch_ts: new Date().toISOString(),
          },
        });
      }
    } catch (err: unknown) {
      setResults((current) => ({
        ...current,
        [channel]: { channel, status: 'failed', sent: false, message: getErrorMessage(err, 'Test failed') },
      }));
    } finally {
      setSending(null);
    }
  };

  return (
    <Card className="notification-channels">
      <h2>{title}</h2>
      <p>{description}</p>
      {error ? <Toast message={error} tone="error" /> : null}
      {!channels && !error ? <Skeleton rows={4} /> : null}
      {channels ? (
        <ul className="notification-channel-list">
          {channels.map(({ channel, status, detail }) => {
            const result = results[channel];
            return (
              <li className="notification-channel" key={channel}>
                <div className="notification-channel-main">
                  <div>
                    <strong>{channel}</strong>
                    <div className="p3-footer">{detail}</div>
                  </div>
                  <div className="notification-channel-actions">
                    <Badge className={statusClass(status)}>{STATUS_LABEL[status] || status.replace(/_/g, ' ')}</Badge>
                    {canSendTest && TESTABLE_CHANNELS.has(channel) ? (
                      <Button type="button" onClick={() => void sendTest(channel)} disabled={sending !== null}>
                        {sending === channel ? 'Sending…' : 'Send test'}
                      </Button>
                    ) : null}
                  </div>
                </div>
                {result ? (
                  <Toast
                    tone={resultTone(result)}
                    message={`${result.status.replace(/_/g, ' ')}: ${result.message}`}
                    onDismiss={() => setResults((current) => {
                      const next = { ...current };
                      delete next[channel];
                      return next;
                    })}
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {!canSendTest ? <p className="p3-footer">Operators and owners can send test notifications.</p> : null}
    </Card>
  );
}

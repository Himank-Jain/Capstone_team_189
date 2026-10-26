import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import useAlertStream from '../hooks/useAlertStream';
import { getRecentAlerts } from '../services/alertsApi';
import { isMockMode } from '../services/apiClient';
import { LOCAL_ALERT_EVENT, type LocalAlertMessage } from '../services/notificationBus';
import { Button, SeverityBadge } from './ui';

const DESKTOP_PREF_KEY = 'capstone.desktopNotifications';
const MAX_ITEMS = 25;
const TOAST_MS = 6000;

export interface AlertNotification {
  id: string;
  tenantId: string;
  entityId: string;
  severity: string;
  score: number;
  receivedAt: string;
  read: boolean;
}

function readDesktopPreference(): boolean {
  try {
    return localStorage.getItem(DESKTOP_PREF_KEY) === 'on';
  } catch {
    return false;
  }
}

function writeDesktopPreference(on: boolean) {
  try {
    localStorage.setItem(DESKTOP_PREF_KEY, on ? 'on' : 'off');
  } catch {
    // per-viewer convenience only
  }
}

function desktopSupported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window;
}

function toNotification(message: unknown): AlertNotification | null {
  if (!message || typeof message !== 'object') return null;
  const { type, tenant_id: tenantId, payload } = message as Partial<LocalAlertMessage>;
  if (type !== 'alert' || !tenantId || !payload?.alert_id) return null;
  return {
    id: String(payload.alert_id),
    tenantId,
    entityId: String(payload.entity_id ?? 'unknown'),
    severity: String(payload.severity ?? 'LOW'),
    score: Number(payload.final_score ?? 0),
    receivedAt: new Date().toISOString(),
    read: false,
  };
}

export default function NotificationCenter({ tenantId }: { tenantId: string | null }) {
  const [items, setItems] = useState<AlertNotification[]>([]);
  const [toasts, setToasts] = useState<AlertNotification[]>([]);
  const [open, setOpen] = useState(false);
  const [desktopOn, setDesktopOn] = useState(readDesktopPreference);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const tenantRef = useRef(tenantId);
  const desktopRef = useRef(desktopOn);
  useEffect(() => {
    tenantRef.current = tenantId;
    desktopRef.current = desktopOn;
  }, [tenantId, desktopOn]);

  // Seed the list with the tenant's recent alerts so the bell is useful after a reload.
  useEffect(() => {
    if (!tenantId) return undefined;
    let cancelled = false;
    getRecentAlerts()
      .then((alerts) => {
        if (cancelled) return;
        const seeded = alerts.slice(0, MAX_ITEMS).map((alert) => ({
          id: alert.alert_id,
          tenantId,
          entityId: alert.entity_id,
          severity: alert.severity,
          score: alert.final_score,
          receivedAt: alert.batch_ts,
          read: true,
        }));
        setItems((current) => [
          ...current.filter((item) => item.tenantId === tenantId && !seeded.some((seed) => seed.id === item.id)),
          ...seeded,
        ].slice(0, MAX_ITEMS));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const receive = useCallback((message: unknown) => {
    const next = toNotification(message);
    if (!next || next.tenantId !== tenantRef.current) return;
    setItems((current) => [next, ...current.filter((item) => item.id !== next.id)].slice(0, MAX_ITEMS));
    setToasts((current) => [next, ...current.filter((item) => item.id !== next.id)].slice(0, 3));
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== next.id)), TOAST_MS);
    if (desktopRef.current && desktopSupported() && Notification.permission === 'granted' && document.hidden) {
      new Notification(`${next.severity} alert · ${next.entityId}`, {
        body: `Risk score ${(next.score * 100).toFixed(0)}% in ${next.tenantId}. Open the dashboard to investigate.`,
        tag: next.id,
      });
    }
  }, []);

  const { connectionState } = useAlertStream(receive, { enabled: !isMockMode() });

  useEffect(() => {
    const onLocal = (event: Event) => receive((event as CustomEvent<LocalAlertMessage>).detail);
    window.addEventListener(LOCAL_ALERT_EVENT, onLocal);
    return () => window.removeEventListener(LOCAL_ALERT_EVENT, onLocal);
  }, [receive]);

  useEffect(() => {
    if (!open) return undefined;
    const onClick = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  // Items are kept per tenant; only the active workspace's are shown.
  const visible = items.filter((item) => item.tenantId === tenantId);
  const unread = visible.filter((item) => !item.read).length;

  const toggleDesktop = async () => {
    if (!desktopSupported()) return;
    if (desktopOn) {
      setDesktopOn(false);
      writeDesktopPreference(false);
      return;
    }
    const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
    const enabled = permission === 'granted';
    setDesktopOn(enabled);
    writeDesktopPreference(enabled);
  };

  const markAllRead = () => setItems((current) => current.map((item) => ({ ...item, read: true })));

  const streamLabel = isMockMode()
    ? 'Mock mode: alerts from the live demo page'
    : connectionState === 'connected'
      ? 'Live stream connected'
      : connectionState === 'disconnected'
        ? 'Live stream offline'
        : 'Connecting to live stream…';

  return (
    <div className="notify-center" ref={panelRef}>
      <button
        type="button"
        className="notify-bell"
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
          <path
            fill="currentColor"
            d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z"
          />
        </svg>
        {unread ? <span className="notify-count">{unread > 9 ? '9+' : unread}</span> : null}
      </button>

      {open ? (
        <section className="notify-panel" role="dialog" aria-label="Notifications">
          <header className="notify-panel-header">
            <div>
              <h2>Notifications</h2>
              <p className="notify-stream">
                <span className={`notify-dot notify-dot-${isMockMode() ? 'mock' : connectionState}`} aria-hidden="true" />
                {streamLabel}
              </p>
            </div>
            <Button type="button" variant="ghost" onClick={markAllRead} disabled={!unread}>Mark all read</Button>
          </header>
          {visible.length ? (
            <ul className="notify-list">
              {visible.map((item) => (
                <li key={item.id} className={item.read ? 'notify-item' : 'notify-item notify-item-unread'}>
                  <Link
                    to={`/incidents/${encodeURIComponent(item.id)}`}
                    onClick={() => {
                      setItems((current) => current.map((entry) => (entry.id === item.id ? { ...entry, read: true } : entry)));
                      setOpen(false);
                    }}
                  >
                    <span className="notify-item-main">
                      <strong>{item.entityId}</strong>
                      <span>Risk {(item.score * 100).toFixed(0)}% · {new Date(item.receivedAt).toLocaleTimeString()}</span>
                    </span>
                    <SeverityBadge severity={item.severity} />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="notify-empty">No alerts for this workspace yet. New detections appear here as they happen.</p>
          )}
          <footer className="notify-panel-footer">
            {desktopSupported() ? (
              <label className="notify-toggle">
                <input type="checkbox" checked={desktopOn} onChange={() => void toggleDesktop()} />
                <span>Desktop notifications when this tab is in the background</span>
              </label>
            ) : <span>Desktop notifications are not supported in this browser.</span>}
            <Link to="/settings" onClick={() => setOpen(false)}>Channel settings</Link>
          </footer>
        </section>
      ) : null}

      <div className="notify-toasts" aria-live="polite">
        {toasts.map((toast) => (
          <Link className={`notify-toast notify-toast-${toast.severity.toLowerCase()}`} key={toast.id} to={`/incidents/${encodeURIComponent(toast.id)}`}>
            <span className="notify-toast-title">New {toast.severity} alert</span>
            <span>{toast.entityId} · risk {(toast.score * 100).toFixed(0)}%</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

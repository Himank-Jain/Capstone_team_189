import { useEffect, useState, type FormEvent } from 'react';
import { friendlyError } from '../services/authApi';
import {
  clearEmailSettings,
  getEmailSettings,
  saveEmailSettings,
  type EmailSettingsSummary,
  type SmtpSecurity,
} from '../services/notificationsApi';
import { Badge, Button, Card, FormField, Skeleton, Toast } from './ui';

type Preset = 'gmail' | 'outlook' | 'custom';

const PRESETS: Record<Exclude<Preset, 'custom'>, { host: string; port: number; security: SmtpSecurity; label: string }> = {
  gmail: { host: 'smtp.gmail.com', port: 587, security: 'starttls', label: 'Gmail' },
  outlook: { host: 'smtp.office365.com', port: 587, security: 'starttls', label: 'Outlook / Microsoft 365' },
};

function presetFor(host: string): Preset {
  if (host === PRESETS.gmail.host) return 'gmail';
  if (host === PRESETS.outlook.host) return 'outlook';
  return host ? 'custom' : 'gmail';
}

export default function EmailSettingsCard({
  canEdit,
  tenantId,
  onSaved,
}: {
  canEdit: boolean;
  tenantId: string | null;
  onSaved?: () => void;
}) {
  const [summary, setSummary] = useState<EmailSettingsSummary | null>(null);
  const [preset, setPreset] = useState<Preset>('gmail');
  const [host, setHost] = useState(PRESETS.gmail.host);
  const [port, setPort] = useState(587);
  const [security, setSecurity] = useState<SmtpSecurity>('starttls');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [recipients, setRecipients] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = (data: EmailSettingsSummary) => {
    setSummary(data);
    if (data.source === 'workspace') {
      setPreset(presetFor(data.host));
      setHost(data.host);
      setPort(data.port);
      setSecurity(data.security);
      setUsername(data.username);
      setRecipients(data.recipients.join(', '));
    }
    setPassword('');
  };

  useEffect(() => {
    let cancelled = false;
    getEmailSettings()
      .then((data) => { if (!cancelled) apply(data); })
      .catch((err: unknown) => { if (!cancelled) setError(friendlyError(err, 'Unable to load email settings')); });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const choosePreset = (next: Preset) => {
    setPreset(next);
    if (next !== 'custom') {
      setHost(PRESETS[next].host);
      setPort(PRESETS[next].port);
      setSecurity(PRESETS[next].security);
    }
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      apply(await saveEmailSettings({
        host: host.trim(),
        port,
        security,
        username: username.trim(),
        password: password || undefined,
        recipients: recipients.split(/[,\s]+/).map((item) => item.trim()).filter(Boolean),
      }));
      setNotice('Email settings saved. Use "Send test" on the EMAIL channel to check delivery.');
      onSaved?.();
    } catch (err: unknown) {
      setError(friendlyError(err, 'Unable to save email settings'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      apply(await clearEmailSettings());
      setNotice('Workspace email settings removed; the server environment settings (if any) apply again.');
      onSaved?.();
    } catch (err: unknown) {
      setError(friendlyError(err, 'Unable to remove email settings'));
    } finally {
      setBusy(false);
    }
  };

  const sourceLabel = summary?.source === 'workspace'
    ? 'Saved for this workspace'
    : summary?.source === 'environment'
      ? 'From the server environment (.env)'
      : 'Not set up';

  return (
    <Card className="email-settings">
      <div className="email-settings-header">
        <div>
          <p className="ui-eyebrow">Email delivery</p>
          <h2>Alert email account</h2>
        </div>
        {summary ? <Badge className={summary.ready ? 'ui-confidence-high' : 'ui-confidence-low'}>{summary.ready ? 'Ready' : 'Not configured'}</Badge> : null}
      </div>
      {!summary && !error ? <Skeleton rows={3} /> : null}
      {summary ? (
        <>
          <p className="p3-footer">
            {sourceLabel}
            {summary.ready ? ` · sends as ${summary.sender} via ${summary.host}:${summary.port}` : ''}
            {summary.effective_recipients.length ? ` · alerts go to ${summary.effective_recipients.join(', ')}` : ''}
          </p>
          {summary.problem ? <p className="email-settings-problem">{summary.problem}</p> : null}
        </>
      ) : null}
      {error ? <Toast message={error} tone="error" onDismiss={() => setError(null)} /> : null}
      {notice ? <Toast message={notice} tone="success" onDismiss={() => setNotice(null)} /> : null}

      {canEdit ? (
        <form className="email-settings-form" onSubmit={save}>
          <FormField label="Provider">
            <select value={preset} onChange={(event) => choosePreset(event.target.value as Preset)}>
              <option value="gmail">{PRESETS.gmail.label}</option>
              <option value="outlook">{PRESETS.outlook.label}</option>
              <option value="custom">Other SMTP server</option>
            </select>
          </FormField>
          {preset === 'custom' ? (
            <div className="email-settings-row">
              <FormField label="SMTP host">
                <input value={host} onChange={(event) => setHost(event.target.value)} required />
              </FormField>
              <FormField label="Port">
                <input type="number" min={1} max={65535} value={port} onChange={(event) => setPort(Number(event.target.value))} required />
              </FormField>
              <FormField label="Security">
                <select value={security} onChange={(event) => setSecurity(event.target.value as SmtpSecurity)}>
                  <option value="starttls">STARTTLS (587)</option>
                  <option value="ssl">SSL/TLS (465)</option>
                  <option value="none">None (local testing only)</option>
                </select>
              </FormField>
            </div>
          ) : null}
          <div className="email-settings-row">
            <FormField label="Sender email (SMTP login)">
              <input type="email" autoComplete="off" value={username} onChange={(event) => setUsername(event.target.value)} required />
            </FormField>
            <FormField
              label={preset === 'gmail' ? 'Gmail app password' : 'SMTP password'}
              hint={summary?.password_set ? 'Leave blank to keep the saved password.' : undefined}
            >
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={summary?.password_set ? '••••••••' : ''}
              />
            </FormField>
          </div>
          <FormField label="Send alerts to" hint="Optional. Comma-separated. Leave empty to email every member of this workspace.">
            <input value={recipients} onChange={(event) => setRecipients(event.target.value)} />
          </FormField>
          {preset === 'gmail' ? (
            <p className="p3-footer">
              Gmail needs an app password, not your normal password: turn on 2-Step Verification, then create one at{' '}
              <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">myaccount.google.com/apppasswords</a>.
            </p>
          ) : null}
          <div className="email-settings-actions">
            <Button variant="primary" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save email settings'}</Button>
            {summary?.source === 'workspace' ? <Button type="button" variant="ghost" disabled={busy} onClick={() => void remove()}>Remove</Button> : null}
          </div>
        </form>
      ) : (
        <p className="p3-footer">Only workspace owners can change the email account.</p>
      )}
    </Card>
  );
}

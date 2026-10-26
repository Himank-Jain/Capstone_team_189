import { fetchJson, getApiBase, isMockMode } from './apiClient';

export type ChannelStatus = 'ready' | 'credentials_required' | string;

export interface NotificationChannel {
  channel: string;
  status: ChannelStatus;
  detail: string;
}

export interface NotificationResult {
  channel: string;
  notify_method?: string;
  status: 'sent' | 'displayed' | 'failed' | 'not_configured' | string;
  sent: boolean;
  message: string;
  email_to?: string;
}

/** Channels the API can send a test through (SMS has no provider wired in). */
export const TESTABLE_CHANNELS = new Set(['PAGE', 'EMAIL', 'SLACK', 'WEBHOOK', 'PAGERDUTY']);

const MOCK_CHANNELS: NotificationChannel[] = [
  { channel: 'PAGE', status: 'ready', detail: 'In-dashboard notifications for signed-in members' },
  { channel: 'EMAIL', status: 'credentials_required', detail: 'Mock mode: no email is sent' },
  { channel: 'SLACK', status: 'credentials_required', detail: 'Mock mode: no Slack message is sent' },
  { channel: 'SMS', status: 'credentials_required', detail: 'No SMS provider is wired into this build' },
  { channel: 'WEBHOOK', status: 'credentials_required', detail: 'Mock mode: no webhook is called' },
  { channel: 'PAGERDUTY', status: 'credentials_required', detail: 'Mock mode: no PagerDuty event is sent' },
];

export async function getNotificationChannels(): Promise<NotificationChannel[]> {
  if (isMockMode()) return MOCK_CHANNELS;
  return fetchJson<NotificationChannel[]>(`${getApiBase()}/notifications/channels`);
}

export async function sendTestNotification(channel: string): Promise<NotificationResult> {
  if (isMockMode()) {
    return channel === 'PAGE'
      ? { channel, status: 'displayed', sent: true, message: 'Mock dashboard notification shown' }
      : { channel, status: 'not_configured', sent: false, message: 'Mock mode does not send external notifications' };
  }
  return fetchJson<NotificationResult>(`${getApiBase()}/notifications/test`, {
    method: 'POST',
    body: JSON.stringify({ channel }),
  });
}

export type SmtpSecurity = 'starttls' | 'ssl' | 'none';

export interface EmailSettingsSummary {
  source: 'workspace' | 'environment' | 'none';
  host: string;
  port: number;
  security: SmtpSecurity;
  username: string;
  sender: string;
  password_set: boolean;
  recipients: string[];
  effective_recipients: string[];
  ready: boolean;
  problem: string | null;
  updated_at?: string | null;
}

export interface EmailSettingsInput {
  host: string;
  port: number;
  security: SmtpSecurity;
  username: string;
  password?: string;
  sender?: string;
  recipients: string[];
}

const MOCK_EMAIL: EmailSettingsSummary = {
  source: 'none', host: 'smtp.gmail.com', port: 587, security: 'starttls', username: '', sender: '',
  password_set: false, recipients: [], effective_recipients: [], ready: false,
  problem: 'Mock mode: email settings are not saved and no email is sent',
};

export async function getEmailSettings(): Promise<EmailSettingsSummary> {
  if (isMockMode()) return MOCK_EMAIL;
  return fetchJson<EmailSettingsSummary>(`${getApiBase()}/notifications/email-settings`);
}

export async function saveEmailSettings(input: EmailSettingsInput): Promise<EmailSettingsSummary> {
  if (isMockMode()) throw new Error('Mock mode cannot save email settings; run the API to send real email');
  return fetchJson<EmailSettingsSummary>(`${getApiBase()}/notifications/email-settings`, {
    method: 'PUT',
    body: JSON.stringify(input),
  });
}

export async function clearEmailSettings(): Promise<EmailSettingsSummary> {
  if (isMockMode()) return MOCK_EMAIL;
  return fetchJson<EmailSettingsSummary>(`${getApiBase()}/notifications/email-settings`, { method: 'DELETE' });
}

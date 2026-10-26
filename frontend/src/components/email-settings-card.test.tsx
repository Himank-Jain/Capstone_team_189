import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import EmailSettingsCard from './EmailSettingsCard';

const api = vi.hoisted(() => ({ getEmailSettings: vi.fn(), saveEmailSettings: vi.fn(), clearEmailSettings: vi.fn() }));
vi.mock('../services/notificationsApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/notificationsApi')>()),
  ...api,
}));

const empty = {
  source: 'none', host: 'smtp.gmail.com', port: 587, security: 'starttls', username: '', sender: '',
  password_set: false, recipients: [], effective_recipients: ['owner@example.com'], ready: false,
  problem: 'Email is not set up', updated_at: null,
};

describe('EmailSettingsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getEmailSettings.mockResolvedValue(empty);
  });

  it('saves Gmail settings and never shows the password again', async () => {
    const onSaved = vi.fn();
    api.saveEmailSettings.mockResolvedValue({
      ...empty, source: 'workspace', username: 'me@gmail.com', sender: 'me@gmail.com', password_set: true, ready: true, problem: null,
    });
    render(<EmailSettingsCard canEdit tenantId="google" onSaved={onSaved} />);

    await screen.findByText('Email is not set up');
    fireEvent.change(screen.getByLabelText(/^Sender email/), { target: { value: 'me@gmail.com' } });
    fireEvent.change(screen.getByLabelText(/^Gmail app password/), { target: { value: 'abcd efgh ijkl mnop' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save email settings' }));

    await waitFor(() => expect(api.saveEmailSettings).toHaveBeenCalledWith({
      host: 'smtp.gmail.com', port: 587, security: 'starttls', username: 'me@gmail.com',
      password: 'abcd efgh ijkl mnop', recipients: [],
    }));
    expect(onSaved).toHaveBeenCalled();
    expect(await screen.findByText(/Email settings saved/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Gmail app password/)).toHaveValue('');
    expect(screen.getByText(/Leave blank to keep the saved password/)).toBeInTheDocument();
  });

  it('is read-only for non-owners', async () => {
    render(<EmailSettingsCard canEdit={false} tenantId="google" />);
    expect(await screen.findByText(/Only workspace owners/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save email settings' })).toBeNull();
  });
});

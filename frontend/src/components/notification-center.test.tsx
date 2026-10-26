import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import NotificationCenter from './NotificationCenter';
import { publishLocalAlert } from '../services/notificationBus';

vi.mock('../services/alertsApi', () => ({
  getRecentAlerts: vi.fn().mockResolvedValue([
    { alert_id: 'older-1', entity_id: 'vol-g00g', severity: 'LOW', final_score: 0.2, batch_ts: '2026-10-26T10:00:00Z' },
  ]),
}));

vi.mock('../hooks/useAlertStream', () => ({
  default: () => ({ connected: true, connectionState: 'connected', error: null }),
}));

function alert(tenantId: string, id: string) {
  publishLocalAlert({
    type: 'alert',
    tenant_id: tenantId,
    payload: { alert_id: id, entity_id: `entity-${id}`, severity: 'CRITICAL', final_score: 0.91, batch_ts: '2026-10-26T12:00:00Z' },
  });
}

describe('NotificationCenter', () => {
  beforeEach(() => localStorage.clear());

  it('shows a toast and unread count for the active workspace only', async () => {
    render(<MemoryRouter><NotificationCenter tenantId="google" /></MemoryRouter>);
    await screen.findByRole('button', { name: 'Notifications' });

    act(() => alert('amazon', 'other-tenant'));
    expect(screen.queryByText(/entity-other-tenant/)).toBeNull();

    act(() => alert('google', 'a1'));
    expect(screen.getByText('New CRITICAL alert')).toBeInTheDocument();
    const bell = screen.getByRole('button', { name: 'Notifications, 1 unread' });

    fireEvent.click(bell);
    const dialog = screen.getByRole('dialog', { name: 'Notifications' });
    expect(dialog).toHaveTextContent('entity-a1');
    expect(dialog).toHaveTextContent('vol-g00g');
    expect(screen.getAllByRole('link', { name: /entity-a1/ })[0]).toHaveAttribute('href', '/incidents/a1');

    fireEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument();
  });
});

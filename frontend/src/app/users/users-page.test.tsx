import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthContext, type AuthContextValue } from '../../auth/authContext';
import type { Role } from '../../services/authApi';
import UsersPage from './page';

const authApi = vi.hoisted(() => ({
  listMembers: vi.fn(),
  addMember: vi.fn(),
  updateMemberRole: vi.fn(),
  removeMember: vi.fn(),
}));

vi.mock('../../services/authApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/authApi')>()),
  ...authApi,
}));

const members = [
  { user_id: 'user-1', email: 'owner@example.com', role: 'OWNER' as Role, joined_at: '2026-10-26T10:00:00Z' },
  { user_id: 'user-2', email: 'teammate@example.com', role: 'VIEWER' as Role, joined_at: '2026-10-26T11:00:00Z' },
];

function renderAs(role: Role) {
  const value: AuthContextValue = {
    status: 'authenticated',
    session: { user: { user_id: role === 'OWNER' ? 'user-1' : 'user-2', email: 'x@example.com', role }, memberships: [] },
    activeTenantId: 'google',
    activeMembership: { tenant_id: 'google', tenant_name: 'Google', role },
    role,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
    switchTenant: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
  };
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={value}><UsersPage /></AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('UsersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authApi.listMembers.mockResolvedValue(members);
  });

  it('lets an owner change roles and add members', async () => {
    authApi.updateMemberRole.mockResolvedValue({ ...members[1], role: 'OPERATOR' });
    authApi.addMember.mockResolvedValue({ user_id: 'user-3', email: 'new@example.com', role: 'OPERATOR' });
    renderAs('OWNER');

    const roleSelect = await screen.findByLabelText('Role for teammate@example.com');
    fireEvent.change(roleSelect, { target: { value: 'OPERATOR' } });
    await waitFor(() => expect(authApi.updateMemberRole).toHaveBeenCalledWith('user-2', 'OPERATOR'));
    expect(await screen.findByText('teammate@example.com is now operator')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'new@example.com' } });
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'OPERATOR' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add member' }));
    await waitFor(() => expect(authApi.addMember).toHaveBeenCalledWith('new@example.com', 'OPERATOR'));
  });

  it('surfaces the last-owner guard from the API', async () => {
    authApi.removeMember.mockRejectedValue(new Error('HTTP 409: A workspace needs at least one owner'));
    renderAs('OWNER');

    fireEvent.click((await screen.findAllByRole('button', { name: 'Remove' }))[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Remove member' }));
    expect(await screen.findByText('A workspace needs at least one owner')).toBeInTheDocument();
  });

  it('is read-only for viewers', async () => {
    renderAs('VIEWER');
    expect(await screen.findByText('teammate@example.com')).toBeInTheDocument();
    expect(screen.queryByLabelText('Role for teammate@example.com')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add member' })).toBeNull();
    expect(screen.getByText(/Only owners can add members/)).toBeInTheDocument();
  });
});

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthContext, type AuthContextValue } from '../../auth/authContext';
import AdminPage from './page';

const authApi = vi.hoisted(() => ({ listAccounts: vi.fn(), setAccountAccess: vi.fn() }));
vi.mock('../../services/authApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/authApi')>()),
  ...authApi,
}));

const workspaces = ['google', 'amazon'].map((id) => ({ tenant_id: id, tenant_name: id, role: 'OWNER' as const }));

function renderAs(isAdmin: boolean) {
  const value: AuthContextValue = {
    status: 'authenticated',
    session: { user: { user_id: 'admin-1', email: 'admin@example.com', role: 'OWNER', is_admin: isAdmin }, memberships: workspaces },
    activeTenantId: 'google',
    activeMembership: workspaces[0],
    role: 'OWNER',
    signIn: vi.fn(), signUp: vi.fn(), signOut: vi.fn(), switchTenant: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
  };
  return render(<MemoryRouter><AuthContext.Provider value={value}><AdminPage /></AuthContext.Provider></MemoryRouter>);
}

describe('AdminPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authApi.listAccounts.mockResolvedValue([
      { user_id: 'admin-1', email: 'admin@example.com', is_admin: true, memberships: workspaces },
      {
        user_id: 'u-2', email: 'swathi@example.com', is_admin: false,
        memberships: workspaces.map((item) => ({ ...item, role: 'VIEWER' as const })),
      },
    ]);
  });

  it('lets an admin promote another account everywhere', async () => {
    authApi.setAccountAccess.mockResolvedValue({ user_id: 'u-2', email: 'swathi@example.com', is_admin: true, memberships: workspaces });
    renderAs(true);

    const select = await screen.findByLabelText('Access for swathi@example.com');
    expect(select).toHaveValue('VIEWER');
    fireEvent.change(select, { target: { value: 'OWNER' } });
    await waitFor(() => expect(authApi.setAccountAccess).toHaveBeenCalledWith('u-2', 'OWNER'));
    expect(await screen.findByLabelText('Access for swathi@example.com')).toHaveValue('OWNER');
  });

  it('blocks non-admins without calling the API', () => {
    renderAs(false);
    expect(screen.getByText('Administrator access required')).toBeInTheDocument();
    expect(authApi.listAccounts).not.toHaveBeenCalled();
  });
});

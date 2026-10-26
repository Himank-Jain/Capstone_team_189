import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AuthProvider from '../../auth/AuthProvider';
import LoginPage from './page';

const authApi = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
  fetchCurrentSession: vi.fn(),
}));

vi.mock('../../services/authApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../services/authApi')>()),
  ...authApi,
}));

const session = {
  access_token: 'token-123',
  user: { user_id: 'user-1', email: 'lav@example.com', role: 'OWNER' as const },
  memberships: [{ tenant_id: 'amazon', tenant_name: 'Amazon', role: 'OWNER' as const }],
};

function renderLogin(path = '/login') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<h1>Workspace home</h1>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

function fill(label: string, value: string) {
  // FormField puts its hint inside the <label>, so match on the label's start.
  fireEvent.change(screen.getByLabelText(new RegExp(`^${label}`)), { target: { value } });
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('signs in, stores the token, and opens the workspace', async () => {
    authApi.login.mockResolvedValue(session);
    renderLogin();

    fill('Email', 'lav@example.com');
    fill('Password', 'correct-password');
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { name: 'Workspace home' })).toBeInTheDocument();
    expect(authApi.login).toHaveBeenCalledWith('lav@example.com', 'correct-password');
    expect(localStorage.getItem('capstone.accessToken')).toBe('token-123');
    expect(localStorage.getItem('capstone.userId')).toBe('user-1');
    expect(localStorage.getItem('capstone.activeTenantId')).toBe('amazon');
    expect(localStorage.getItem('capstone.role')).toBe('OWNER');
  });

  it('shows the server message when credentials are wrong', async () => {
    authApi.login.mockRejectedValue(new Error('HTTP 401: Invalid email or password'));
    renderLogin();

    fill('Email', 'lav@example.com');
    fill('Password', 'nope-nope');
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByText('Invalid email or password')).toBeInTheDocument();
    expect(localStorage.getItem('capstone.accessToken')).toBeNull();
  });

  it('validates registration locally before calling the API', async () => {
    renderLogin();
    fireEvent.click(screen.getByRole('tab', { name: 'Create account' }));

    fill('Email', 'new@example.com');
    fill('Password', 'short');
    fill('Confirm password', 'short');
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText(/at least 8 characters/)).toBeInTheDocument();

    fill('Password', 'long-enough-1');
    fill('Confirm password', 'long-enough-2');
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText('Passwords do not match')).toBeInTheDocument();
    expect(authApi.register).not.toHaveBeenCalled();
  });

  it('registers a new account and signs straight in', async () => {
    authApi.register.mockResolvedValue({ ...session, user: { ...session.user, email: 'new@example.com' } });
    renderLogin('/login?mode=register');

    fill('Email', 'new@example.com');
    fill('Password', 'long-enough-1');
    fill('Confirm password', 'long-enough-1');
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }));

    await waitFor(() => expect(authApi.register).toHaveBeenCalledWith('new@example.com', 'long-enough-1'));
    expect(await screen.findByRole('heading', { name: 'Workspace home' })).toBeInTheDocument();
  });

  it('explains an expired session', () => {
    renderLogin('/login?expired=1');
    expect(screen.getByText(/Your session ended/)).toBeInTheDocument();
  });
});

import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../../auth/authContext';
import { isMockMode } from '../../services/apiClient';
import { friendlyError, MIN_PASSWORD_LENGTH } from '../../services/authApi';
import { Button, Card, FormField, PageHeader, Toast } from '../../components/ui';

type Mode = 'signin' | 'register';

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { status, signIn, signUp } = useAuth();
  const [mode, setMode] = useState<Mode>(searchParams.get('mode') === 'register' ? 'register' : 'signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const expired = searchParams.get('expired') === '1';
  const redirectTo = (location.state as { from?: string } | null)?.from || '/';

  if (status === 'authenticated') return <Navigate to={redirectTo} replace />;

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setPassword('');
    setConfirmPassword('');
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError('Enter both email and password');
      return;
    }
    if (mode === 'register') {
      if (password.length < MIN_PASSWORD_LENGTH) {
        setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`);
        return;
      }
      if (password !== confirmPassword) {
        setError('Passwords do not match');
        return;
      }
    }
    setError(null);
    setSubmitting(true);
    try {
      if (mode === 'register') await signUp(email.trim(), password);
      else await signIn(email.trim(), password);
      navigate(redirectTo, { replace: true });
    } catch (err: unknown) {
      setError(friendlyError(err, mode === 'register' ? 'Unable to create the account' : 'Unable to sign in'));
    } finally {
      setSubmitting(false);
    }
  };

  const isRegister = mode === 'register';

  return (
    <main className="login-page">
      <Card className="login-card">
        <p className="ui-eyebrow">Cloud behavior platform</p>
        <PageHeader
          title="CAPSTONE-189"
          description="Behavioral anomaly detection for multi-cloud operations."
        />
        <div className="ui-tabs login-tabs" role="tablist" aria-label="Account access">
          <button type="button" role="tab" className="ui-tab" aria-selected={!isRegister} onClick={() => switchMode('signin')}>
            Sign in
          </button>
          <button type="button" role="tab" className="ui-tab" aria-selected={isRegister} onClick={() => switchMode('register')}>
            Create account
          </button>
        </div>
        {expired && !isRegister ? <Toast message="Your session ended. Sign in again to continue." /> : null}
        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <FormField label="Email">
            <input
              type="email"
              autoComplete={isRegister ? 'email' : 'username'}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </FormField>
          <FormField label="Password" hint={isRegister ? `At least ${MIN_PASSWORD_LENGTH} characters.` : undefined}>
            <input
              type="password"
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </FormField>
          {isRegister ? (
            <FormField label="Confirm password">
              <input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
              />
            </FormField>
          ) : null}
          {error ? <Toast message={error} tone="error" /> : null}
          <Button variant="primary" type="submit" disabled={submitting}>
            {submitting ? (isRegister ? 'Creating account…' : 'Signing in…') : isRegister ? 'Create account' : 'Sign in'}
          </Button>
        </form>
        <p className="login-footnote">
          {isRegister
            ? 'The first account becomes the owner of the demo workspaces. Later accounts join as viewers until an owner changes their role.'
            : 'Admins and members sign in here. Admin access comes from the account (the first account registered, or the one configured on the server). New here? Create an account.'}
          {isMockMode() ? ' Mock mode: accounts are stored only in this browser.' : ''}
        </p>
      </Card>
    </main>
  );
}

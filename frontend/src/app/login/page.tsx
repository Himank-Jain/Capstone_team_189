import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getApiBase, isMockMode } from '../../services/apiClient';
import { Button, Card, FormField, PageHeader, Toast } from '../../components/ui';

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email || !password) {
      setError('Enter both email and password');
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      if (isMockMode()) {
        localStorage.setItem('capstone.userId', 'mock-operator');
        localStorage.setItem('capstone.activeTenantId', 'google');
        localStorage.setItem('capstone.role', 'OPERATOR');
        navigate('/');
        return;
      }
      const response = await fetch(`${getApiBase()}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        throw new Error(`Login failed with HTTP ${response.status}`);
      }
      const result = await response.json();
      localStorage.setItem('capstone.accessToken', result.access_token);
      localStorage.setItem('capstone.refreshToken', result.refresh_token);
      localStorage.setItem('capstone.userId', result.user.user_id);
      if (result.user.role) localStorage.setItem('capstone.role', result.user.role.toUpperCase());
      navigate('/');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unable to start the demo session');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <Card className="login-card">
        <p className="ui-eyebrow">Cloud behavior platform</p>
        <PageHeader title="CAPSTONE-189" description="Behavioral anomaly detection for multi-cloud operations. This local demo login is not production authentication." />
        <form className="login-form" onSubmit={handleSubmit}>
          <FormField label="Email">
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </FormField>
          <FormField label="Password">
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </FormField>
          {error ? <Toast message={error} tone="error" /> : null}
          <Button variant="primary" type="submit" disabled={submitting}>
            {submitting ? 'Starting demo…' : 'Continue'}
          </Button>
        </form>
      </Card>
    </main>
  );
}

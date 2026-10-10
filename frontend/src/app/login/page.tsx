import { useState } from 'react';

const DEMO_AUTH = {
  access_token: 'demo-access-token',
  refresh_token: 'demo-refresh-token',
};

function setAuthTokens(tokens: typeof DEMO_AUTH) {
  localStorage.setItem('capstone.accessToken', tokens.access_token);
  localStorage.setItem('capstone.refreshToken', tokens.refresh_token);
}

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email || !password) {
      setError('Enter both email and password');
      return;
    }
    setError(null);
    setAuthTokens(DEMO_AUTH);
    window.location.href = '/select-org';
  };

  return (
    <main style={{ minHeight: '100vh', background: '#0b0f17', color: '#f8fafc', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
      <div style={{ width: '100%', maxWidth: '420px', background: '#111827', border: '1px solid #1f2937', borderRadius: '24px', padding: '32px' }}>
        <h1 style={{ margin: 0, marginBottom: '16px', fontSize: '28px' }}>CAPSTONE-189</h1>
        <p style={{ color: '#94a3b8', marginBottom: '24px' }}>Behavioral anomaly detection SOC dashboard demo.</p>
        <form onSubmit={handleSubmit} style={{ display: 'grid', gap: '16px' }}>
          <label style={{ display: 'grid', gap: '8px', color: '#cbd5e1' }}>
            Email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              style={{ padding: '12px', borderRadius: '12px', border: '1px solid #334155', background: '#0f172a', color: '#f8fafc' }}
            />
          </label>
          <label style={{ display: 'grid', gap: '8px', color: '#cbd5e1' }}>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              style={{ padding: '12px', borderRadius: '12px', border: '1px solid #334155', background: '#0f172a', color: '#f8fafc' }}
            />
          </label>
          {error ? <p style={{ color: '#fca5a5', margin: 0 }}>{error}</p> : null}
          <button type="submit" style={{ padding: '14px 18px', borderRadius: '14px', border: 'none', background: '#2563eb', color: 'white', cursor: 'pointer' }}>
            Continue
          </button>
        </form>
      </div>
    </main>
  );
}

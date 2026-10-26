import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../auth/authContext';
import {
  friendlyError,
  listAccounts,
  setAccountAccess,
  type AccessLevel,
  type AccountSummary,
} from '../../services/authApi';
import {
  Badge,
  Card,
  DataTable,
  EmptyState,
  PageHeader,
  Skeleton,
  Toast,
  type DataTableColumn,
} from '../../components/ui';

const LEVELS: Array<{ value: AccessLevel; label: string }> = [
  { value: 'OWNER', label: 'Admin (owner everywhere)' },
  { value: 'OPERATOR', label: 'Operator everywhere' },
  { value: 'VIEWER', label: 'Viewer everywhere' },
  { value: 'NONE', label: 'No access' },
];

function uniformLevel(account: AccountSummary, workspaceCount: number): AccessLevel | 'MIXED' {
  if (!account.memberships.length) return 'NONE';
  const roles = new Set(account.memberships.map((item) => item.role));
  if (roles.size === 1 && account.memberships.length === workspaceCount) return account.memberships[0].role;
  return 'MIXED';
}

export default function AdminPage() {
  const { session, refresh } = useAuth();
  const isAdmin = Boolean(session?.user.is_admin);
  const [accounts, setAccounts] = useState<AccountSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) return undefined;
    let cancelled = false;
    listAccounts()
      .then((data) => { if (!cancelled) setAccounts(data); })
      .catch((err: unknown) => { if (!cancelled) setError(friendlyError(err, 'Unable to load accounts')); });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  if (!isAdmin) {
    return (
      <main className="app-page"><div className="app-page-content">
        <PageHeader eyebrow="Administration" title="Admin console" />
        <Card>
          <EmptyState
            title="Administrator access required"
            description="Only admins (owners of every workspace) can open this page. Ask an admin to promote your account, or see docs/guides for the command-line option."
            action={<Link className="p3-button p3-button-primary" to="/">Back to overview</Link>}
          />
        </Card>
      </div></main>
    );
  }

  const workspaceCount = session?.memberships.length ?? 0;

  const change = async (account: AccountSummary, level: AccessLevel) => {
    setBusyId(account.user_id);
    setError(null);
    setNotice(null);
    try {
      const updated = await setAccountAccess(account.user_id, level);
      setAccounts((current) => current?.map((item) => (item.user_id === updated.user_id ? updated : item)) ?? null);
      setNotice(`${account.email}: ${LEVELS.find((item) => item.value === level)?.label.toLowerCase()}`);
      if (account.user_id === session?.user.user_id) await refresh();
    } catch (err: unknown) {
      setError(friendlyError(err, 'The change could not be saved'));
    } finally {
      setBusyId(null);
    }
  };

  const columns: DataTableColumn<AccountSummary>[] = [
    {
      key: 'email',
      header: 'Account',
      render: (account) => (
        <span>
          {account.email}
          {account.user_id === session?.user.user_id ? <Badge className="users-you">you</Badge> : null}
          {account.is_admin ? <Badge className="users-you ui-confidence-high">admin</Badge> : null}
        </span>
      ),
    },
    {
      key: 'workspaces',
      header: 'Workspaces',
      render: (account) => (account.memberships.length
        ? <span className="admin-workspaces">{account.memberships.map((item) => `${item.tenant_name}: ${item.role.toLowerCase()}`).join(' · ')}</span>
        : <span className="p3-footer">No access</span>),
    },
    {
      key: 'access',
      header: 'Access in every workspace',
      render: (account) => {
        const level = uniformLevel(account, workspaceCount);
        return (
          <select
            aria-label={`Access for ${account.email}`}
            value={level}
            disabled={busyId !== null}
            onChange={(event) => void change(account, event.target.value as AccessLevel)}
          >
            {level === 'MIXED' ? <option value="MIXED" disabled>Mixed (per workspace)</option> : null}
            {LEVELS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        );
      },
    },
  ];

  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Administration"
          title="Admin console"
          description="Every registered account and its access across all workspaces. Per-workspace roles can still be fine-tuned on the Users page."
          actions={<Link className="p3-link-button" to="/users">Users (this workspace)</Link>}
        />
        {error ? <Toast message={error} tone="error" onDismiss={() => setError(null)} /> : null}
        {notice ? <Toast message={notice} tone="success" onDismiss={() => setNotice(null)} /> : null}
        <Card>
          {accounts === null && !error ? <Skeleton rows={4} /> : (
            <DataTable
              columns={columns}
              rows={accounts ?? []}
              getRowKey={(account) => account.user_id}
              emptyMessage="No accounts are registered yet."
            />
          )}
        </Card>
        <Card>
          <h2>How admin access works</h2>
          <p className="p3-footer">
            An admin is an account that owns every workspace. The first account registered becomes admin automatically.
            A server can also define one with CAPSTONE_ADMIN_EMAIL and CAPSTONE_ADMIN_PASSWORD, and an existing account
            can be promoted from a terminal with <code>python -m scripts.manage_users promote you@example.com</code>.
            You cannot remove your own admin access, and every workspace always keeps at least one owner.
          </p>
        </Card>
      </div>
    </main>
  );
}

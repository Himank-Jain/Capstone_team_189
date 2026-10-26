import { useEffect, useState, type FormEvent } from 'react';
import { useAuth } from '../../auth/authContext';
import {
  addMember,
  friendlyError,
  listMembers,
  removeMember,
  updateMemberRole,
  type Member,
  type Role,
} from '../../services/authApi';
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  FormField,
  PageHeader,
  Skeleton,
  Toast,
  type DataTableColumn,
} from '../../components/ui';

const ROLES: Role[] = ['OWNER', 'OPERATOR', 'VIEWER'];
const ROLE_HELP: Record<Role, string> = {
  OWNER: 'Manage members and roles, plus everything an operator can do.',
  OPERATOR: 'Run demo scenarios, acknowledge and resolve incidents, send test notifications.',
  VIEWER: 'Read-only access to alerts, incidents, and explanations.',
};

export default function UsersPage() {
  const { session, role, activeMembership, refresh } = useAuth();
  const isOwner = role === 'OWNER';
  const [members, setMembers] = useState<Member[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [newRole, setNewRole] = useState<Role>('VIEWER');
  const [busy, setBusy] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<Member | null>(null);

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listMembers()
      .then((data) => { if (!cancelled) setMembers(data); })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(friendlyError(err, 'Unable to load members'));
        setMembers([]);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(success);
      setReloadKey((key) => key + 1);
      await refresh();
    } catch (err: unknown) {
      setError(friendlyError(err, 'The change could not be saved'));
    } finally {
      setBusy(false);
    }
  };

  const handleAdd = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!email.trim()) return;
    void run(async () => {
      await addMember(email.trim(), newRole);
      setEmail('');
    }, `${email.trim()} added as ${newRole.toLowerCase()}`);
  };

  const columns: DataTableColumn<Member>[] = [
    {
      key: 'email',
      header: 'Member',
      render: (member) => (
        <span>
          {member.email}
          {member.user_id === session?.user.user_id ? <Badge className="users-you">you</Badge> : null}
        </span>
      ),
    },
    {
      key: 'role',
      header: 'Role',
      render: (member) => (isOwner ? (
        <select
          aria-label={`Role for ${member.email}`}
          value={member.role}
          disabled={busy}
          onChange={(event) => {
            const next = event.target.value as Role;
            void run(() => updateMemberRole(member.user_id, next), `${member.email} is now ${next.toLowerCase()}`);
          }}
        >
          {ROLES.map((item) => <option key={item} value={item}>{item.toLowerCase()}</option>)}
        </select>
      ) : <Badge>{member.role.toLowerCase()}</Badge>),
    },
    {
      key: 'joined',
      header: 'Joined',
      render: (member) => (member.joined_at ? new Date(member.joined_at).toLocaleDateString() : '—'),
    },
    ...(isOwner ? [{
      key: 'actions',
      header: '',
      render: (member: Member) => (
        <Button type="button" variant="ghost" disabled={busy} onClick={() => setPendingRemoval(member)}>
          Remove
        </Button>
      ),
    }] : []),
  ];

  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Administration"
          title="Users"
          description={`Members of ${activeMembership?.tenant_name || 'this workspace'} and what each role can do.`}
        />
        {error ? <Toast message={error} tone="error" onDismiss={() => setError(null)} /> : null}
        {notice ? <Toast message={notice} tone="success" onDismiss={() => setNotice(null)} /> : null}
        <Card>
          {members === null ? <Skeleton rows={4} /> : (
            <DataTable
              columns={columns}
              rows={members}
              getRowKey={(member) => member.user_id}
              emptyMessage="No members are listed for this workspace."
            />
          )}
        </Card>
        {isOwner ? (
          <Card className="users-invite">
            <h2>Add a member</h2>
            <p>They need to create an account first. Then add their email here to give them access to this workspace.</p>
            <form className="users-invite-form" onSubmit={handleAdd}>
              <FormField label="Email">
                <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
              </FormField>
              <FormField label="Role">
                <select value={newRole} onChange={(event) => setNewRole(event.target.value as Role)}>
                  {ROLES.map((item) => <option key={item} value={item}>{item.toLowerCase()}</option>)}
                </select>
              </FormField>
              <Button variant="primary" type="submit" disabled={busy || !email.trim()}>Add member</Button>
            </form>
          </Card>
        ) : (
          <Card>
            <p className="p3-footer">
              Your role here is <strong>{role?.toLowerCase() || 'none'}</strong>. Only owners can add members or change roles.
            </p>
          </Card>
        )}
        <Card>
          <h2>Roles</h2>
          <dl className="users-roles">
            {ROLES.map((item) => (
              <div key={item}><dt>{item.toLowerCase()}</dt><dd>{ROLE_HELP[item]}</dd></div>
            ))}
          </dl>
        </Card>
        <ConfirmDialog
          open={pendingRemoval !== null}
          title="Remove member?"
          description={`${pendingRemoval?.email ?? 'This member'} will lose access to this workspace. Their account is not deleted.`}
          confirmLabel="Remove member"
          onCancel={() => setPendingRemoval(null)}
          onConfirm={() => {
            const member = pendingRemoval;
            setPendingRemoval(null);
            if (member) void run(() => removeMember(member.user_id), `${member.email} removed`);
          }}
        />
      </div>
    </main>
  );
}

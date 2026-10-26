import ModulePage from '../../components/ui/ModulePage';

export default function UsersPage() {
  return (
    <ModulePage
      eyebrow="Administration"
      title="Users"
      description="Tenant membership and role controls for the current workspace."
      emptyTitle="No additional member records"
      emptyDescription="The current demo identity is provisioned locally. Tenant membership remains enforced by the API."
      action={{ label: 'Choose organization', to: '/select-org' }}
    />
  );
}

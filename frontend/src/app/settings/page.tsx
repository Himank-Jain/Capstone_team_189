import ModulePage from '../../components/ui/ModulePage';

export default function SettingsPage() {
  return (
    <ModulePage
      eyebrow="Administration"
      title="Settings"
      description="Manage tenant configuration and operational integrations."
      emptyTitle="Tenant settings are managed during onboarding"
      emptyDescription="Review connections or resume the guided setup to configure this workspace."
      action={{ label: 'Open connections', to: '/connections' }}
    />
  );
}

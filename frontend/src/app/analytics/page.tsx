import ModulePage from '../../components/ui/ModulePage';

export default function AnalyticsPage() {
  return (
    <ModulePage
      eyebrow="Operations"
      title="Analytics"
      description="Explore behavior trends, alert patterns, and tenant activity over time."
      emptyTitle="Analytics data is not connected yet"
      emptyDescription="The current demo provides the live alert stream and entity-level scores. Run a scenario to review the available trend data."
      action={{ label: 'Open live demo', to: '/demo' }}
    />
  );
}

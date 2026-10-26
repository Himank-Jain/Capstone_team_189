import ModulePage from '../../components/ui/ModulePage';

export default function SystemHealthPage() {
  return (
    <ModulePage
      eyebrow="Platform health"
      title="System health"
      description="Review the services that support ingestion, scoring, RCA, and notification delivery."
      emptyTitle="Service health checks are unavailable"
      emptyDescription="No live service telemetry is configured for this demo workspace. The frontend remains usable in mock mode."
      action={{ label: 'Open live demo', to: '/demo' }}
    />
  );
}

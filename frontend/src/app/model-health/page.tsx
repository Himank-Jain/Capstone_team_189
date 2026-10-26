import ModulePage from '../../components/ui/ModulePage';

export default function ModelHealthPage() {
  return (
    <ModulePage
      eyebrow="Platform health"
      title="Model health"
      description="Inspect the encoder and baseline data that support unsupervised anomaly scoring."
      emptyTitle="No model telemetry available"
      emptyDescription="Model registry summaries are not currently exposed through this dashboard route."
      action={{ label: 'Review system health', to: '/system-health' }}
    />
  );
}

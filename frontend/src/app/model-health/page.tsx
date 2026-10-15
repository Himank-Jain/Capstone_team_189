import { Card, DataTable, PageHeader } from '../../components/ui';
import type { DataTableColumn } from '../../components/ui';
import { evaluation } from '../../data/evaluation';
import type { ModelVersion } from '../../data/evaluation';

const columns: DataTableColumn<ModelVersion>[] = [
  { key: 'version', header: 'Version', render: (m) => m.version },
  { key: 'dim', header: 'Embedding size', render: (m) => m.embedding_dim },
  { key: 'seq', header: 'Window (events)', render: (m) => m.sequence_length },
  { key: 'cloud', header: 'Clouds', render: (m) => m.vocab.cloud },
  { key: 'type', header: 'Entity types', render: (m) => m.vocab.entity_type },
  { key: 'ns', header: 'Namespaces', render: (m) => m.vocab.namespace },
  { key: 'metric', header: 'Metrics', render: (m) => m.vocab.metric_name },
];

export default function ModelHealthPage() {
  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Platform health"
          title="Model health"
          description="Registered encoder versions and the vocabulary each was trained on."
        />
        <Card>
          <div className="section-heading">
            <div>
              <p className="ui-eyebrow">Model registry</p>
              <h2>Encoder versions</h2>
            </div>
          </div>
          <DataTable columns={columns} rows={evaluation.models} getRowKey={(m) => m.version} />
          <p className="eval-note">Metrics, namespaces or clouds outside these vocabularies map to a shared unknown slot, and their values are standardised online so the encoder still scores them.</p>
        </Card>
      </div>
    </main>
  );
}

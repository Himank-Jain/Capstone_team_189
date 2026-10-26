import { Link } from 'react-router-dom';
import { Card, EmptyState, PageHeader } from './index';

export default function ModulePage({
  eyebrow,
  title,
  description,
  emptyTitle,
  emptyDescription,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  emptyTitle: string;
  emptyDescription: string;
  action?: { label: string; to: string };
}) {
  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader eyebrow={eyebrow} title={title} description={description} />
        <Card>
          <EmptyState
            title={emptyTitle}
            description={emptyDescription}
            action={action ? <Link className="p3-button p3-button-primary" to={action.to}>{action.label}</Link> : undefined}
          />
        </Card>
      </div>
    </main>
  );
}

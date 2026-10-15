import { useParams } from 'react-router-dom';
import ModulePage from '../../../components/ui/ModulePage';

export default function EntityPage() {
  const { entityId = 'unknown' } = useParams();
  return (
    <ModulePage
      eyebrow="Resource profile"
      title={entityId}
      description="Review the resource's behavioral baseline, recent scores, and related incidents."
      emptyTitle="Entity profile is not available"
      emptyDescription="No profile has been loaded for this entity in the current demo session."
      action={{ label: 'Browse alerts', to: '/alerts' }}
    />
  );
}

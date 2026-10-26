import { StatCard } from './ui';

interface DemoStatusCardProps {
  title: string;
  value: string | number;
  description?: string;
  accent?: string;
}

export default function DemoStatusCard({ title, value, description }: DemoStatusCardProps) {
  const tone = title.toLowerCase().includes('critical')
    ? 'critical'
    : title.toLowerCase().includes('confidence')
      ? 'success'
      : title.toLowerCase().includes('status')
        ? 'warning'
        : 'brand';
  return <StatCard label={title} value={value} detail={description} tone={tone} />;
}

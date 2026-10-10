interface DemoStatusCardProps {
  title: string;
  value: string | number;
  description?: string;
  accent?: string;
}

export default function DemoStatusCard({ title, value, description, accent = '#2563eb' }: DemoStatusCardProps) {
  return (
    <div style={{ padding: '18px', borderRadius: '18px', background: '#0f172a', border: `1px solid ${accent}` }}>
      <p style={{ margin: 0, color: '#9ca3af', fontSize: '13px' }}>{title}</p>
      <h3 style={{ margin: '10px 0 0', fontSize: '28px', color: '#f8fafc' }}>{value}</h3>
      {description ? <p style={{ margin: '10px 0 0', color: '#94a3b8', fontSize: '14px' }}>{description}</p> : null}
    </div>
  );
}

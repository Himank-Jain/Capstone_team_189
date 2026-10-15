import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({ className = '', variant = 'secondary', ...props }: ButtonProps) {
  return <button className={`ui-button ui-button-${variant} ${className}`.trim()} {...props} />;
}

export function Card({ className = '', ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={`ui-card ${className}`.trim()} {...props} />;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="ui-page-header">
      <div>
        {eyebrow ? <p className="ui-eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {description ? <p className="ui-page-description">{description}</p> : null}
      </div>
      {actions ? <div className="ui-page-actions">{actions}</div> : null}
    </header>
  );
}

export function StatCard({
  label,
  value,
  detail,
  tone = 'brand',
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: 'brand' | 'critical' | 'warning' | 'success' | 'neutral';
}) {
  return (
    <Card className={`ui-stat-card ui-stat-${tone}`}>
      <p className="ui-stat-label">{label}</p>
      <p className="ui-stat-value">{value}</p>
      {detail ? <p className="ui-stat-detail">{detail}</p> : null}
    </Card>
  );
}

export interface DataTableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
}

export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  emptyMessage = 'No records to show.',
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowKey: (row: T, index: number) => string;
  emptyMessage?: string;
}) {
  if (!rows.length) return <EmptyState title="Nothing here yet" description={emptyMessage} />;
  return (
    <div className="ui-table-scroll">
      <table className="ui-table">
        <thead>
          <tr>{columns.map((column) => <th key={column.key} scope="col">{column.header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={getRowKey(row, index)}>
              {columns.map((column) => <td key={column.key}>{column.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Badge({ className = '', children }: { className?: string; children: ReactNode }) {
  return <span className={`ui-badge ${className}`.trim()}>{children}</span>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  const key = severity.toLowerCase();
  const tone = ['low', 'medium', 'high', 'critical'].includes(key) ? key : 'low';
  return <Badge className={`ui-severity-${tone}`}>{severity}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const key = status.toLowerCase().replace(/_/g, '-');
  const tone = ['open', 'acknowledged', 'resolved', 'regression'].includes(key) ? key : 'open';
  return <Badge className={`ui-status-${tone}`}>{status.replace(/_/g, ' ')}</Badge>;
}

export function ConfidenceBadge({ confidence }: { confidence: string }) {
  const key = confidence.toLowerCase();
  const tone = ['high', 'medium', 'low'].includes(key) ? key : 'low';
  return <Badge className={`ui-confidence-${tone}`}>{confidence}</Badge>;
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="ui-empty-state" role="status">
      <span className="ui-empty-mark" aria-hidden="true">—</span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action ? <div className="ui-empty-action">{action}</div> : null}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="ui-skeleton-stack" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, index) => <span className="ui-skeleton" key={index} />)}
    </div>
  );
}

export function Stepper({
  items,
  activeIndex,
  onSelect,
}: {
  items: string[];
  activeIndex: number;
  onSelect?: (index: number) => void;
}) {
  return (
    <ol className="ui-stepper">
      {items.map((item, index) => {
        const state = index < activeIndex ? 'complete' : index === activeIndex ? 'current' : 'upcoming';
        const content = (
          <>
            <span className="ui-step-marker">{state === 'complete' ? '✓' : index + 1}</span>
            <span>{item}</span>
          </>
        );
        return (
          <li className={`ui-step ui-step-${state}`} key={item}>
            {onSelect ? (
              <button
                type="button"
                aria-current={state === 'current' ? 'step' : undefined}
                aria-label={`${item}${state === 'complete' ? ', complete' : state === 'current' ? ', current step' : ''}`}
                onClick={() => onSelect(index)}
              >
                {content}
              </button>
            ) : <div aria-current={state === 'current' ? 'step' : undefined}>{content}</div>}
          </li>
        );
      })}
    </ol>
  );
}

export function FormField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="ui-form-field">
      <span className="ui-form-label">{label}</span>
      {children}
      {hint ? <span className="ui-form-hint">{hint}</span> : null}
    </label>
  );
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  confirmDisabled = false,
  children,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  confirmDisabled?: boolean;
  children?: ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="ui-dialog-backdrop">
      <section className="ui-dialog" role="alertdialog" aria-modal="true" aria-labelledby="ui-dialog-title">
        <h2 id="ui-dialog-title">{title}</h2>
        <p>{description}</p>
        {children}
        <div className="ui-dialog-actions">
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="danger" onClick={onConfirm} disabled={confirmDisabled}>{confirmLabel}</Button>
        </div>
      </section>
    </div>
  );
}

export function Toast({
  message,
  tone = 'info',
  onDismiss,
}: {
  message: string;
  tone?: 'info' | 'success' | 'error';
  onDismiss?: () => void;
}) {
  return (
    <div className={`ui-toast ui-toast-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <span>{message}</span>
      {onDismiss ? <Button className="ui-toast-dismiss" aria-label="Dismiss notification" onClick={onDismiss}>×</Button> : null}
    </div>
  );
}

export function Tabs({
  items,
  active,
  onChange,
  label,
}: {
  items: string[];
  active: string;
  onChange: (item: string) => void;
  label: string;
}) {
  return (
    <div className="ui-tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          type="button"
          role="tab"
          aria-selected={active === item}
          className="ui-tab"
          key={item}
          onClick={() => onChange(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}

export const rechartsTheme = {
  grid: 'var(--color-app-border)',
  axis: 'var(--color-app-muted)',
  tooltip: {
    background: 'var(--color-app-raised)',
    border: 'var(--color-app-border)',
    text: 'var(--color-app-text)',
  },
  series: [
    'var(--color-brand)',
    'var(--color-accent)',
    'var(--color-severity-medium)',
    'var(--color-severity-critical)',
    'var(--color-status-regression)',
  ],
} as const;

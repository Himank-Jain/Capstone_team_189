import { Card, PageHeader, StatCard } from '../../components/ui';
import { evaluation } from '../../data/evaluation';

const SCHEMA_LABELS: Record<string, string> = {
  'shift/in_vocab': 'Known schema',
  'shift/oov_passthrough': 'Unseen schema, old fallback',
  'shift/oov_online': 'Unseen schema, online statistics',
  'spike/in_vocab': 'Known schema',
  'spike/oov_passthrough': 'Unseen schema, old fallback',
  'spike/oov_online': 'Unseen schema, online statistics',
};

function Bar({ value, max, label, detail }: { value: number; max: number; label: string; detail: string }) {
  const width = Math.max(1, Math.min(100, (value / max) * 100));
  return (
    <div className="eval-bar-row">
      <span className="eval-bar-label">{label}</span>
      <div className="eval-bar-track" role="img" aria-label={`${label}: ${detail}`}>
        <div className="eval-bar-fill" style={{ width: `${width}%` }} />
      </div>
      <span className="eval-bar-detail">{detail}</span>
    </div>
  );
}

export default function AnalyticsPage() {
  const { guard, schema_free: schema, explanation, cold_start: cold } = evaluation;
  const maxDrift = Math.max(...guard.strategies.map((s) => s.stored_drift), 1);
  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Operations"
          title="Analytics"
          description="Measured results from the drift-guard, schema-free encoder and explanation evaluations."
        />
        <div className="dashboard-stats ui-stat-grid">
          <StatCard label="Entities evaluated" value={guard.n_entities} detail="AWS CloudWatch series" />
          <StatCard label="Identical explanations" value={`${explanation.identical_pct}%`} detail={`${explanation.runs.toLocaleString()} repeated runs`} tone="success" />
          <StatCard label="Explanation latency" value={`${explanation.median_ms.toFixed(2)} ms`} detail={`median, p95 ${explanation.p95_ms.toFixed(2)} ms`} />
          <StatCard label="Network calls" value={explanation.network_attempts} detail="during explanation runs" tone="neutral" />
        </div>

        <Card className="dashboard-alerts">
          <div className="section-heading">
            <div>
              <p className="ui-eyebrow">Invention A</p>
              <h2>Baseline drift after a slow poisoning ramp</h2>
            </div>
          </div>
          <p className="eval-note">Median stored baseline shift, in standard deviations, when the ramp ends. Lower means the baseline moved less. Real AWS CloudWatch series with simulated attacks.</p>
          {guard.strategies.map((s) => (
            <Bar key={s.key} label={s.label} value={s.stored_drift} max={maxDrift} detail={`${s.stored_drift.toFixed(2)}σ`} />
          ))}
        </Card>

        <Card className="dashboard-alerts">
          <div className="section-heading">
            <div>
              <p className="ui-eyebrow">Invention A</p>
              <h2>Detection and alert rates</h2>
            </div>
          </div>
          <div className="ui-table-scroll">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">Strategy</th>
                  <th scope="col">Attacks detected</th>
                  <th scope="col">Alerts on clean control</th>
                  <th scope="col">Alerts on real growth</th>
                </tr>
              </thead>
              <tbody>
                {guard.strategies.map((s) => (
                  <tr key={s.key}>
                    <td>{s.label}</td>
                    <td>{s.attack.k} / {s.attack.n}</td>
                    <td>{s.control_alert.k} / {s.control_alert.n}</td>
                    <td>{s.benign_alert.k} / {s.benign_alert.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="dashboard-alerts">
          <div className="section-heading">
            <div>
              <p className="ui-eyebrow">Invention C</p>
              <h2>Detection on schemas the encoder never saw</h2>
            </div>
          </div>
          <p className="eval-note">AUC of embedding deviation, 30 synthetic entities per condition. 0.5 is chance.</p>
          {schema.map((r) => (
            <Bar
              key={r.key}
              label={`${r.key.startsWith('shift') ? 'Level shift' : 'Spikes'} · ${SCHEMA_LABELS[r.key] ?? r.key}`}
              value={r.auc}
              max={1}
              detail={r.auc.toFixed(2)}
            />
          ))}
        </Card>

        <Card className="dashboard-alerts">
          <div className="section-heading">
            <div>
              <p className="ui-eyebrow">Dependent feature</p>
              <h2>Cohort cold start</h2>
            </div>
          </div>
          <p className="eval-note">New entity, hourly readings, a +4σ shift injected at hour 48. {cold.seeded.n} real AWS entities, each seeded from a cohort of other series.</p>
          <div className="ui-table-scroll">
            <table className="ui-table">
              <thead>
                <tr>
                  <th scope="col">Variant</th>
                  <th scope="col">Scoring starts (h)</th>
                  <th scope="col">Shift detected</th>
                  <th scope="col">Median delay (h)</th>
                  <th scope="col">False alerts / 100</th>
                </tr>
              </thead>
              <tbody>
                {(['unseeded', 'seeded'] as const).map((k) => (
                  <tr key={k}>
                    <td>{k === 'seeded' ? 'Cohort seeded' : 'Unseeded'}</td>
                    <td>{cold[k].scoring_start_h}</td>
                    <td>{cold[k].detected_k} / {cold[k].n}</td>
                    <td>{cold[k].delay_h}</td>
                    <td>{cold[k].false_per_100.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </main>
  );
}

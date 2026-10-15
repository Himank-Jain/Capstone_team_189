import { Card, PageHeader, StatCard } from '../../components/ui';
import { evaluation } from '../../data/evaluation';
import type { FrozenRow, Rate } from '../../data/evaluation';

const SCHEMA_LABELS: Record<string, string> = {
  'shift/in_vocab': 'Known schema',
  'shift/oov_passthrough': 'Unseen schema, old fallback',
  'shift/oov_online': 'Unseen schema, online statistics',
  'spike/in_vocab': 'Known schema',
  'spike/oov_passthrough': 'Unseen schema, old fallback',
  'spike/oov_online': 'Unseen schema, online statistics',
};

const pct = (r: Rate | null | undefined) => (r ? `${Math.round(r.rate * 100)}% (${Math.round(r.lo * 100)}–${Math.round(r.hi * 100)})` : '–');
const share = (x: number | null | undefined) => (x === null || x === undefined ? '–' : x.toFixed(2));
const proportion = (x: number | null | undefined) => (x === null || x === undefined ? '–' : `${Math.round(x * 100)}%`);

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
  const { frozen, schema_free: schema, explanation, cold_start: cold } = evaluation;
  return (
    <main className="app-page">
      <div className="app-page-content">
        <PageHeader
          eyebrow="Operations"
          title="Analytics"
          description="Frozen-design results for the governed baseline, plus the schema-free encoder, explanation and cold-start evaluations. NAB entities are synthetic replicas of real series."
        />
        <div className="dashboard-stats ui-stat-grid">
          <StatCard label="Series evaluated" value={frozen.reduce((n, d) => n + d.series, 0)} detail="2 development and 2 never-run sets" />
          <StatCard label="Identical explanations" value={`${explanation.identical_pct}%`} detail={`${explanation.runs.toLocaleString()} repeated runs`} tone="success" />
          <StatCard label="Explanation latency" value={`${explanation.median_ms.toFixed(2)} ms`} detail={`median, p95 ${explanation.p95_ms.toFixed(2)} ms`} />
          <StatCard label="Network calls" value={explanation.network_attempts} detail="during explanation runs" tone="neutral" />
        </div>

        {frozen.map((set) => (
          <Card key={set.key} className="dashboard-alerts">
            <div className="section-heading">
              <div>
                <p className="ui-eyebrow">Governed baseline · frozen design</p>
                <h2>{set.title}</h2>
              </div>
            </div>
            <p className="eval-note">
              {set.note}. {set.series} series ({set.entities} entities); {set.clean_series} clean series ({set.clean_entities} entities)
              {set.shifted_series ? `, ${set.shifted_series} with real level shifts` : ''}. Rates are shares with a 95% interval from a bootstrap over whole
              series. Thresholds fixed so development entities false-alert at 5% or less.
            </p>
            <div className="ui-table-scroll">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">Strategy</th>
                    <th scope="col">False alerts</th>
                    <th scope="col">2 sigma ramp detected</th>
                    <th scope="col">3 sigma ramp detected</th>
                    <th scope="col">Hour-only 4 sigma</th>
                    <th scope="col">Poisoned calibration</th>
                    <th scope="col">Silent shift at alert (sigma)</th>
                    <th scope="col">Growth left unresolved</th>
                    {set.shifted_series ? <th scope="col">Real shifts unresolved</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {set.rows.map((r: FrozenRow) => (
                    <tr key={r.key}>
                      <td>{r.label}</td>
                      <td>{pct(r.fpr)}</td>
                      <td>{pct(r.tpr2)}</td>
                      <td>{pct(r.tpr3)}</td>
                      <td>{pct(r.local)}</td>
                      <td>{pct(r.poisoned)}</td>
                      <td>{r.disp2.toFixed(2)}</td>
                      <td>{pct(r.benign_unresolved)}</td>
                      {set.shifted_series ? <td>{pct(r.real_unresolved)}</td> : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="eval-note">Share of a 3σ attack already in the stored baseline N days after the strategy&apos;s own first alert, and share of flagged legitimate shifts resolved by then.</p>
            <div className="ui-table-scroll">
              <table className="ui-table">
                <thead>
                  <tr>
                    <th scope="col">Strategy</th>
                    <th scope="col">Attack +14 d</th>
                    <th scope="col">+30 d</th>
                    <th scope="col">+60 d</th>
                    <th scope="col">Resolved +14 d</th>
                    <th scope="col">+30 d</th>
                    <th scope="col">+60 d</th>
                  </tr>
                </thead>
                <tbody>
                  {set.rows.filter((r: FrozenRow) => r.key !== 'guard_cal').map((r: FrozenRow) => (
                    <tr key={r.key}>
                      <td>{r.label}</td>
                      <td>{share(r.absorb['14'])}</td>
                      <td>{share(r.absorb['30'])}</td>
                      <td>{share(r.absorb['60'])}</td>
                      <td>{proportion(r.resolved['14'])}</td>
                      <td>{proportion(r.resolved['30'])}</td>
                      <td>{proportion(r.resolved['60'])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))}

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

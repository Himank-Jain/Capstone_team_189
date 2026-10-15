import raw from './evaluation.json';

export interface Strategy {
  key: string;
  label: string;
  stored_drift: number;
  attack: { k: number; n: number };
  control_alert: { k: number; n: number };
  benign_alert: { k: number; n: number };
}
export interface ModelVersion {
  version: string;
  embedding_dim: number;
  sequence_length: number;
  vocab: Record<string, number>;
}
export interface Evaluation {
  guard: { n_entities: number; strategies: Strategy[] };
  schema_free: { key: string; auc: number; ci95: [number, number] }[];
  explanation: { runs: number; identical_pct: number; median_ms: number; p95_ms: number; network_attempts: number };
  models: ModelVersion[];
  cold_start: Record<'unseeded' | 'seeded', { scoring_start_h: number; detected_k: number; n: number; delay_h: number; false_per_100: number }>;
}

export const evaluation = raw as unknown as Evaluation;

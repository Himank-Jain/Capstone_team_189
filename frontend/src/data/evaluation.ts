import raw from './evaluation.json';

export interface Rate {
  rate: number;
  lo: number;
  hi: number;
}
export interface FrozenRow {
  key: string;
  label: string;
  fpr: Rate | null;
  tpr2: Rate | null;
  tpr3: Rate | null;
  local: Rate | null;
  poisoned: Rate | null;
  disp2: number;
  benign_unresolved: Rate | null;
  real_unresolved: Rate | null;
  absorb: Record<'14' | '30' | '60', number | null>;
  resolved: Record<'14' | '30' | '60', number | null>;
}
export interface FrozenSet {
  key: string;
  title: string;
  note: string;
  entities: number;
  series: number;
  clean_entities: number;
  clean_series: number;
  shifted_series: number;
  rows: FrozenRow[];
}
export interface ModelVersion {
  version: string;
  embedding_dim: number;
  sequence_length: number;
  vocab: Record<string, number>;
}
export interface Evaluation {
  frozen: FrozenSet[];
  schema_free: { key: string; auc: number; ci95: [number, number] }[];
  explanation: { runs: number; identical_pct: number; median_ms: number; p95_ms: number; network_attempts: number };
  models: ModelVersion[];
  cold_start: Record<'unseeded' | 'seeded', { scoring_start_h: number; detected_k: number; n: number; delay_h: number; false_per_100: number }>;
}

export const evaluation = raw as unknown as Evaluation;

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type GroupType = "ISOLATED" | "CORRELATED" | "REGIONAL_OUTAGE";
export type SevLevel = "SEV1" | "SEV2" | "SEV3" | "SEV4";
export type NotifyMethod = "PAGE" | "SLACK" | "EMAIL";

export interface EpisodeMatch {
  similarity_score: number;
  episode_id: string;
  entity_id: string;
  timestamp: string;
  cloud_provider: string;
  severity_label?: string;
}

export interface AlertPayload {
  alert_id: string;
  entity_id: string;
  batch_ts: string;
  final_score: number;
  severity: Severity;
  sev_level: SevLevel;
  deviation_score: number;
  drift_score: number;
  similarity_score: number;
  similar_episodes: EpisodeMatch[];
  related_ids: string[];
  group_type: GroupType;
  target_team: string;
  notify_method: NotifyMethod;
  cloud_provider: string;
  region: string;
}

export interface EntityProfile {
  entity_id: string;
  centroid_emb: number[];
  history_embs: number[][];
  emb_variance: number;
  n_records: number;
  last_update_ts: string;
  cold_start_flag: boolean;
}

export interface CurrentEmbedding {
  entity_id: string;
  emb: number[];
  batch_ts: string;
  n_records: number;
  cloud_provider: string;
}

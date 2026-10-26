/**
 * In-browser alert events. The live WebSocket feeds the notification center in
 * API mode; mock mode (no backend) publishes demo alerts here instead.
 */
export const LOCAL_ALERT_EVENT = 'capstone:local-alert';

export interface LocalAlertMessage {
  type: 'alert';
  tenant_id: string;
  payload: {
    alert_id: string;
    entity_id: string;
    severity: string;
    final_score: number;
    batch_ts: string;
    cloud_provider?: string;
    region?: string;
  };
}

export function publishLocalAlert(message: LocalAlertMessage) {
  window.dispatchEvent(new CustomEvent<LocalAlertMessage>(LOCAL_ALERT_EVENT, { detail: message }));
}

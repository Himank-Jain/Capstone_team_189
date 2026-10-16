from typing import Any, Dict


def build_stage_heartbeat(stage: str, entity_id: str) -> Dict[str, Any]:
    return {
        "type": "stage_heartbeat",
        "stage": stage,
        "entity_id": entity_id,
        "ts": "2026-07-28T00:00:00Z",
    }

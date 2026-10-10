"""
phase2/alerting/notifiers/slack_notifier.py
==========================================
P2-M14  Explainable Alert API — SlackNotifier
CAPSTONE-189

Posts a formatted Slack Block Kit message to a webhook URL.

Design notes
------------
1. HTTP client injection (DIP). Accepts an httpx.AsyncClient (or any
   object exposing an async `.post(url, json=...)` returning something
   with `.status_code` and `.text`) via constructor injection, matching
   the project's established pattern (redis_client on
   AlertDeduplicator, faiss_indexer on EpisodeRetriever) -- makes this
   trivially testable with a fake client, no real network needed.

2. Rate limiting. Slack's documented webhook limit is 1 msg/sec (ticket
   watch-out). Wraps every send in AsyncRateLimiter keyed on the
   webhook URL itself, so multiple SlackNotifier instances (or the same
   instance handling bursts) never exceed that rate for a given
   webhook, while different webhooks (e.g. two Slack workspaces) don't
   throttle each other.

3. Severity color coding. Block Kit has no native "color" attribute the
   way legacy attachments did, but a colored `context` block emoji
   (🔴🟠🟡) gives an at-a-glance severity read without reintroducing
   the deprecated attachments API.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..api.models import AlertPayloadModel
from .base_notifier import BaseNotifier
from .rate_limiter import AsyncRateLimiter

_SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "MEDIUM": "🟡",
    "LOW": "🟢",
}


class SlackNotifier(BaseNotifier):
    def __init__(
        self,
        webhook_url: str,
        http_client: Any,
        rate_limiter: Optional[AsyncRateLimiter] = None,
    ) -> None:
        """
        Parameters
        ----------
        webhook_url:
            Slack incoming-webhook URL.
        http_client:
            Injected async HTTP client (e.g. httpx.AsyncClient()) — DIP,
            see module docstring note 1.
        rate_limiter:
            Injected AsyncRateLimiter. Defaults to a 1 msg/sec limiter
            (Slack's documented cap) if not supplied.
        """
        super().__init__(channel_name="slack")
        self._webhook_url = webhook_url
        self._http_client = http_client
        self._rate_limiter = rate_limiter if rate_limiter is not None else AsyncRateLimiter(min_interval_sec=1.0)

    def _build_block_kit_message(self, payload: AlertPayloadModel) -> Dict[str, Any]:
        emoji = _SEVERITY_EMOJI.get(payload.severity.value, "⚪")
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {payload.severity.value} anomaly — {payload.entity_id}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Final score:*\n{payload.final_score:.3f}"},
                    {"type": "mrkdwn", "text": f"*Escalation:*\n{payload.sev_level.value}"},
                    {"type": "mrkdwn", "text": f"*Deviation:*\n{payload.deviation_score:.3f}"},
                    {"type": "mrkdwn", "text": f"*Drift:*\n{payload.drift_score:.3f}"},
                    {"type": "mrkdwn", "text": f"*Similarity:*\n{payload.similarity_score:.3f}"},
                    {"type": "mrkdwn", "text": f"*Group:*\n{payload.group_type.value}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Cloud:* {payload.cloud_provider}  *Region:* {payload.region}\n"
                        f"*Target team:* {payload.target_team}\n"
                        f"*Related incidents:* {', '.join(payload.related_ids) or 'none'}"
                    ),
                },
            },
        ]
        if payload.contributing_features:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Contributing features: " + ", ".join(payload.contributing_features),
                        }
                    ],
                }
            )
        if payload.similar_episodes:
            top = payload.similar_episodes[0]
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"Most similar past episode: {top.episode_id} "
                                f"(similarity {top.similarity_score:.3f})"
                            ),
                        }
                    ],
                }
            )
        return {
            "text": f"{emoji} {payload.severity.value} anomaly on {payload.entity_id}",
            "blocks": blocks,
        }

    async def _send(self, payload: AlertPayloadModel) -> str:
        await self._rate_limiter.acquire(self._webhook_url)
        message = self._build_block_kit_message(payload)
        response = await self._http_client.post(self._webhook_url, json=message)
        status_code = getattr(response, "status_code", None)
        if status_code is not None and status_code >= 300:
            raise RuntimeError(f"Slack webhook returned HTTP {status_code}: {getattr(response, 'text', '')}")
        return f"HTTP {status_code}" if status_code is not None else "sent"

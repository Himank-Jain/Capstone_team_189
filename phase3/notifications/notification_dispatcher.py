from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from phase3.shared.constants import (
    PLATFORM_DEFAULT_TENANT_ID,
    PLATFORM_DISPATCH_TIMEOUT_SECONDS,
    PLATFORM_IDEMPOTENCY_TTL_SECONDS,
    PLATFORM_MAX_RETRIES,
    PLATFORM_RETRY_BACKOFF_SECONDS,
)
from phase3.shared.types import NotificationDeliveryResult, NotificationEndpoint, NotificationPolicy
from shared.types import AlertPayload, Severity

logger = logging.getLogger(__name__)


def _mask_target(target: str) -> str:
    if not target:
        return "<empty>"
    if "@" in target and not target.startswith(("http://", "https://")):
        local, domain = target.split("@", 1)
        return f"{local[:1]}***@{domain}"
    if target.startswith(("http://", "https://")):
        parsed = urlsplit(target)
        return f"{parsed.scheme}://***"
    return "***"


def _sanitize_error(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return message.replace("\n", " ")


class NotificationEndpointRepository(ABC):
    @abstractmethod
    def list_for_tenant(self, tenant_id: str) -> List[NotificationEndpoint]:
        raise NotImplementedError


class InMemoryNotificationEndpointRepository(NotificationEndpointRepository):
    def __init__(self, endpoints: Optional[Iterable[NotificationEndpoint]] = None) -> None:
        self._endpoints: Dict[str, List[NotificationEndpoint]] = {}
        if endpoints:
            for endpoint in endpoints:
                self._endpoints.setdefault(endpoint.tenant_id, []).append(endpoint)

    def add(self, endpoint: NotificationEndpoint) -> None:
        self._endpoints.setdefault(endpoint.tenant_id, []).append(endpoint)

    def list_for_tenant(self, tenant_id: str) -> List[NotificationEndpoint]:
        return list(self._endpoints.get(tenant_id, []))


class NotificationDeliveryRecorder(ABC):
    @abstractmethod
    async def record(self, result: NotificationDeliveryResult) -> None:
        raise NotImplementedError


class InMemoryNotificationDeliveryRecorder(NotificationDeliveryRecorder):
    def __init__(self) -> None:
        self._results: List[NotificationDeliveryResult] = []

    async def record(self, result: NotificationDeliveryResult) -> None:
        self._results.append(result)

    def results(self) -> List[NotificationDeliveryResult]:
        return list(self._results)

    def clear_for_tenant(self, tenant_id: str) -> None:
        self._results = [result for result in self._results if result.tenant_id != tenant_id]


class IdempotencyStore(ABC):
    @abstractmethod
    async def acquire(self, key: str, ttl_seconds: int = PLATFORM_IDEMPOTENCY_TTL_SECONDS) -> bool:
        raise NotImplementedError


class InMemoryIdempotencyStore(IdempotencyStore):
    def __init__(self) -> None:
        self._items: Dict[str, datetime] = {}

    async def acquire(self, key: str, ttl_seconds: int = PLATFORM_IDEMPOTENCY_TTL_SECONDS) -> bool:
        now = datetime.now(timezone.utc)
        expires_at = self._items.get(key)
        if expires_at is not None and expires_at > now:
            return False
        self._items[key] = now + __import__("datetime").timedelta(seconds=ttl_seconds)
        return True


class NotificationDispatcher:
    def __init__(
        self,
        notifiers: Optional[List[Any]] = None,
        endpoints: Optional[List[NotificationEndpoint]] = None,
        endpoint_repository: Optional[NotificationEndpointRepository] = None,
        delivery_recorder: Optional[NotificationDeliveryRecorder] = None,
        idempotency_store: Optional[IdempotencyStore] = None,
    ) -> None:
        self._notifiers = list(notifiers or [])
        self._endpoint_repository = endpoint_repository or InMemoryNotificationEndpointRepository(
            endpoints
        )
        self._delivery_recorder = delivery_recorder or InMemoryNotificationDeliveryRecorder()
        self._idempotency_store = idempotency_store or InMemoryIdempotencyStore()

    def _channel_map(self) -> Dict[str, Any]:
        return {
            str(getattr(notifier, "channel_name", "")).lower(): notifier
            for notifier in self._notifiers
        }

    def _policy_allowed_channels(self, policy: NotificationPolicy) -> Optional[set[str]]:
        if not policy.allowed_channels:
            return None
        return {channel.lower() for channel in policy.allowed_channels}

    @staticmethod
    def _entity_to_tenant_id(payload: Any) -> str:
        entity_id = str(
            getattr(payload, "entity_id", "")
            or (payload.get("entity_id") if isinstance(payload, dict) else "")
        ).strip()
        if not entity_id:
            return PLATFORM_DEFAULT_TENANT_ID
        mapping = {
            "vol-g00g": "google",
            "vol-msft": "microsoft",
            "vol-amzn": "amazon",
            "vol-orcl": "oracle",
            "vol-acme": "acme",
        }
        return mapping.get(entity_id.lower(), PLATFORM_DEFAULT_TENANT_ID)

    async def resolve_policy_for_alert(
        self, payload: Any, *, tenant_id: Optional[str] = None
    ) -> NotificationPolicy:
        resolved_tenant = (
            tenant_id or getattr(payload, "tenant_id", None) or self._entity_to_tenant_id(payload)
        )
        notify_method = getattr(payload, "notify_method", None)
        if notify_method is None and isinstance(payload, dict):
            notify_method = payload.get("notify_method")
        channel = None
        if hasattr(notify_method, "value"):
            channel = str(notify_method.value).lower()
        elif isinstance(notify_method, str):
            channel = notify_method.lower()
        if channel is None:
            channel = "email"
        return NotificationPolicy(
            tenant_id=resolved_tenant or PLATFORM_DEFAULT_TENANT_ID, allowed_channels=[channel]
        )

    def _severity_allowed(self, current: Severity, minimum: Optional[Severity]) -> bool:
        if minimum is None:
            return True
        severity_order = {
            Severity.LOW: 0,
            Severity.MEDIUM: 1,
            Severity.HIGH: 2,
            Severity.CRITICAL: 3,
        }
        return severity_order.get(current, -1) >= severity_order.get(minimum, -1)

    def _is_quiet_hours(self, policy: NotificationPolicy) -> bool:
        if not policy.quiet_hours_start or not policy.quiet_hours_end or not policy.quiet_hours_tz:
            return False
        try:
            tz = ZoneInfo(policy.quiet_hours_tz)
        except Exception:
            logger.warning(
                "[NotificationDispatcher] invalid quiet_hours_tz=%s", policy.quiet_hours_tz
            )
            return False

        now = datetime.now(tz)
        start_minutes = self._parse_clock(policy.quiet_hours_start)
        end_minutes = self._parse_clock(policy.quiet_hours_end)
        current_minutes = now.hour * 60 + now.minute

        if start_minutes <= end_minutes:
            return start_minutes <= current_minutes < end_minutes
        return current_minutes >= start_minutes or current_minutes < end_minutes

    @staticmethod
    def _parse_clock(value: str) -> int:
        hours, minutes = value.split(":", 1)
        return int(hours) * 60 + int(minutes)

    def _resolve_endpoints_for_policy(
        self, policy: NotificationPolicy
    ) -> List[NotificationEndpoint]:
        tenant_id = policy.tenant_id or PLATFORM_DEFAULT_TENANT_ID
        endpoints = self._endpoint_repository.list_for_tenant(tenant_id)
        allowed_channels = self._policy_allowed_channels(policy)
        filtered: List[NotificationEndpoint] = []
        for endpoint in endpoints:
            if not endpoint.enabled:
                continue
            if allowed_channels is not None and endpoint.channel.lower() not in allowed_channels:
                continue
            if self._is_quiet_hours(policy):
                continue
            filtered.append(endpoint)
        return filtered

    async def dispatch(
        self,
        payload: AlertPayload,
        policy: NotificationPolicy,
        timeout_seconds: Optional[float] = None,
        idempotency_suffix: Optional[str] = None,
    ) -> List[NotificationDeliveryResult]:
        if policy is None:
            policy = NotificationPolicy(tenant_id=PLATFORM_DEFAULT_TENANT_ID)

        tenant_id = policy.tenant_id or PLATFORM_DEFAULT_TENANT_ID
        endpoints = self._resolve_endpoints_for_policy(policy)
        if not endpoints:
            return []

        tasks = [
            self._deliver_endpoint(
                payload,
                endpoint,
                policy,
                timeout_seconds=timeout_seconds
                or policy.timeout_seconds
                or PLATFORM_DISPATCH_TIMEOUT_SECONDS,
                idempotency_suffix=idempotency_suffix,
            )
            for endpoint in endpoints
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        final_results: List[NotificationDeliveryResult] = []
        for result in results:
            if result is None:
                continue
            if isinstance(result, NotificationDeliveryResult):
                final_results.append(result)
            elif isinstance(result, BaseException):
                final_results.append(
                    NotificationDeliveryResult(
                        endpoint_id="unknown",
                        channel="unknown",
                        tenant_id=tenant_id,
                        success=False,
                        error=f"{type(result).__name__}: {_sanitize_error(result)}",
                    )
                )
        return final_results

    async def _deliver_endpoint(
        self,
        payload: AlertPayload,
        endpoint: NotificationEndpoint,
        policy: NotificationPolicy,
        timeout_seconds: float,
        idempotency_suffix: Optional[str] = None,
    ) -> NotificationDeliveryResult:
        if policy.min_severity is not None and not self._severity_allowed(
            payload.severity, policy.min_severity
        ):
            return NotificationDeliveryResult(
                endpoint_id=endpoint.endpoint_id,
                channel=endpoint.channel,
                tenant_id=endpoint.tenant_id,
                success=False,
                detail="severity below policy threshold",
                error=None,
                retry_count=0,
                idempotent=True,
            )

        key = (
            f"{payload.alert_id}:{endpoint.endpoint_id}:{idempotency_suffix}"
            if idempotency_suffix
            else f"notif:idem:{payload.alert_id}:{endpoint.endpoint_id}"
        )
        if not await self._idempotency_store.acquire(key, PLATFORM_IDEMPOTENCY_TTL_SECONDS):
            return None

        notifier = self._channel_map().get(endpoint.channel.lower())
        if notifier is None:
            result = NotificationDeliveryResult(
                endpoint_id=endpoint.endpoint_id,
                channel=endpoint.channel,
                tenant_id=endpoint.tenant_id,
                success=False,
                detail="no notifier registered for channel",
                error="no notifier registered for channel",
                retry_count=0,
                idempotent=False,
            )
            await self._delivery_recorder.record(result)
            return result

        retry_count = 0
        for attempt in range(1, (policy.max_retries or PLATFORM_MAX_RETRIES) + 2):
            try:
                result = await asyncio.wait_for(notifier.notify(payload), timeout=timeout_seconds)
                normalized = self._normalize_notifier_result(endpoint, result)
                normalized.retry_count = retry_count
                normalized.idempotent = True
                await self._delivery_recorder.record(normalized)
                return normalized
            except asyncio.TimeoutError:
                retry_count += 1
                if retry_count > (policy.max_retries or PLATFORM_MAX_RETRIES):
                    result = NotificationDeliveryResult(
                        endpoint_id=endpoint.endpoint_id,
                        channel=endpoint.channel,
                        tenant_id=endpoint.tenant_id,
                        success=False,
                        detail="dispatch timeout",
                        error="dispatch timeout",
                        retry_count=retry_count,
                        idempotent=False,
                    )
                    await self._delivery_recorder.record(result)
                    return result
                logger.warning(
                    "[NotificationDispatcher] channel=%s endpoint=%s timed out; retrying in %.2fs",
                    endpoint.channel,
                    endpoint.endpoint_id,
                    policy.retry_backoff_seconds or PLATFORM_RETRY_BACKOFF_SECONDS,
                )
                await asyncio.sleep(policy.retry_backoff_seconds or PLATFORM_RETRY_BACKOFF_SECONDS)
            except Exception as exc:  # pragma: no cover - defensive path
                retry_count += 1
                sanitized = _sanitize_error(exc)
                if retry_count > (policy.max_retries or PLATFORM_MAX_RETRIES):
                    result = NotificationDeliveryResult(
                        endpoint_id=endpoint.endpoint_id,
                        channel=endpoint.channel,
                        tenant_id=endpoint.tenant_id,
                        success=False,
                        detail=sanitized,
                        error=sanitized,
                        retry_count=retry_count,
                        idempotent=False,
                    )
                    await self._delivery_recorder.record(result)
                    return result
                logger.warning(
                    "[NotificationDispatcher] channel=%s endpoint=%s failed (%s); "
                    "retrying in %.2fs",
                    endpoint.channel,
                    endpoint.endpoint_id,
                    _mask_target(endpoint.target),
                    policy.retry_backoff_seconds or PLATFORM_RETRY_BACKOFF_SECONDS,
                )
                await asyncio.sleep(policy.retry_backoff_seconds or PLATFORM_RETRY_BACKOFF_SECONDS)

        result = NotificationDeliveryResult(
            endpoint_id=endpoint.endpoint_id,
            channel=endpoint.channel,
            tenant_id=endpoint.tenant_id,
            success=False,
            detail="delivery failed after retries",
            error="delivery failed after retries",
            retry_count=retry_count,
            idempotent=False,
        )
        await self._delivery_recorder.record(result)
        return result

    @staticmethod
    def _normalize_notifier_result(
        endpoint: NotificationEndpoint, raw: Any
    ) -> NotificationDeliveryResult:
        if isinstance(raw, NotificationDeliveryResult):
            return raw
        if isinstance(raw, dict):
            return NotificationDeliveryResult(
                endpoint_id=endpoint.endpoint_id,
                channel=endpoint.channel,
                tenant_id=endpoint.tenant_id,
                success=bool(raw.get("success", True)),
                detail=str(raw.get("detail") or raw.get("message") or "ok"),
                error=str(raw.get("error")) if raw.get("error") is not None else None,
                retry_count=int(raw.get("retry_count", 0)),
                idempotent=bool(raw.get("idempotent", False)),
            )
        return NotificationDeliveryResult(
            endpoint_id=endpoint.endpoint_id,
            channel=endpoint.channel,
            tenant_id=endpoint.tenant_id,
            success=True,
            detail=str(raw),
            error=None,
            retry_count=0,
            idempotent=False,
        )

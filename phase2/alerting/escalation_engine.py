"""
phase2/alerting/escalation_engine.py
=====================================
P2-M13  Escalation Engine — EscalationEngine
CAPSTONE-189

Determines Sev1-4 escalation level, target team, and notify method for
a non-duplicate, correlated alert firing, using a versioned YAML rules
file (config/escalation_rules.yaml) evaluated in order, first match
wins.

Design notes — deviations from the literal ticket text, and why
------------------------------------------------------------------
1. entity_criticality / timezone source. AnomalyResult and
   CorrelationResult -- the two dataclasses this module actually
   receives from upstream -- carry neither entity_criticality nor a
   timezone. Same situation P2-M12 hit with cloud_provider/region/op_id.
   Followed the same fix: a constructor-injected
   BaseEntityMetadataProvider (DIP/ISP), not fields smuggled onto
   AnomalyResult. Keeps this module importing only shared/types.py +
   shared/constants.py + stdlib + PyYAML.

2. Naming: policy_applied, not policy_name_applied. The AI Prompt Brief
   asks for "policy_name_applied" but the frozen EscalationResult
   (Directory Structure Section 5) already names this field
   policy_applied. Written to policy_applied -- see
   shared/types_ESCALATION_PATCH.py for the full rationale.

3. GroupType.REGIONAL_OUTAGE, not "REGIONAL". The brief's SeverityMapper
   spec says CRITICAL+REGIONAL=Sev1; the frozen GroupType enum (reused
   from P2-M12) has no REGIONAL member, only REGIONAL_OUTAGE.
   SeverityMapper matches on GroupType.REGIONAL_OUTAGE.

4. SeverityMapper vs. YAML rules -- how they compose. The ticket asks
   for BOTH a SeverityMapper (Severity x GroupType -> SevLevel) AND YAML
   rules whose actions include a severity_level. These are not
   redundant: SeverityMapper produces a *default* sev_level from the
   two signals that are always present (anomaly severity, group_type).
   The matched YAML rule can then override that default (e.g. force
   SEV1 for a rule that specifically wants to escalate a normally-SEV2
   situation) by specifying severity_level in its actions -- or leave
   SeverityMapper's value untouched by omitting severity_level from its
   actions (see default_fallback in escalation_rules.yaml). This mirrors
   the ticket's own two-source design (entity_criticality/business_hours
   feed the rule; anomaly severity/group_type feed the mapper) without
   forcing one to be computed from the other.

5. min_final_score condition. AnomalyResult carries final_score
   directly (shared/types.py), so RulesEngine reads it straight from
   the AnomalyResult passed to EscalationEngine.process() rather than
   re-deriving anything.

6. Suppression (Team Planner P2-M13, step 6: "if entity was Sev3 within
   last 4h from same group -> downgrade to Sev4 notification only").
   Implemented as a small in-memory SuppressionTracker keyed by
   incident_group_id ("same group" per the planner's own wording, not
   entity_id -- a group can contain many entities all worth suppressing
   together). Like P2-M11's dedup bucketing and P2-M12's pruning, this
   never calls datetime.now() internally; the caller supplies alert_ts
   explicitly, keeping the engine deterministic and unit-testable.

7. "Now" for business-hours evaluation. BusinessHoursChecker converts
   alert_ts (assumed UTC, per shared/types.py's datetime convention) to
   the entity's local IANA timezone rather than trusting any caller-
   supplied local time -- avoids the "store timezones as offsets"
   footgun the planner explicitly calls out.

Import constraint
------------------
Only shared/types.py, shared/constants.py, stdlib (yaml is a project
dependency per requirements.txt, same tier as networkx for P2-M12).
BaseEntityMetadataProvider is defined in this file (no other module
owns entity-metadata lookup yet) and is accepted via constructor
injection -- DIP, testable with a trivial in-memory fake.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import yaml

from shared.constants import (
    ESC_FALLBACK_POLICY_NAME,
    ESC_FALLBACK_TARGET_TEAM,
    ESC_QUIET_HOURS_END_HOUR,
    ESC_QUIET_HOURS_START_HOUR,
    ESC_RULES_CONFIG_PATH,
    ESC_SUPPRESSED_NOTIFY_METHOD,
    ESC_SUPPRESSED_SEV_LEVEL,
    ESC_SUPPRESSION_WINDOW_SEC,
)
from shared.types import EscalationResult, GroupType, NotifyMethod, Severity, SevLevel

logger_obj: logging.Logger = logging.getLogger(__name__)


# =========================================================================
# Entity metadata provider (DIP boundary -- see design note 1)
# =========================================================================


@dataclass
class EntityMetadata:
    """The subset of entity metadata EscalationEngine needs that isn't
    already present on AnomalyResult/CorrelationResult."""

    entity_id: str
    entity_criticality: str  # 'critical' | 'high' | 'medium' | 'low'
    timezone: str  # IANA string, e.g. 'America/New_York'


class BaseEntityMetadataProvider(ABC):
    """
    Read-only source of an entity's criticality tier and IANA timezone.
    Concrete implementations might wrap a CMDB lookup, a static YAML
    inventory, or an in-memory cache populated at ingestion time.
    EscalationEngine only depends on this abstraction (ISP/DIP), never a
    concrete store -- same pattern as P2-M12's
    BaseEntityAttributesProvider.
    """

    @abstractmethod
    def get_metadata(self, entity_id: str) -> EntityMetadata:
        """Return the entity's current metadata. Raises KeyError (or a
        subclass-defined exception) if the entity is unknown."""
        raise NotImplementedError


class StaticEntityMetadataProvider(BaseEntityMetadataProvider):
    """
    Trivial in-memory implementation backed by a dict, e.g. loaded from
    a static YAML inventory at startup. Good enough for the capstone
    demo per the planner's "static YAML on-call schedule first for the
    demo" guidance; a CMDB-backed provider can be swapped in later
    without touching EscalationEngine (DIP).
    """

    def __init__(self, entity_metadata_map: Dict[str, EntityMetadata]) -> None:
        self._entity_metadata_map = entity_metadata_map

    def get_metadata(self, entity_id: str) -> EntityMetadata:
        if entity_id not in self._entity_metadata_map:
            raise KeyError(
                f"[StaticEntityMetadataProvider] No metadata registered for "
                f"entity_id={entity_id!r}"
            )
        return self._entity_metadata_map[entity_id]


# =========================================================================
# BusinessHoursChecker
# =========================================================================


class BusinessHoursChecker:
    """
    Given an entity's IANA timezone and a UTC alert_ts, determines
    whether the alert fell inside "quiet hours"
    (ESC_QUIET_HOURS_START_HOUR..ESC_QUIET_HOURS_END_HOUR local, default
    00:00-07:00) and returns the inverse as is_business_hours.

    Deliberately stateless and takes alert_ts as an explicit parameter
    (design note 7) -- never reads the system clock.
    """

    def __init__(
        self,
        quiet_hours_start_hour: int = ESC_QUIET_HOURS_START_HOUR,
        quiet_hours_end_hour: int = ESC_QUIET_HOURS_END_HOUR,
    ) -> None:
        self._quiet_hours_start_hour = quiet_hours_start_hour
        self._quiet_hours_end_hour = quiet_hours_end_hour

    def is_business_hours(self, timezone: str, alert_ts: datetime) -> bool:
        """
        Parameters
        ----------
        timezone:
            IANA timezone string, e.g. 'America/New_York'. Never a raw
            UTC offset (planner's own explicit warning).
        alert_ts:
            UTC-aware (or naive-but-UTC, per shared/types.py convention)
            datetime for this firing.

        Returns
        -------
        bool
            True if the entity's local time is OUTSIDE the quiet-hours
            window (i.e. normal escalation applies); False if inside it
            (i.e. P2/P3 alerts should hold per the planner's rule --
            P1/SEV1 alerts always page regardless, enforced by the
            rules file rather than by this checker).
        """
        try:
            local_ts = alert_ts.astimezone(ZoneInfo(timezone))
        except Exception as exc:  # noqa: BLE001 -- unknown/malformed tz string
            logger_obj.warning(
                "[BusinessHoursChecker] Could not resolve timezone %r (%s) -- "
                "defaulting to business_hours=True (fail open, do not "
                "silently suppress a real alert).",
                timezone,
                exc,
            )
            return True

        local_hour = local_ts.hour
        in_quiet_hours = self._quiet_hours_start_hour <= local_hour < self._quiet_hours_end_hour
        return not in_quiet_hours


# =========================================================================
# SeverityMapper
# =========================================================================


class SeverityMapper:
    """
    Combines anomaly Severity (LOW/MEDIUM/HIGH/CRITICAL) with
    correlation GroupType (ISOLATED/CORRELATED/REGIONAL_OUTAGE) into a
    default SevLevel (SEV1-4), per the exact matrix in the ticket and
    the Directory Structure's own P2-M13 primer:

        CRITICAL + REGIONAL_OUTAGE -> SEV1
        CRITICAL + ISOLATED        -> SEV2
        HIGH     + CORRELATED      -> SEV2
        HIGH     + ISOLATED        -> SEV3
        (anything else)            -> SEV4

    Every combination not explicitly listed (CRITICAL+CORRELATED,
    HIGH+REGIONAL_OUTAGE, any MEDIUM/LOW combination, etc.) falls
    through to SEV4 -- this is the literal "else Sev4" from the ticket,
    not an oversight.
    """

    _MATRIX = {
        (Severity.CRITICAL, GroupType.REGIONAL_OUTAGE): SevLevel.SEV1,
        (Severity.CRITICAL, GroupType.ISOLATED): SevLevel.SEV2,
        (Severity.HIGH, GroupType.CORRELATED): SevLevel.SEV2,
        (Severity.HIGH, GroupType.ISOLATED): SevLevel.SEV3,
    }
    _DEFAULT = SevLevel.SEV4

    def classify(self, anomaly_severity: Severity, group_type: GroupType) -> SevLevel:
        return self._MATRIX.get((anomaly_severity, group_type), self._DEFAULT)


# =========================================================================
# RulesEngine
# =========================================================================


class RulesEngine:
    """
    Loads config/escalation_rules.yaml and evaluates its ordered rule
    list against a context dict, first match wins (Team Planner P2-M13,
    step 2, verbatim).
    """

    def __init__(self, rules_path: str = ESC_RULES_CONFIG_PATH) -> None:
        self._rules_path = rules_path
        self._rules = self._load_rules(rules_path)

    def _load_rules(self, rules_path: str) -> list:
        path = Path(rules_path)
        if not path.exists():
            raise FileNotFoundError(
                f"[RulesEngine] escalation_rules.yaml not found at "
                f"{rules_path!r} -- this file must be version-controlled "
                f"in the repo (Team Planner P2-M13 integration note)."
            )
        with path.open("r", encoding="utf-8") as fh:
            parsed = yaml.safe_load(fh) or {}
        rules = parsed.get("rules", [])
        if not rules:
            raise ValueError(
                f"[RulesEngine] {rules_path!r} contains no rules -- at "
                f"minimum a catch-all default rule with empty conditions "
                f"is required so every alert resolves to a policy."
            )
        return rules

    def evaluate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns the FIRST matching rule dict (with 'name', 'conditions',
        'actions' keys) from the loaded rules list. Raises RuntimeError
        if nothing matches -- should never happen if the YAML file ends
        with a catch-all rule (conditions: {}), which always matches.
        """
        for rule in self._rules:
            if self._conditions_match(rule.get("conditions", {}) or {}, context):
                return rule
        raise RuntimeError(
            "[RulesEngine] No rule matched and no catch-all rule was "
            "present in escalation_rules.yaml -- add a final rule with "
            "empty conditions."
        )

    def _conditions_match(self, conditions: Dict[str, Any], context: Dict[str, Any]) -> bool:
        if "entity_criticality" in conditions:
            expected = str(conditions["entity_criticality"]).lower()
            actual = str(context.get("entity_criticality", "")).lower()
            if expected != actual:
                return False

        if "min_final_score" in conditions:
            if context.get("final_score", 0.0) < conditions["min_final_score"]:
                return False

        if "group_type" in conditions:
            expected_group = str(conditions["group_type"])
            actual_group = context.get("group_type")
            actual_group_value = (
                actual_group.value if isinstance(actual_group, GroupType) else str(actual_group)
            )
            if expected_group != actual_group_value:
                return False

        if "business_hours" in conditions:
            if bool(conditions["business_hours"]) != bool(context.get("business_hours")):
                return False

        return True


# =========================================================================
# SuppressionTracker (design note 6)
# =========================================================================


class SuppressionTracker:
    """
    Tracks the most recent SEV3 escalation per incident_group_id. If a
    NEW SEV3 escalation arrives for a group that already had one within
    ESC_SUPPRESSION_WINDOW_SEC, this one is downgraded to SEV4,
    notify-only (Team Planner P2-M13, step 6).

    In-memory dict, keyed by incident_group_id, never touches a system
    clock -- alert_ts is always caller-supplied (same pattern as P2-M11
    dedup buckets / P2-M12 pruning).
    """

    def __init__(self, suppression_window_sec: int = ESC_SUPPRESSION_WINDOW_SEC) -> None:
        self._suppression_window_sec = suppression_window_sec
        self._last_sev3_ts: Dict[str, datetime] = {}

    def should_suppress(
        self, incident_group_id: str, sev_level: SevLevel, alert_ts: datetime
    ) -> bool:
        """
        Call AFTER computing sev_level (SeverityMapper + rule override)
        but BEFORE building the final EscalationResult. Returns True if
        this firing should be downgraded per the suppression rule, and
        records this firing's timestamp for the NEXT check when
        sev_level == SEV3 (whether or not this one was itself
        suppressed -- each SEV3 firing refreshes the window).
        """
        if sev_level != SevLevel.SEV3:
            return False

        previous_ts = self._last_sev3_ts.get(incident_group_id)
        should_suppress = (
            previous_ts is not None
            and (alert_ts - previous_ts).total_seconds() <= self._suppression_window_sec
        )
        self._last_sev3_ts[incident_group_id] = alert_ts
        return should_suppress

    def clear_group(self, incident_group_id: str) -> None:
        """Forget suppression history for a closed incident group."""
        self._last_sev3_ts.pop(incident_group_id, None)


# =========================================================================
# EscalationEngine (Controller, GRASP)
# =========================================================================


class EscalationEngine:
    """
    Controller orchestrating: compute default sev_level (SeverityMapper)
    -> check business hours -> evaluate YAML rules (first match wins) ->
    apply suppression -> assemble EscalationResult.

    Parameters
    ----------
    entity_metadata_provider:
        Supplies (entity_criticality, timezone) per entity_id -- see
        BaseEntityMetadataProvider docstring and design note 1.
    rules_path:
        Path to the versioned escalation_rules.yaml. Defaults to
        ESC_RULES_CONFIG_PATH.
    """

    def __init__(
        self,
        entity_metadata_provider: BaseEntityMetadataProvider,
        rules_path: str = ESC_RULES_CONFIG_PATH,
        severity_mapper: Optional[SeverityMapper] = None,
        business_hours_checker: Optional[BusinessHoursChecker] = None,
        rules_engine: Optional[RulesEngine] = None,
        suppression_tracker: Optional[SuppressionTracker] = None,
    ) -> None:
        self._entity_metadata_provider = entity_metadata_provider
        self._severity_mapper = severity_mapper if severity_mapper is not None else SeverityMapper()
        self._business_hours_checker = (
            business_hours_checker if business_hours_checker is not None else BusinessHoursChecker()
        )
        self._rules_engine = rules_engine if rules_engine is not None else RulesEngine(rules_path)
        self._suppression_tracker = (
            suppression_tracker if suppression_tracker is not None else SuppressionTracker()
        )

    def process(
        self,
        entity_id: str,
        final_score: float,
        anomaly_severity: Severity,
        group_type: GroupType,
        incident_group_id: str,
        alert_ts: datetime,
    ) -> EscalationResult:
        """
        Parameters
        ----------
        entity_id:
            AnomalyResult.entity_id / CorrelationResult.entity_id.
        final_score:
            AnomalyResult.final_score -- feeds the rules' min_final_score
            condition.
        anomaly_severity:
            AnomalyResult.severity -- feeds SeverityMapper.
        group_type:
            CorrelationResult.group_type -- feeds SeverityMapper and the
            rules' group_type condition.
        incident_group_id:
            CorrelationResult.incident_group_id -- the suppression key
            ("same group", Team Planner step 6).
        alert_ts:
            This firing's own timestamp (typically AnomalyResult.batch_ts
            or CorrelationResult's originating alert_ts). Used as "now"
            for both business-hours evaluation and suppression, matching
            P2-M11/P2-M12's no-internal-clock convention.

        Returns
        -------
        EscalationResult
        """
        metadata = self._entity_metadata_provider.get_metadata(entity_id)
        if metadata.entity_id != entity_id:
            raise ValueError(
                f"[EscalationEngine] BaseEntityMetadataProvider returned "
                f"metadata for '{metadata.entity_id}' when asked for "
                f"'{entity_id}' -- provider implementation bug."
            )

        default_sev_level = self._severity_mapper.classify(anomaly_severity, group_type)
        is_business_hours = self._business_hours_checker.is_business_hours(
            metadata.timezone, alert_ts
        )

        context = {
            "entity_criticality": metadata.entity_criticality,
            "final_score": final_score,
            "group_type": group_type,
            "business_hours": is_business_hours,
        }

        try:
            matched_rule = self._rules_engine.evaluate(context)
            policy_applied = matched_rule["name"]
            actions = matched_rule.get("actions", {})
            sev_level = (
                SevLevel(actions["severity_level"])
                if "severity_level" in actions
                else default_sev_level
            )
            target_team = actions.get("target_team", ESC_FALLBACK_TARGET_TEAM)
            notify_method = NotifyMethod(actions.get("notify_method", NotifyMethod.SLACK.value))
        except RuntimeError:
            logger_obj.error(
                "[EscalationEngine] No YAML rule matched for entity_id=%s "
                "-- falling back to SeverityMapper's default and "
                "ESC_FALLBACK_* constants.",
                entity_id,
            )
            policy_applied = ESC_FALLBACK_POLICY_NAME
            sev_level = default_sev_level
            target_team = ESC_FALLBACK_TARGET_TEAM
            notify_method = NotifyMethod.SLACK

        if self._suppression_tracker.should_suppress(incident_group_id, sev_level, alert_ts):
            logger_obj.info(
                "[EscalationEngine] Suppressing repeat SEV3 for "
                "incident_group_id=%s (entity_id=%s) within the "
                "suppression window -- downgrading to %s / %s.",
                incident_group_id,
                entity_id,
                ESC_SUPPRESSED_SEV_LEVEL,
                ESC_SUPPRESSED_NOTIFY_METHOD,
            )
            sev_level = SevLevel(ESC_SUPPRESSED_SEV_LEVEL)
            notify_method = NotifyMethod(ESC_SUPPRESSED_NOTIFY_METHOD)
            policy_applied = f"{policy_applied}+sev3_suppression"

        return EscalationResult(
            entity_id=entity_id,
            sev_level=sev_level,
            target_team=target_team,
            notify_method=notify_method,
            policy_applied=policy_applied,
            business_hours_flag=is_business_hours,
        )

    def clear_suppression_memory(self, incident_group_id: str) -> None:
        self._suppression_tracker.clear_group(incident_group_id)

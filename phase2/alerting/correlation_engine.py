"""
phase2/alerting/correlation_engine.py
==========================================
P2-M12  Correlation Engine — CorrelationEngine
CAPSTONE-189

Groups related, non-duplicate alerts into correlated incident groups
using an entity-attribute graph, and classifies each group as
ISOLATED / CORRELATED / REGIONAL_OUTAGE.

Design notes — deviations from the literal ticket text, and why
------------------------------------------------------------------
1. group_type values. The Team Planner's prose (P2-M12 section) talks
   about "single/regional/global" group types and a ">2 members ->
   grouped, else standalone_group" ID rule. The FROZEN shared/types.py
   contract (Directory Structure Section 5, explicitly marked unchanged
   by the redesign) defines GroupType as exactly
   ISOLATED / CORRELATED / REGIONAL_OUTAGE, and the Directory Structure's
   own P2-M12 primer confirms the rule actually used:
   "REGIONAL_OUTAGE: group_size>10 AND same region." This file follows
   the frozen enum and that primer, not the older planner prose. Mapping
   used: community size <= 1 -> ISOLATED; community size > 10 AND every
   member shares the same region -> REGIONAL_OUTAGE; anything else with
   size >= 2 -> CORRELATED. The old ">2" standalone-vs-grouped threshold
   doesn't survive contact with a 3-value enum that has no "standalone
   but still size 2" state, so it's dropped in favor of the primer's own
   explicit rule.

2. Entity attributes input. AnomalyResult and DedupResult -- the two
   dataclasses this module actually receives -- carry no
   cloud_provider / region / op_id (see shared_types_APPEND_ONLY's
   EntityAttributesData docstring for the full explanation). Those are
   supplied here via a constructor-injected BaseEntityAttributesProvider
   rather than assumed to be smuggled onto AnomalyResult/DedupResult.
   This keeps CorrelationEngine importing only from shared/types.py +
   shared/constants.py, per the project's own Low Coupling / DIP rule
   (Directory Structure Section 3/4) -- the provider is an abstraction,
   not a concrete store.

3. related_ids semantics. shared/types.py's CorrelationResult field is
   named related_ids: List[str], and the Directory Structure's own
   integration note says "Related incident IDs are included in P2-M14
   alert payload as 'related_incidents' field" -- i.e. downstream wants
   INCIDENT ids, not entity ids, so alerts can be cross-linked by
   incident. This module therefore tracks each node's most recent
   canonical_incident_id (from DedupResult, via set_incident_id()) and
   populates related_ids with OTHER members' incident ids -- not their
   entity ids. A node with no incident id on record yet (e.g. graph
   pruning edge cases) is simply omitted from related_ids rather than
   guessed at.

4. Directed graph + community detection. The ticket specifies a
   directed graph for AlertGraph but Louvain community detection is
   inherently an undirected-graph algorithm. Edges are added
   symmetrically (u->v and v->u) whenever the edge condition holds, so
   the DiGraph is always reciprocal by construction; community
   detection runs against an undirected projection built fresh each call
   (cheap at the pruned graph sizes this module is designed for -- see
   watch-out below on pruning).

5. Louvain availability. nx.community.louvain_communities requires a
   recent NetworkX (>=2.8). If it's unavailable in the team's pinned
   version, this falls back to nx.connected_components on the same
   undirected projection -- coarser (no sub-community splitting within
   a connected component) but a documented, ticket-sanctioned fallback
   ("Louvain or label propagation... connected_components()").

6. "Now" for time-windowing and pruning. Like P2-M11's dedup window
   bucketing, this module never calls time.time()/datetime.now()
   internally -- the caller supplies alert_ts explicitly (typically the
   AnomalyResult's own batch_ts). This keeps the engine's time-windowed
   behavior deterministic and unit-testable without monkeypatching the
   clock, matching the project's existing pattern.

Import constraint
-------------------
Only shared/types.py, shared/constants.py, stdlib, and networkx.
BaseEntityAttributesProvider is defined in this file (no other module
owns entity-attribute lookup yet) and is accepted via constructor
injection -- DIP, testable with a trivial in-memory fake.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Set

import networkx as nx

from shared.constants import (
    CORR_EDGE_TIME_WINDOW_SEC,
    CORR_LOUVAIN_RANDOM_STATE,
    CORR_MIN_SHARED_ATTRS,
    CORR_PRUNE_INACTIVE_SEC,
    CORR_REGIONAL_GROUP_SIZE_THRESHOLD,
)
from shared.types import CorrelationResult, EntityAttributesData, GroupType

logger_obj: logging.Logger = logging.getLogger(__name__)

_SHARED_ATTR_KEYS = ("cloud_provider", "region", "op_id")


class BaseEntityAttributesProvider(ABC):
    """
    Read-only source of an entity's current identifying attributes.
    Concrete implementations might wrap a small in-memory cache
    populated from RawRecord fields as events are ingested, or a
    lookup table maintained alongside EntityStore. CorrelationEngine
    only depends on this abstraction (ISP/DIP), never a concrete store.
    """

    @abstractmethod
    def get_attributes(self, entity_id: str) -> EntityAttributesData:
        """Return the entity's current attributes. Raises KeyError (or a
        subclass-defined exception) if the entity is unknown."""
        raise NotImplementedError


class AlertGraph:
    """
    Owns the entity-attribute graph itself: node/edge maintenance,
    time-windowed pruning, and community detection. Kept separate from
    CorrelationEngine (which owns the higher-level "what does this alert
    mean" orchestration) per SRP -- CorrelationEngine is a Controller,
    AlertGraph is the Information Expert that actually holds the graph.
    """

    def __init__(
        self,
        edge_time_window_sec: int = CORR_EDGE_TIME_WINDOW_SEC,
        prune_inactive_sec: int = CORR_PRUNE_INACTIVE_SEC,
        min_shared_attrs: int = CORR_MIN_SHARED_ATTRS,
        louvain_random_state: int = CORR_LOUVAIN_RANDOM_STATE,
    ) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._edge_time_window_sec = edge_time_window_sec
        self._prune_inactive_sec = prune_inactive_sec
        self._min_shared_attrs = min_shared_attrs
        self._louvain_random_state = louvain_random_state

    # ── Mutation ─────────────────────────────────────────────────────────────

    def prune_inactive(self, reference_ts: datetime) -> None:
        """Remove nodes whose last_alert_ts is older than
        prune_inactive_sec relative to reference_ts. Call BEFORE adding
        the current alert so the current node is never pruned by its
        own arrival."""
        stale_node_ids = [
            node_id
            for node_id, node_data in self._graph.nodes(data=True)
            if node_data.get("last_alert_ts") is not None
            and (reference_ts - node_data["last_alert_ts"]).total_seconds()
            > self._prune_inactive_sec
        ]
        self._graph.remove_nodes_from(stale_node_ids)

    def add_alert(self, attrs: EntityAttributesData, alert_ts: datetime) -> None:
        """Add/update the node for attrs.entity_id and draw edges to
        every OTHER currently-present node that shares >= min_shared_attrs
        attributes AND was itself last-alerted within
        edge_time_window_sec of alert_ts."""
        entity_id = attrs.entity_id
        self._graph.add_node(
            entity_id,
            cloud_provider=attrs.cloud_provider,
            region=attrs.region,
            op_id=attrs.op_id,
            last_alert_ts=alert_ts,
        )
        for other_id in list(self._graph.nodes):
            if other_id == entity_id:
                continue
            other_ts = self._graph.nodes[other_id].get("last_alert_ts")
            if other_ts is None:
                continue
            delta_seconds = abs((alert_ts - other_ts).total_seconds())
            if delta_seconds > self._edge_time_window_sec:
                continue
            if self._count_shared_attrs(entity_id, other_id) < self._min_shared_attrs:
                continue
            self._graph.add_edge(entity_id, other_id)
            self._graph.add_edge(other_id, entity_id)

    def set_incident_id(self, entity_id: str, incident_id: str) -> None:
        """Record the entity's current canonical_incident_id (from
        DedupResult) on its node, so other communities can report it
        back as a related incident."""
        if entity_id in self._graph:
            self._graph.nodes[entity_id]["incident_id"] = incident_id

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_incident_id(self, entity_id: str) -> Optional[str]:
        if entity_id in self._graph:
            return self._graph.nodes[entity_id].get("incident_id")
        return None

    def get_region(self, entity_id: str) -> Optional[str]:
        if entity_id in self._graph:
            return self._graph.nodes[entity_id].get("region")
        return None

    def _count_shared_attrs(self, a_id: str, b_id: str) -> int:
        a_data = self._graph.nodes[a_id]
        b_data = self._graph.nodes[b_id]
        return sum(
            1
            for key in _SHARED_ATTR_KEYS
            if a_data.get(key) is not None and a_data.get(key) == b_data.get(key)
        )

    def _undirected_projection(self) -> nx.Graph:
        undirected_graph = nx.Graph()
        undirected_graph.add_nodes_from(self._graph.nodes(data=True))
        undirected_graph.add_edges_from(self._graph.edges())
        return undirected_graph

    def detect_communities(self) -> List[Set[str]]:
        """Run Louvain (preferred) or connected_components (fallback,
        see module docstring note 5) over the current undirected
        projection. Returns a list of node-id sets."""
        undirected_graph = self._undirected_projection()
        if undirected_graph.number_of_nodes() == 0:
            return []
        try:
            communities = nx.community.louvain_communities(
                undirected_graph, seed=self._louvain_random_state
            )
            return [set(community) for community in communities]
        except (AttributeError, ImportError):
            logger_obj.warning(
                "[AlertGraph] nx.community.louvain_communities unavailable "
                "(NetworkX version too old) -- falling back to "
                "connected_components. Sub-community splitting within a "
                "connected component will not occur."
            )
            return [set(component) for component in nx.connected_components(undirected_graph)]

    def find_community(self, entity_id: str) -> Set[str]:
        """The set of node ids (including entity_id itself) in
        entity_id's current community. An entity with no edges returns
        a singleton set containing only itself."""
        for community in self.detect_communities():
            if entity_id in community:
                return community
        return {entity_id}

    @property
    def n_nodes(self) -> int:
        return self._graph.number_of_nodes()


class CorrelationEngine:
    """
    Controller (GRASP) orchestrating: prune -> add alert -> detect
    communities -> classify -> assemble CorrelationResult. Depends only
    on AlertGraph (owned internally -- this module IS AlertGraph's
    primary owner, unlike detection-engine classes that take stores via
    constructor injection) and the injected BaseEntityAttributesProvider.

    Parameters
    ----------
    entity_attributes_provider:
        Supplies (cloud_provider, region, op_id) per entity_id -- see
        BaseEntityAttributesProvider docstring and design note 2 above.
    regional_group_size_threshold:
        group_size strictly greater than this, combined with a single
        shared region across the whole community, triggers
        REGIONAL_OUTAGE. Defaults to CORR_REGIONAL_GROUP_SIZE_THRESHOLD
        (10, i.e. 11+ members).
    """

    def __init__(
        self,
        entity_attributes_provider: BaseEntityAttributesProvider,
        regional_group_size_threshold: int = CORR_REGIONAL_GROUP_SIZE_THRESHOLD,
        alert_graph: Optional[AlertGraph] = None,
    ) -> None:
        self._entity_attributes_provider = entity_attributes_provider
        self._regional_group_size_threshold = regional_group_size_threshold
        self._graph = alert_graph if alert_graph is not None else AlertGraph()

    # ── Public API ───────────────────────────────────────────────────────────

    def process(
        self,
        entity_id: str,
        canonical_incident_id: str,
        alert_ts: datetime,
    ) -> CorrelationResult:
        """
        Process one non-duplicate alert firing and return its
        CorrelationResult.

        Parameters
        ----------
        entity_id:
            The entity that just fired (AnomalyResult.entity_id /
            DedupResult.entity_id).
        canonical_incident_id:
            DedupResult.canonical_incident_id for this firing -- recorded
            on the graph node so other entities' related_ids can
            reference it.
        alert_ts:
            The firing's own timestamp (typically AnomalyResult.batch_ts).
            Used as "now" for both pruning and the edge time-window check
            -- see module docstring note 6.

        Returns
        -------
        CorrelationResult
        """
        attrs = self._entity_attributes_provider.get_attributes(entity_id)
        if attrs.entity_id != entity_id:
            raise ValueError(
                f"[CorrelationEngine] BaseEntityAttributesProvider returned "
                f"attributes for '{attrs.entity_id}' when asked for "
                f"'{entity_id}' -- provider implementation bug."
            )

        self._graph.prune_inactive(alert_ts)
        self._graph.add_alert(attrs, alert_ts)
        self._graph.set_incident_id(entity_id, canonical_incident_id)

        community = self._graph.find_community(entity_id)
        group_size = len(community)
        group_type = self._classify_group(community)
        incident_group_id = self._build_incident_group_id(entity_id, community, group_type)
        related_ids = self._collect_related_incident_ids(entity_id, community)

        return CorrelationResult(
            entity_id=entity_id,
            incident_group_id=incident_group_id,
            related_ids=related_ids,
            group_size=group_size,
            group_type=group_type,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _classify_group(self, community: Set[str]) -> GroupType:
        if len(community) <= 1:
            return GroupType.ISOLATED
        if len(community) > self._regional_group_size_threshold and self._all_same_region(
            community
        ):
            return GroupType.REGIONAL_OUTAGE
        return GroupType.CORRELATED

    def _all_same_region(self, community: Set[str]) -> bool:
        regions = {self._graph.get_region(node_id) for node_id in community}
        return len(regions) == 1 and None not in regions

    def _build_incident_group_id(
        self, entity_id: str, community: Set[str], group_type: GroupType
    ) -> str:
        if group_type == GroupType.ISOLATED:
            return f"standalone_{entity_id}"
        members_key = ",".join(sorted(community))
        digest = hashlib.sha256(members_key.encode("utf-8")).hexdigest()[:12]
        return f"grp_{digest}"

    def _collect_related_incident_ids(
        self, entity_id: str, community: Set[str]
    ) -> List[str]:
        other_member_ids = sorted(node_id for node_id in community if node_id != entity_id)
        related_incident_ids = []
        for other_id in other_member_ids:
            incident_id = self._graph.get_incident_id(other_id)
            if incident_id is not None:
                related_incident_ids.append(incident_id)
        return related_incident_ids

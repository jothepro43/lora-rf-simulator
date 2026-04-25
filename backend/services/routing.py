"""Multi-objective network-topology pathfinding.

Builds an undirected graph from analyzed ``NetworkLink`` rows and solves
shortest-path queries with several user-selectable objectives:

- ``hops``                 BFS – fewest intermediate nodes.
- ``lowest_total_loss``    Dijkstra – minimum sum of ``path_loss_db``.
- ``best_bottleneck_margin`` Widest-path – maximize the worst-hop link
  margin (good for "this is the weakest hop in the chain" planning).

The graph is built from the cached metrics on ``network_links``, so
``/api/links/analyze`` should be called before requesting a path. Edges
with ``status`` in :data:`UNUSABLE_STATUSES` are excluded by default,
which keeps blocked or never-analyzed edges out of the search space.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

Objective = Literal["hops", "lowest_total_loss", "best_bottleneck_margin"]

# Statuses that should NOT be considered traversable for routing.
UNUSABLE_STATUSES = frozenset({"blocked", "unknown"})


@dataclass(frozen=True)
class EdgeView:
    """Lightweight view of a NetworkLink for the routing graph."""

    link_id: int
    node_a: int
    node_b: int
    distance_km: float
    path_loss_db: float
    link_margin_db: float
    status: str
    is_los: bool


@dataclass(frozen=True)
class NodeView:
    """Lightweight view of a Node for routing constraints."""

    id: int
    name: str
    role: str


@dataclass(frozen=True)
class PathSolution:
    """Result of a successful pathfinding query."""

    objective: Objective
    nodes: list[int]
    links: list[int]
    hops: int
    total_path_loss_db: float
    total_distance_km: float
    end_to_end_margin_db: float       # min over hop margins
    bottleneck_link_id: Optional[int]


def _filter_edges(
    edges: Iterable[EdgeView],
    *,
    allow_unanalyzed: bool,
    min_margin_db: Optional[float],
) -> list[EdgeView]:
    out: list[EdgeView] = []
    for e in edges:
        if e.status in UNUSABLE_STATUSES and not allow_unanalyzed:
            continue
        if min_margin_db is not None and e.link_margin_db < min_margin_db:
            continue
        out.append(e)
    return out


def _filter_relay_nodes(
    nodes: Iterable[NodeView],
    allowed_relay_roles: Optional[Iterable[str]],
    source_id: int,
    dest_id: int,
) -> set[int]:
    """Return the set of node IDs that may appear in the path.

    Source and destination are always included regardless of role.
    """
    if allowed_relay_roles is None:
        return {n.id for n in nodes}
    allowed = {r.upper() for r in allowed_relay_roles}
    return {
        n.id for n in nodes
        if n.role.upper() in allowed or n.id == source_id or n.id == dest_id
    }


def _build_adjacency(
    edges: Iterable[EdgeView],
    permitted: set[int],
) -> dict[int, list[tuple[int, EdgeView]]]:
    adj: dict[int, list[tuple[int, EdgeView]]] = {}
    for e in edges:
        if e.node_a not in permitted or e.node_b not in permitted:
            continue
        adj.setdefault(e.node_a, []).append((e.node_b, e))
        adj.setdefault(e.node_b, []).append((e.node_a, e))
    return adj


def _bfs(
    adj: dict[int, list[tuple[int, EdgeView]]],
    source: int,
    dest: int,
    max_hops: Optional[int],
) -> Optional[tuple[list[int], list[EdgeView]]]:
    if source == dest:
        return [source], []
    visited = {source}
    queue: deque[tuple[int, list[int], list[EdgeView]]] = deque([(source, [source], [])])
    while queue:
        node, path_nodes, path_edges = queue.popleft()
        if max_hops is not None and len(path_edges) >= max_hops:
            continue
        for nxt, edge in adj.get(node, []):
            if nxt in visited:
                continue
            new_nodes = path_nodes + [nxt]
            new_edges = path_edges + [edge]
            if nxt == dest:
                return new_nodes, new_edges
            visited.add(nxt)
            queue.append((nxt, new_nodes, new_edges))
    return None


def _dijkstra(
    adj: dict[int, list[tuple[int, EdgeView]]],
    source: int,
    dest: int,
    weight_fn,
    max_hops: Optional[int],
) -> Optional[tuple[list[int], list[EdgeView]]]:
    """Standard Dijkstra returning (node_ids, edge_views)."""
    if source == dest:
        return [source], []
    best: dict[int, float] = {source: 0.0}
    parent: dict[int, tuple[int, EdgeView]] = {}
    pq: list[tuple[float, int, int]] = [(0.0, 0, source)]  # (cost, hops, node)
    while pq:
        cost, hops, node = heapq.heappop(pq)
        if cost > best.get(node, float("inf")):
            continue
        if node == dest:
            break
        if max_hops is not None and hops >= max_hops:
            continue
        for nxt, edge in adj.get(node, []):
            new_cost = cost + weight_fn(edge)
            if new_cost < best.get(nxt, float("inf")):
                best[nxt] = new_cost
                parent[nxt] = (node, edge)
                heapq.heappush(pq, (new_cost, hops + 1, nxt))

    if dest not in best:
        return None

    nodes_rev: list[int] = [dest]
    edges_rev: list[EdgeView] = []
    cur = dest
    while cur != source:
        prev, edge = parent[cur]
        edges_rev.append(edge)
        nodes_rev.append(prev)
        cur = prev
    return list(reversed(nodes_rev)), list(reversed(edges_rev))


def _widest_path(
    adj: dict[int, list[tuple[int, EdgeView]]],
    source: int,
    dest: int,
    max_hops: Optional[int],
) -> Optional[tuple[list[int], list[EdgeView]]]:
    """Maximize the minimum link_margin_db along the path.

    Implemented with a max-heap on the bottleneck score.
    """
    if source == dest:
        return [source], []
    best: dict[int, float] = {source: float("inf")}
    parent: dict[int, tuple[int, EdgeView]] = {}
    # Use negative bottleneck for max-heap behaviour.
    pq: list[tuple[float, int, int]] = [(-float("inf"), 0, source)]
    while pq:
        neg_bottleneck, hops, node = heapq.heappop(pq)
        bottleneck = -neg_bottleneck
        if bottleneck < best.get(node, -float("inf")):
            # Stale entry.
            continue
        if node == dest:
            break
        if max_hops is not None and hops >= max_hops:
            continue
        for nxt, edge in adj.get(node, []):
            new_bottleneck = min(bottleneck, edge.link_margin_db)
            if new_bottleneck > best.get(nxt, -float("inf")):
                best[nxt] = new_bottleneck
                parent[nxt] = (node, edge)
                heapq.heappush(pq, (-new_bottleneck, hops + 1, nxt))

    if dest not in best:
        return None

    nodes_rev: list[int] = [dest]
    edges_rev: list[EdgeView] = []
    cur = dest
    while cur != source:
        prev, edge = parent[cur]
        edges_rev.append(edge)
        nodes_rev.append(prev)
        cur = prev
    return list(reversed(nodes_rev)), list(reversed(edges_rev))


def find_path(
    nodes: Iterable[NodeView],
    edges: Iterable[EdgeView],
    *,
    source_id: int,
    dest_id: int,
    objective: Objective = "hops",
    max_hops: Optional[int] = None,
    min_margin_db: Optional[float] = None,
    allow_unanalyzed: bool = False,
    allowed_relay_roles: Optional[Iterable[str]] = None,
) -> Optional[PathSolution]:
    """Solve the shortest-path query with the chosen objective.

    Returns ``None`` if no usable path exists.
    """
    if source_id == dest_id:
        raise ValueError("source_id and dest_id must differ")

    nodes_list = list(nodes)
    if not any(n.id == source_id for n in nodes_list):
        raise ValueError(f"Unknown source node {source_id}")
    if not any(n.id == dest_id for n in nodes_list):
        raise ValueError(f"Unknown dest node {dest_id}")

    permitted = _filter_relay_nodes(
        nodes_list, allowed_relay_roles, source_id, dest_id
    )
    edges_filtered = _filter_edges(
        edges, allow_unanalyzed=allow_unanalyzed, min_margin_db=min_margin_db
    )
    adj = _build_adjacency(edges_filtered, permitted)

    if objective == "hops":
        result = _bfs(adj, source_id, dest_id, max_hops)
    elif objective == "lowest_total_loss":
        result = _dijkstra(
            adj, source_id, dest_id,
            weight_fn=lambda e: max(0.0, e.path_loss_db),
            max_hops=max_hops,
        )
    elif objective == "best_bottleneck_margin":
        result = _widest_path(adj, source_id, dest_id, max_hops)
    else:
        raise ValueError(f"Unknown objective '{objective}'")

    if result is None:
        return None

    node_ids, path_edges = result
    if not path_edges:
        # source == dest already handled above; shouldn't get here
        return None

    total_loss = round(sum(e.path_loss_db for e in path_edges), 2)
    total_dist = round(sum(e.distance_km for e in path_edges), 2)
    margins = [e.link_margin_db for e in path_edges]
    end_to_end_margin = round(min(margins), 2) if margins else 0.0
    bottleneck_idx = margins.index(min(margins)) if margins else None
    bottleneck_link_id = (
        path_edges[bottleneck_idx].link_id if bottleneck_idx is not None else None
    )

    return PathSolution(
        objective=objective,
        nodes=node_ids,
        links=[e.link_id for e in path_edges],
        hops=len(path_edges),
        total_path_loss_db=total_loss,
        total_distance_km=total_dist,
        end_to_end_margin_db=end_to_end_margin,
        bottleneck_link_id=bottleneck_link_id,
    )

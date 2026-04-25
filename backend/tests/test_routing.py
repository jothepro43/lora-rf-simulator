"""Tests for the multi-objective routing engine."""

import pytest

from services.routing import EdgeView, NodeView, find_path


def _node(id_: int, name: str = "", role: str = "CLIENT") -> NodeView:
    return NodeView(id=id_, name=name or f"n{id_}", role=role)


def _edge(
    link_id: int,
    a: int,
    b: int,
    *,
    distance_km: float = 5.0,
    path_loss_db: float = 100.0,
    margin_db: float = 10.0,
    status: str = "viable",
    is_los: bool = True,
) -> EdgeView:
    return EdgeView(
        link_id=link_id,
        node_a=a,
        node_b=b,
        distance_km=distance_km,
        path_loss_db=path_loss_db,
        link_margin_db=margin_db,
        status=status,
        is_los=is_los,
    )


def _diamond_graph():
    """A→B is direct but blocked. A→C→B and A→D→B are both viable.

    A→C→B has fewer total loss; A→D→B has higher bottleneck margin.
    """
    nodes = [_node(1, "A"), _node(2, "B"), _node(3, "C"), _node(4, "D")]
    edges = [
        _edge(10, 1, 2, status="blocked", margin_db=-10, path_loss_db=200),
        _edge(11, 1, 3, path_loss_db=110, margin_db=15),
        _edge(12, 3, 2, path_loss_db=110, margin_db=20),
        _edge(13, 1, 4, path_loss_db=140, margin_db=25),
        _edge(14, 4, 2, path_loss_db=140, margin_db=30),
    ]
    return nodes, edges


def test_hops_picks_two_hop_when_direct_blocked():
    nodes, edges = _diamond_graph()
    sol = find_path(nodes, edges, source_id=1, dest_id=2, objective="hops")
    assert sol is not None
    assert sol.hops == 2
    assert sol.nodes[0] == 1 and sol.nodes[-1] == 2


def test_lowest_total_loss_picks_minimum_loss_path():
    nodes, edges = _diamond_graph()
    sol = find_path(
        nodes, edges, source_id=1, dest_id=2, objective="lowest_total_loss"
    )
    assert sol is not None
    # A->C->B sums to 220 dB, beats A->D->B at 280 dB.
    assert sol.total_path_loss_db == pytest.approx(220.0, abs=0.1)
    assert sol.nodes == [1, 3, 2]


def test_widest_path_maximizes_bottleneck_margin():
    nodes, edges = _diamond_graph()
    sol = find_path(
        nodes, edges, source_id=1, dest_id=2, objective="best_bottleneck_margin"
    )
    assert sol is not None
    # A->D->B bottleneck = min(25, 30) = 25, beats A->C->B bottleneck = 15.
    assert sol.end_to_end_margin_db == pytest.approx(25.0)
    assert sol.nodes == [1, 4, 2]


def test_blocked_edges_are_excluded_by_default():
    """Single direct edge that is blocked → no path."""
    nodes = [_node(1, "A"), _node(2, "B")]
    edges = [_edge(10, 1, 2, status="blocked")]
    assert find_path(nodes, edges, source_id=1, dest_id=2) is None


def test_allow_unanalyzed_lets_us_use_blocked_edges():
    nodes = [_node(1, "A"), _node(2, "B")]
    edges = [_edge(10, 1, 2, status="blocked")]
    sol = find_path(
        nodes, edges, source_id=1, dest_id=2, allow_unanalyzed=True
    )
    assert sol is not None
    assert sol.hops == 1


def test_min_margin_filter_excludes_weak_edges():
    nodes, edges = _diamond_graph()
    # Require 22 dB minimum margin -> only the A-D-B path qualifies.
    sol = find_path(
        nodes, edges, source_id=1, dest_id=2,
        objective="hops", min_margin_db=22.0,
    )
    assert sol is not None
    assert sol.nodes == [1, 4, 2]


def test_max_hops_constrains_search():
    """With max_hops=1 between A and B (only blocked edge available), no path."""
    nodes, edges = _diamond_graph()
    sol = find_path(
        nodes, edges, source_id=1, dest_id=2,
        objective="hops", max_hops=1,
    )
    assert sol is None


def test_relay_role_filter_includes_endpoints():
    """Even when relay roles are restricted, source/dest are always allowed."""
    nodes = [
        _node(1, "A", role="CLIENT"),
        _node(2, "B", role="CLIENT"),
        _node(3, "Relay", role="ROUTER"),
    ]
    edges = [_edge(10, 1, 3), _edge(11, 3, 2)]
    sol = find_path(
        nodes, edges, source_id=1, dest_id=2,
        objective="hops", allowed_relay_roles=["ROUTER"],
    )
    assert sol is not None
    assert sol.nodes == [1, 3, 2]


def test_relay_role_filter_blocks_disallowed_relay():
    nodes = [
        _node(1, "A", role="CLIENT"),
        _node(2, "B", role="CLIENT"),
        _node(3, "Relay", role="CLIENT"),
    ]
    edges = [_edge(10, 1, 3), _edge(11, 3, 2)]
    sol = find_path(
        nodes, edges, source_id=1, dest_id=2,
        objective="hops", allowed_relay_roles=["ROUTER"],
    )
    assert sol is None


def test_unknown_source_raises():
    nodes = [_node(1), _node(2)]
    edges = [_edge(10, 1, 2)]
    with pytest.raises(ValueError):
        find_path(nodes, edges, source_id=99, dest_id=2)


def test_same_source_and_dest_rejected():
    nodes = [_node(1)]
    edges: list[EdgeView] = []
    with pytest.raises(ValueError):
        find_path(nodes, edges, source_id=1, dest_id=1)


def test_bottleneck_link_id_is_lowest_margin():
    nodes, edges = _diamond_graph()
    sol = find_path(
        nodes, edges, source_id=1, dest_id=2, objective="lowest_total_loss"
    )
    assert sol is not None
    # A->C->B path uses links 11 (margin 15) and 12 (margin 20). Bottleneck=11.
    assert sol.bottleneck_link_id == 11

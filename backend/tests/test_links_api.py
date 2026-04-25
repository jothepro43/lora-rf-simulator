"""Integration tests for /api/links endpoints.

Builds a fresh in-memory DB and a TestClient. We avoid network calls by
not invoking ``/analyze`` (which fetches SRTM tiles); the routing path
test seeds analyzed metrics directly into the DB.
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from models.database import Base, get_db  # noqa: E402
from models.node import Node  # noqa: E402
from models.link import NetworkLink  # noqa: E402
from api.links import router as links_router  # noqa: E402


@pytest.fixture()
def client():
    # StaticPool keeps a single connection so the :memory: DB persists
    # across requests within the test.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(links_router)
    app.dependency_overrides[get_db] = override_get_db
    # Stash for tests that need to seed extra rows.
    app.state.test_session = TestSession

    seed_db(TestSession)
    with TestClient(app) as c:
        yield c


def seed_db(SessionLocal):
    """Create a 4-node graph with hand-tuned link metrics so we can test
    pathfinding without needing the real RF analyzer."""
    db = SessionLocal()
    try:
        a = Node(id=1, name="A", lat=34.0, lon=-83.0, role="ROUTER")
        b = Node(id=2, name="B", lat=34.5, lon=-83.5, role="ROUTER")
        c = Node(id=3, name="C", lat=34.25, lon=-83.25, role="ROUTER")
        d = Node(id=4, name="D", lat=34.1, lon=-83.4, role="CLIENT")
        db.add_all([a, b, c, d])
        db.commit()

        # Direct A-B blocked.
        l1 = NetworkLink(
            id=10, node1_id=1, node2_id=2,
            distance_km=70.0, path_loss_db=200.0, link_margin_db=-10.0,
            is_los=False, status="blocked",
        )
        # A-C-B: lower total loss but tighter margin.
        l2 = NetworkLink(
            id=11, node1_id=1, node2_id=3,
            distance_km=35.0, path_loss_db=110.0, link_margin_db=15.0,
            is_los=True, status="viable",
        )
        l3 = NetworkLink(
            id=12, node1_id=3, node2_id=2,
            distance_km=35.0, path_loss_db=110.0, link_margin_db=20.0,
            is_los=True, status="good",
        )
        # A-D-B: higher loss but bigger margin.
        l4 = NetworkLink(
            id=13, node1_id=1, node2_id=4,
            distance_km=40.0, path_loss_db=140.0, link_margin_db=25.0,
            is_los=True, status="excellent",
        )
        l5 = NetworkLink(
            id=14, node1_id=4, node2_id=2,
            distance_km=40.0, path_loss_db=140.0, link_margin_db=30.0,
            is_los=True, status="excellent",
        )
        db.add_all([l1, l2, l3, l4, l5])
        db.commit()
    finally:
        db.close()


def test_list_links_returns_seeded_rows(client):
    resp = client.get("/api/links")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 5


def test_path_objective_hops_returns_two_hop_path(client):
    resp = client.post(
        "/api/links/path",
        json={"source_id": 1, "dest_id": 2, "objective": "hops"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["hops"] == 2
    assert body["node_ids"][0] == 1 and body["node_ids"][-1] == 2


def test_path_objective_lowest_total_loss_picks_C_relay(client):
    resp = client.post(
        "/api/links/path",
        json={"source_id": 1, "dest_id": 2, "objective": "lowest_total_loss"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["node_names"] == ["A", "C", "B"]


def test_path_objective_widest_margin_picks_D_relay(client):
    resp = client.post(
        "/api/links/path",
        json={"source_id": 1, "dest_id": 2, "objective": "best_bottleneck_margin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["node_names"] == ["A", "D", "B"]
    assert body["end_to_end_margin_db"] == pytest.approx(25.0)


def test_path_returns_not_found_when_no_route(client):
    """Isolated dest with no edges -> not found."""
    TestSession = client.app.state.test_session
    db = TestSession()
    try:
        db.add(Node(id=99, name="Isolated", lat=0, lon=0, role="CLIENT"))
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/api/links/path",
        json={"source_id": 1, "dest_id": 99},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False


def test_path_rejects_same_source_and_dest(client):
    resp = client.post(
        "/api/links/path",
        json={"source_id": 1, "dest_id": 1},
    )
    assert resp.status_code == 400


def test_path_validates_objective(client):
    resp = client.post(
        "/api/links/path",
        json={"source_id": 1, "dest_id": 2, "objective": "not-real"},
    )
    assert resp.status_code == 422

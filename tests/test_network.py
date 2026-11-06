"""Routing and border-delay checks on a small hand-built network with known answers.
Run: python -m pytest tests"""
import math

import networkx as nx
import pandas as pd
import pytest
from shapely.geometry import LineString

from sim import network

P = dict(truck_teu_per_truck=2, cargo_value_usd_per_teu=87600, holding_rate_per_year=0.1,  # VOT = 1 USD/TEU-h
         truck_usd_per_km=1.0, truck_usd_per_hour=10.0)


def add(G, u, v, length, kph, cap=80, geom=None):
    d = dict(length=length, speed_kph=kph, truck_tt=length / (min(kph, cap) / 3.6))
    if geom is not None:
        d["geometry"] = geom
    G.add_edge(u, v, **d)


@pytest.fixture
def G():
    """Nodes 1-2-3 straight (1 km links), 1-4-3 detour, 3->5 one-way, a far parallel 1->2 road."""
    G = nx.MultiDiGraph(crs=network.CRS_WORK)
    for n, (x, y) in {1: (0, 0), 2: (1000, 0), 3: (2000, 0), 4: (1000, 1000), 5: (3000, 0)}.items():
        G.add_node(n, x=x, y=y)
    D = math.hypot(1000, 1000)
    for a, b in [(1, 2), (2, 3)]:
        add(G, a, b, 1000, 100); add(G, b, a, 1000, 100)
    for a, b in [(1, 4), (4, 3)]:
        add(G, a, b, D, 250); add(G, b, a, D, 250)
    add(G, 3, 5, 1000, 100)
    add(G, 1, 2, 1600, 300, geom=LineString([(0, 0), (500, 800), (1000, 0)]))
    return G


def no_borders(G):
    for _, _, d in G.edges(data=True):
        d.update(border_h=0.0, border_fee_truck=0.0, border_name="")


def test_snap_ignores_parallel_road(G):
    (on, dist), = network.snap_points(G, [250], [5])
    assert {(a, b, k) for a, b, k, _ in on} == {(1, 2, 0), (2, 1, 0)}
    assert dist == pytest.approx(5)


def test_route_mid_edge_to_mid_edge(G):
    no_borders(G)
    network.set_costs(G, P)
    o, t = network.snap_points(G, [250, 2500], [5, 4])
    r = network.route_from(G, o, {"X": t})["X"]
    # truck capped at 80 km/h, so the detour is no faster: straight 750 + 1000 + 500 m
    assert r["length"] == pytest.approx(2250)
    hours = 2.25 / 80
    assert r["hours"] == pytest.approx(hours)
    assert r["usd"] == pytest.approx((2.25 * 1.0 + hours * 10.0) / 2)
    assert r["geometry"].length == pytest.approx(2250)
    assert "__origin__" not in G


def test_border_delay_charged_once_and_avoided_if_possible(G):
    # crossing circle around node 2: the straight route cuts it twice (in and out)
    cr = pd.DataFrame([dict(name="Test border", lat=0, lon=0, radius_m=300, delay_h=5, fee_usd_per_truck=40)])
    # place the circle at node 2 in work coordinates by bypassing the lon/lat conversion
    orig = network.to_work
    network.to_work = lambda lon, lat: ([1000.0], [0.0])
    try:
        network.add_border_delays(G, cr)
    finally:
        network.to_work = orig
    network.set_costs(G, P)
    o, t = network.snap_points(G, [250, 2500], [5, 4])
    r = network.route_from(G, o, {"X": t})["X"]
    # a 5 h delay makes the 1-4-3 detour (no border) cheaper, as a router should choose
    assert r["border_h"] == pytest.approx(0)
    assert r["length"] == pytest.approx(250 + 2 * math.hypot(1000, 1000) + 500)
    # through the border itself: the edges 1->2 and 2->3 each cut the circle once (half each)
    assert G.edges[1, 2, 0]["border_h"] + G.edges[2, 3, 0]["border_h"] == pytest.approx(5)
    assert G.edges[1, 2, 0]["border_fee_truck"] + G.edges[2, 3, 0]["border_fee_truck"] == pytest.approx(40)


def test_border_paid_once_when_unavoidable(G):
    G.remove_edges_from([(1, 4, 0), (4, 1, 0), (4, 3, 0), (3, 4, 0)])  # no detour left
    cr = pd.DataFrame([dict(name="Test border", lat=0, lon=0, radius_m=300, delay_h=5, fee_usd_per_truck=40)])
    orig = network.to_work
    network.to_work = lambda lon, lat: ([1000.0], [0.0])
    try:
        network.add_border_delays(G, cr)
    finally:
        network.to_work = orig
    network.set_costs(G, P)
    o, t = network.snap_points(G, [250, 2500], [5, 4])  # starts part-way along 1->2, before the border
    r = network.route_from(G, o, {"X": t})["X"]
    assert r["border_h"] == pytest.approx(5)
    assert r["borders"] == ["Test border"]
    assert r["hours"] == pytest.approx(2.25 / 80 + 5)
    assert r["usd"] == pytest.approx((2.25 * 1.0 + (2.25 / 80 + 5) * 10.0 + 40) / 2)

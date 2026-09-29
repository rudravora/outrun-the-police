"""
Graph generator for "Outrun the Police" (CODEVERSE 2.0, Phase 2 Game 4).

Produces the city map: >=50 nodes, >=100 directed edges, one HIDEOUT and one
EXTRACTION node. Each edge carries time/risk/cost/[window_start, window_end].

Deliberately engineers a "trap": a short, low-time, high-risk express route
from HIDEOUT to EXTRACTION, alongside a longer, higher-time, low-risk/cost
route, such that under the published scoring weights the safe route wins.

Run directly to (re)generate graph.json + graph.csv and print a summary.
"""
import csv
import json
import random
from pathlib import Path

N_NODES = 60
N_EXTRA_EDGES = 110  # on top of the backbone + trap edges, comfortably >100 total
EVENT_DURATION = 120  # minutes, the whole event window
SEED = 42

# Scoring weights (published to teams) — lower total score is better.
WEIGHTS = {"time": 1.0, "risk": 4.0, "cost": 0.5}

OUT_DIR = Path(__file__).parent
GRAPH_JSON = OUT_DIR / "graph.json"
GRAPH_CSV = OUT_DIR / "graph.csv"


def node_id(i):
    return f"N{i:02d}"


def make_nodes():
    nodes = [node_id(i) for i in range(N_NODES)]
    hideout, extraction = nodes[0], nodes[-1]
    return nodes, hideout, extraction


def score(edge):
    return (
        WEIGHTS["time"] * edge["time"]
        + WEIGHTS["risk"] * edge["risk"]
        + WEIGHTS["cost"] * edge["cost"]
    )


def make_edge(rng, eid, u, v, *, time=None, risk=None, cost=None, window=None):
    t = time if time is not None else rng.randint(3, 15)
    r = risk if risk is not None else rng.randint(1, 10)
    c = cost if cost is not None else rng.randint(1, 20)
    if window is not None:
        ws, we = window
    else:
        ws = rng.randint(0, EVENT_DURATION - 30)
        we = min(EVENT_DURATION, ws + rng.randint(20, 60))
    return {
        "id": f"E{eid}",
        "from": u,
        "to": v,
        "time": t,
        "risk": r,
        "cost": c,
        "window_start": ws,
        "window_end": we,
    }


def build_graph(seed=SEED):
    rng = random.Random(seed)
    nodes, hideout, extraction = make_nodes()

    edges = []
    eid = 0

    # 1. Backbone: a random Hamiltonian-ish chain through all nodes so the
    #    graph is guaranteed connected end-to-end (HIDEOUT -> ... -> EXTRACTION),
    #    open the whole event, at "safe" but unremarkable stats.
    order = nodes[:]  # already HIDEOUT..EXTRACTION by construction
    for u, v in zip(order, order[1:]):
        edges.append(
            make_edge(
                rng, eid, u, v,
                time=rng.randint(4, 8),
                risk=rng.randint(1, 4),
                cost=rng.randint(2, 10),
                window=(0, EVENT_DURATION),
            )
        )
        eid += 1

    # 2. THE TRAP: a short chain of "express" edges from HIDEOUT straight to
    #    EXTRACTION via a couple of hops — very low time, but very high risk.
    #    Fastest-by-time route. Should score worse than the safe backbone.
    trap_mid = nodes[len(nodes) // 2]
    trap_path = [hideout, node_id(3), node_id(7), extraction]
    for u, v in zip(trap_path, trap_path[1:]):
        edges.append(
            make_edge(
                rng, eid, u, v,
                time=rng.randint(1, 2),   # very fast
                risk=rng.randint(18, 25),  # very risky
                cost=rng.randint(1, 5),
                window=(0, EVENT_DURATION),
            )
        )
        eid += 1

    # 3. A second, deliberately SAFE alternate route (slower than trap, but
    #    much lower time than the full backbone) so there's a genuine
    #    trade-off space, not just "one safe path, one trap path".
    safe_path = [hideout, node_id(15), node_id(30), node_id(45), extraction]
    for u, v in zip(safe_path, safe_path[1:]):
        edges.append(
            make_edge(
                rng, eid, u, v,
                time=rng.randint(6, 10),
                risk=rng.randint(1, 3),
                cost=rng.randint(3, 8),
                window=(0, EVENT_DURATION),
            )
        )
        eid += 1

    # 4. Random extra edges for density/red-herrings — random endpoints,
    #    random stats, random (sometimes narrow/early-closing) windows.
    attempts = 0
    added = 0
    existing = {(e["from"], e["to"]) for e in edges}
    while added < N_EXTRA_EDGES and attempts < N_EXTRA_EDGES * 20:
        attempts += 1
        u, v = rng.sample(nodes, 2)
        if (u, v) in existing:
            continue
        existing.add((u, v))
        edges.append(make_edge(rng, eid, u, v))
        eid += 1
        added += 1

    graph = {
        "nodes": [{"id": n} for n in nodes],
        "hideout": hideout,
        "extraction": extraction,
        "edges": edges,
        "weights": WEIGHTS,
        "event_duration": EVENT_DURATION,
    }
    return graph


def write_json(graph, path=GRAPH_JSON):
    path.write_text(json.dumps(graph, indent=2))


def write_csv(graph, path=GRAPH_CSV):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "from", "to", "time", "risk", "cost", "window_start", "window_end"])
        for e in graph["edges"]:
            w.writerow([e["id"], e["from"], e["to"], e["time"], e["risk"], e["cost"],
                        e["window_start"], e["window_end"]])


if __name__ == "__main__":
    g = build_graph()
    write_json(g)
    write_csv(g)
    print(f"nodes={len(g['nodes'])} edges={len(g['edges'])}")
    print(f"hideout={g['hideout']} extraction={g['extraction']}")
    print(f"wrote {GRAPH_JSON} and {GRAPH_CSV}")

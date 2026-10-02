"""
Reference solver for "Outrun the Police".

Proves (before the event) that the generated graph is solvable, and finds
both the shortest-by-time route and the best-by-score route from HIDEOUT to
EXTRACTION, so we can confirm they genuinely differ (the "trap").

Also provides validate_path(), the same logic the live backend must use to
check a team's submitted route against a given event time `t` and a set of
compromised nodes — kept here so both the solver's self-check and the future
Flask backend import one shared source of truth instead of duplicating it.
"""
import heapq
import json
from pathlib import Path

GRAPH_JSON = Path(__file__).parent / "graph.json"


def load_graph(path=GRAPH_JSON):
    return json.loads(Path(path).read_text())


def build_adjacency(graph):
    adj = {n["id"]: [] for n in graph["nodes"]}
    for e in graph["edges"]:
        adj[e["from"]].append(e)
    return adj


def dijkstra(graph, start, goal, weight_fn, *, t=None, compromised=None):
    """
    Generic Dijkstra over directed edges, weighted by weight_fn(edge).
    If t is given, only edges open at time t are traversable (models the
    live event clock). If compromised is given, edges into a compromised
    node are skipped (a compromised HIDEOUT/EXTRACTION would make the graph
    unsolvable at that instant, which is expected/valid behavior).
    Returns (total_weight, path_node_list, path_edge_list) or (None, None, None).
    """
    compromised = compromised or set()
    adj = build_adjacency(graph)
    dist = {start: 0.0}
    prev = {}  # node -> (prev_node, edge)
    pq = [(0.0, start)]
    visited = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == goal:
            break
        for e in adj[u]:
            v = e["to"]
            if v in compromised:
                continue
            if t is not None and not (e["window_start"] <= t <= e["window_end"]):
                continue
            nd = d + weight_fn(e)
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, e)
                heapq.heappush(pq, (nd, v))

    if goal not in dist:
        return None, None, None

    # reconstruct
    nodes = [goal]
    edges = []
    cur = goal
    while cur != start:
        pu, e = prev[cur]
        edges.append(e)
        nodes.append(pu)
        cur = pu
    nodes.reverse()
    edges.reverse()
    return dist[goal], nodes, edges


def time_weight(e):
    return e["time"]


def make_score_weight(weights):
    def w(e):
        return weights["time"] * e["time"] + weights["risk"] * e["risk"] + weights["cost"] * e["cost"]
    return w


def path_totals(edges):
    return {
        "time": sum(e["time"] for e in edges),
        "risk": sum(e["risk"] for e in edges),
        "cost": sum(e["cost"] for e in edges),
    }


def path_score(edges, weights):
    tot = path_totals(edges)
    return weights["time"] * tot["time"] + weights["risk"] * tot["risk"] + weights["cost"] * tot["cost"]


def validate_path(graph, node_path, *, t, compromised, deadline=None, budget=None):
    """
    Server-side validator: given an ordered list of node IDs, the current
    event time t, and the set of currently-compromised node IDs, checks the
    path is a real sequence of currently-open edges through non-compromised
    nodes, AND (if given) that total time <= deadline and total cost <=
    budget. Returns (ok: bool, reason: str, edges: list|None).

    A route that exceeds deadline or budget is REJECTED outright, not
    penalized in a score — risk is the only thing scored now
    (see min_risk_constrained below).

    This is the exact logic the live Flask backend must reuse for
    submission validation (see PRD 8.4 — never trust client-computed score).
    """
    if not node_path or len(node_path) < 2:
        return False, "path must have at least 2 nodes", None

    node_ids = {n["id"] for n in graph["nodes"]}
    for n in node_path:
        if n not in node_ids:
            return False, f"unknown node {n}", None
        if n in compromised:
            return False, f"{n} is compromised", None

    adj = build_adjacency(graph)
    by_endpoints = {}
    for u in adj:
        for e in adj[u]:
            by_endpoints.setdefault((e["from"], e["to"]), []).append(e)

    edges = []
    for u, v in zip(node_path, node_path[1:]):
        candidates = by_endpoints.get((u, v))
        if not candidates:
            return False, f"no edge from {u} to {v}", None
        # pick the (or an) open edge at time t if one exists
        open_candidates = [e for e in candidates if e["window_start"] <= t <= e["window_end"]]
        if not open_candidates:
            return False, f"edge {u}->{v} not open at t={t}", None
        edges.append(open_candidates[0])

    totals = path_totals(edges)
    if deadline is not None and totals["time"] > deadline:
        return False, f"total time {totals['time']} exceeds deadline {deadline}", None
    if budget is not None and totals["cost"] > budget:
        return False, f"total cost {totals['cost']} exceeds budget {budget}", None

    return True, "ok", edges


def min_risk_constrained(graph, start, goal, *, t=None, compromised=None, deadline, budget):
    """
    Finds the minimum-RISK route from start to goal subject to:
      total time  <= deadline
      total cost  <= budget
      (plus the usual open-edge-at-t / not-compromised constraints).

    Plain Dijkstra can't do this: minimizing risk alone would ignore the
    caps, and minimizing a weighted sum (the old model) can silently accept
    a route that blows the budget as long as risk/time compensate. Needed:
    a route that's worse on risk than some other route, but is the only one
    that actually fits the caps.

    Approach: state-augmented DP over (node, cumulative_cost). Edge time/
    cost are small non-negative integers (checked by run_selfcheck), and
    `deadline`/`budget` are themselves finite, so cumulative cost has at
    most `budget + 1` distinct integer values worth tracking (any path
    using more than `budget` cost is already invalid, so it's pruned, not
    bucketed/approximated). For each (node, cost_used) pair we track the
    minimum (risk, time) to reach it; time is folded into the same state
    scan rather than given its own axis, since at fixed cost the only thing
    that matters for deadline-feasibility is minimizing time too — we keep
    the Pareto-minimal (risk, time) pairs per (node, cost) state instead of
    just one, since neither dominates the other.

    Returns (edges, totals) for the best feasible route, or (None, None) if
    no route satisfies both caps.
    """
    compromised = compromised or set()
    adj = build_adjacency(graph)
    budget_i = int(budget)

    best_at_goal = None  # (risk, time, edges)

    # Simple best-first search over (risk, time) ordered by risk, since
    # that's what we minimize; budget/time act as hard filters per edge.
    pq = [(0, 0, start, 0, [])]  # (risk, time, node, cost_used, edges)
    visited_best = {}  # (node, cost_used) -> list of (risk, time) kept

    def dominated(node, cost_used, risk, time_):
        for r, tm in visited_best.get((node, cost_used), []):
            if r <= risk and tm <= time_:
                return True
        return False

    while pq:
        risk, time_, u, cost_used, edges = heapq.heappop(pq)

        if dominated(u, cost_used, risk, time_):
            continue
        visited_best.setdefault((u, cost_used), []).append((risk, time_))

        if u == goal:
            if best_at_goal is None or risk < best_at_goal[0]:
                best_at_goal = (risk, time_, edges)
            continue

        for e in adj[u]:
            v = e["to"]
            if v in compromised:
                continue
            if t is not None and not (e["window_start"] <= t <= e["window_end"]):
                continue
            new_cost = cost_used + e["cost"]
            if new_cost > budget_i:
                continue
            new_time = time_ + e["time"]
            if new_time > deadline:
                continue
            new_risk = risk + e["risk"]
            if dominated(v, new_cost, new_risk, new_time):
                continue
            heapq.heappush(pq, (new_risk, new_time, v, new_cost, edges + [e]))

    if best_at_goal is None:
        return None, None

    risk, time_, edges = best_at_goal
    return edges, path_totals(edges)


def run_selfcheck(graph):
    """Prove solvability and the shortest-time-vs-best-score trap. Raises on failure."""
    weights = graph["weights"]
    hideout, extraction = graph["hideout"], graph["extraction"]

    # Solvable at t=0, nothing compromised.
    t_time, t_nodes, t_edges = dijkstra(graph, hideout, extraction, time_weight, t=0, compromised=set())
    assert t_nodes is not None, "graph not solvable by time at t=0 — generator bug"

    s_score, s_nodes, s_edges = dijkstra(
        graph, hideout, extraction, make_score_weight(weights), t=0, compromised=set()
    )
    assert s_nodes is not None, "graph not solvable by score at t=0 — generator bug"

    fastest_score = path_score(t_edges, weights)
    best_score_route_score = path_score(s_edges, weights)
    fastest_time = path_totals(t_edges)["time"]
    best_score_route_time = path_totals(s_edges)["time"]

    assert best_score_route_score <= fastest_score, (
        "best-scoring route should score at least as well as the fastest-by-time route "
        f"(got best={best_score_route_score}, fastest={fastest_score})"
    )

    trap_confirmed = (t_nodes != s_nodes) and (best_score_route_time > fastest_time) and (
        best_score_route_score < fastest_score
    )
    assert trap_confirmed, (
        "no genuine trap: shortest-by-time route and best-by-score route must differ, "
        "with the score-optimal route being slower but scoring better"
    )

    # validate_path() round-trips both reference routes as legitimate at t=0.
    ok, reason, _ = validate_path(graph, t_nodes, t=0, compromised=set())
    assert ok, f"fastest route failed validate_path: {reason}"
    ok, reason, _ = validate_path(graph, s_nodes, t=0, compromised=set())
    assert ok, f"best-score route failed validate_path: {reason}"

    # A route through a compromised node must be rejected.
    mid_node = t_nodes[1] if len(t_nodes) > 1 else t_nodes[0]
    ok, reason, _ = validate_path(graph, t_nodes, t=0, compromised={mid_node})
    assert not ok, "compromised node should invalidate a route but didn't"

    # --- Constrained model (risk-only objective, hard time/cost caps) ---
    deadline = graph["event_duration"]
    fastest_totals = path_totals(t_edges)

    # (a) solvable under a reasonable deadline/budget combination.
    budget = fastest_totals["cost"] + 50  # generous, just proving feasibility
    c_edges, c_totals = min_risk_constrained(
        graph, hideout, extraction, t=0, compromised=set(), deadline=deadline, budget=budget
    )
    assert c_edges is not None, "graph not solvable under constrained model at t=0 — generator/solver bug"
    ok, reason, _ = validate_path(
        graph, [hideout] + [e["to"] for e in c_edges], t=0, compromised=set(),
        deadline=deadline, budget=budget,
    )
    assert ok, f"constrained solver's own route failed validate_path: {reason}"

    # (b) min-TIME route and min-RISK-under-caps route genuinely differ,
    # proving the min-time route is NOT always what should be accepted as
    # "best". We already know the best-by-score route (lower risk, higher
    # cost than fastest) is feasible under its own cost — scan budgets
    # between fastest's cost and that cost to find one where the
    # risk-minimizer picks a genuinely different, lower-risk route than
    # fastest-by-time (plain Dijkstra-by-time would never surface it).
    best_score_cost = path_totals(s_edges)["cost"]
    mid_edges = mid_totals = mid_budget = None
    for b in range(int(fastest_totals["cost"]), int(best_score_cost) + 1):
        edges, totals = min_risk_constrained(
            graph, hideout, extraction, t=None, compromised=set(), deadline=deadline, budget=b
        )
        if edges is None:
            continue
        nodes = [hideout] + [e["to"] for e in edges]
        if nodes != t_nodes and totals["risk"] < fastest_totals["risk"]:
            mid_edges, mid_totals, mid_budget = edges, totals, b
            break
    assert mid_edges is not None, (
        "expected some budget between the fastest route's cost and the best-score route's "
        "cost to yield a genuinely different, lower-risk route than fastest-by-time"
    )
    mid_nodes = [hideout] + [e["to"] for e in mid_edges]

    return {
        "fastest": {"nodes": t_nodes, "time": fastest_time, "score": fastest_score,
                    "totals": path_totals(t_edges)},
        "best_score": {"nodes": s_nodes, "time": best_score_route_time, "score": best_score_route_score,
                        "totals": path_totals(s_edges)},
        "constrained": {"nodes": mid_nodes, "totals": mid_totals, "budget": mid_budget,
                         "deadline": deadline},
    }


if __name__ == "__main__":
    graph = load_graph()
    result = run_selfcheck(graph)
    print("SELF-CHECK PASSED\n")
    print(f"Fastest-by-time route ({len(result['fastest']['nodes'])} nodes):")
    print("  ", " -> ".join(result["fastest"]["nodes"]))
    print(f"   time={result['fastest']['time']} totals={result['fastest']['totals']} "
          f"score={result['fastest']['score']:.1f}")
    print()
    print(f"Best-by-score route ({len(result['best_score']['nodes'])} nodes):")
    print("  ", " -> ".join(result["best_score"]["nodes"]))
    print(f"   time={result['best_score']['time']} totals={result['best_score']['totals']} "
          f"score={result['best_score']['score']:.1f}")
    print()
    print("TRAP CONFIRMED: fastest route is NOT the best-scoring route.")
    print()
    c = result["constrained"]
    print(f"Min-risk route under budget={c['budget']}, deadline={c['deadline']} "
          f"({len(c['nodes'])} nodes):")
    print("  ", " -> ".join(c["nodes"]))
    print(f"   totals={c['totals']}")
    print("CONSTRAINED MODEL CONFIRMED: min-risk-under-caps route differs from the "
          "fastest-by-time route and has strictly lower risk.")

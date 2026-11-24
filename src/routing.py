"""Phase 3b: route one van to carry out part of an overnight plan
(Formulation 2 in docs/PLAN.md: single-vehicle pickup-and-delivery routing).

Input:  outputs/tables/plan_example.csv (from rebalance.py). change > 0 means
        drop off bikes, change < 0 means pick up bikes.
Cluster: the ROUTE_STATIONS stations with the largest moves in that plan.
The van starts and ends at the depot, may leave the depot loaded and bring
bikes back. Compared with a nearest-neighbour route for each van capacity.
Outputs: outputs/tables/routing_results.csv, outputs/figures/route_map.png
"""
import gurobipy as gp
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from gurobipy import GRB

import config
from eda import BLUE, ORANGE, INK, INK2, MUTED, SURFACE, save

PENALTY_KM = 5.0  # cost (km-equivalent) of each planned bike move left undone


def distances(lat, lon):
    """Road distance estimate: straight-line (haversine) km x circuity factor."""
    la, lo = np.radians(lat)[:, None], np.radians(lon)[:, None]
    h = (np.sin((la - la.T) / 2) ** 2
         + np.cos(la) * np.cos(la.T) * np.sin((lo - lo.T) / 2) ** 2)
    return 6371 * 2 * np.arcsin(np.sqrt(h)) * config.ROAD_CIRCUITY


def solve_route(r, D, Q):
    """r[k] = planned change at node k (node 0 = depot, r[0] = 0). Returns
    (stop order, bikes moved at each stop, km, undone bikes, model size)."""
    n = len(r)
    S = range(1, n)
    m = gp.Model("route")
    m.Params.OutputFlag = 0
    m.Params.TimeLimit = 60
    arcs = [(i, j) for i in range(n) for j in range(n) if i != j]
    x = m.addVars(arcs, vtype=GRB.BINARY)            # van drives i -> j
    f = m.addVars(arcs, lb=0, ub=Q)                  # bikes on board on arc i -> j
    d = {k: m.addVar(lb=min(0, r[k]), ub=max(0, r[k])) for k in S}  # bikes actually moved
    u = m.addVars(S, lb=1, ub=n - 1)                 # visit order (MTZ)
    for k in range(n):
        m.addConstr(x.sum(k, "*") == 1)              # leave every node once
        m.addConstr(x.sum("*", k) == 1)              # enter every node once
    for k in S:
        m.addConstr(f.sum("*", k) - f.sum(k, "*") == d[k])  # load drops by bikes dropped
    for i, j in arcs:
        m.addConstr(f[i, j] <= Q * x[i, j])          # capacity; no load on unused arcs
        if i != 0 and j != 0:
            m.addConstr(u[i] - u[j] + (n - 1) * x[i, j] <= n - 2)  # no subtours
    undone = gp.quicksum(abs(r[k]) - (d[k] if r[k] > 0 else -d[k]) for k in S)
    m.setObjective(gp.quicksum(D[i, j] * x[i, j] for i, j in arcs) + PENALTY_KM * undone)
    m.optimize()
    order, k = [0], 0
    while True:
        k = next(j for j in range(n) if j != k and x[k, j].X > 0.5)
        if k == 0:
            break
        order.append(k)
    km = sum(D[i, j] for i, j in arcs if x[i, j].X > 0.5)
    moved = {k: round(d[k].X) for k in S}
    return order, moved, km, round(undone.getValue()), (m.NumVars, m.NumConstrs), m.MIPGap


def nearest_neighbour(r, D, Q):
    """Baseline, a sensible dispatcher's rule: drive to the closest unvisited
    station where the van can act (it has bikes to drop, or room to pick up);
    if none, the closest unvisited station. The van leaves the depot carrying
    min(Q, total drops) bikes."""
    n = len(r)
    load = min(Q, sum(v for v in r[1:] if v > 0))
    order, moved, left, k = [0], {}, set(range(1, n)), 0
    while left:
        useful = [j for j in left if (r[j] > 0 and load > 0) or (r[j] < 0 and load < Q)]
        k = min(useful or left, key=lambda j: D[k, j])
        left.remove(k)
        order.append(k)
        if r[k] > 0:
            moved[k] = min(r[k], load)
            load -= moved[k]
        else:
            moved[k] = -min(-r[k], Q - load)
            load -= moved[k]
    order.append(0)
    km = sum(D[order[i], order[i + 1]] for i in range(len(order) - 1))
    undone = sum(abs(r[k]) - abs(moved[k]) for k in range(1, n))
    return order[:-1], moved, km, undone


def plot_routes(nodes, routes, Q):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), sharex=True, sharey=True)
    for ax, (title, order, moved, km, undone) in zip(axes, routes):
        path = order + [0]
        ax.plot(nodes.lon.iloc[path], nodes.lat.iloc[path], color=MUTED, lw=1.5, zorder=1)
        for a, b in zip(path[:-1], path[1:]):  # arrow at the midpoint of each leg
            xa, ya, xb, yb = nodes.lon.iat[a], nodes.lat.iat[a], nodes.lon.iat[b], nodes.lat.iat[b]
            ax.annotate("", ((xa + xb) / 2 + (xb - xa) * 0.05, (ya + yb) / 2 + (yb - ya) * 0.05),
                        ((xa + xb) / 2, (ya + yb) / 2),
                        arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.2))
        st = nodes.iloc[1:]
        drop, pick = st[st.change > 0], st[st.change < 0]
        ax.scatter(drop.lon, drop.lat, s=drop.change * 12, color=BLUE, ec=SURFACE, lw=1,
                   zorder=3, label="Drop off bikes")
        ax.scatter(pick.lon, pick.lat, s=-pick.change * 12, color=ORANGE, ec=SURFACE, lw=1,
                   zorder=3, label="Pick up bikes")
        ax.scatter(nodes.lon.iat[0], nodes.lat.iat[0], marker="s", s=70, color=INK, zorder=3,
                   label="Depot (25 Booth Ave)")
        for stop, k in enumerate(order[1:], start=1):
            ax.annotate(f"{stop}: {moved[k]:+d}", (nodes.lon.iat[k], nodes.lat.iat[k]),
                        xytext=(6, 4), textcoords="offset points", fontsize=8, color=INK2)
        ax.set_title(f"{title}\n{km:.1f} km driven; {undone} of {sum(abs(v) for v in nodes.change)} "
                     "planned pickups/drops not done", fontsize=11)
        ax.set_aspect(1 / np.cos(np.radians(43.65)))
        ax.set_xticks([]); ax.set_yticks([])
    axes[1].legend(loc="upper center", bbox_to_anchor=(-0.02, -0.02), ncol=3, fontsize=9)
    fig.suptitle(f"One van (capacity {Q} bikes) serving the 12 largest moves of the example "
                 "plan\nLabels: stop number and bikes dropped (+) or picked up (−)",
                 x=0.01, ha="left", fontweight="bold", fontsize=12)
    save(fig, "route_map.png")


def main():
    plan = pd.read_csv(config.TABLES / "plan_example.csv", index_col="station_id")
    moves = plan[plan.change != 0]
    cluster = moves.loc[moves.change.abs().sort_values(ascending=False).index[:config.ROUTE_STATIONS]]
    print(f"plan moves {moves.change.clip(lower=0).sum()} bikes at {len(moves)} stations; "
          f"cluster covers {cluster.change.abs().sum()} of {moves.change.abs().sum()} "
          "pickups+drops")
    depot = pd.DataFrame({"name": ["Depot"], "lat": [config.DEPOT_LATLON[0]],
                          "lon": [config.DEPOT_LATLON[1]], "change": [0]})
    nodes = pd.concat([depot, cluster[["name", "lat", "lon", "change"]]], ignore_index=True)
    D = distances(nodes.lat.to_numpy(), nodes.lon.to_numpy())
    r = nodes.change.astype(int).tolist()

    rows, routes = [], {}
    for Q in config.VAN_CAPACITIES:
        order, moved, km, undone, size, gap = solve_route(r, D, Q)
        nn = nearest_neighbour(r, D, Q)
        rows += [dict(van_capacity=Q, method="Optimised route", km=km, undone=undone,
                      moved=sum(abs(v) for v in moved.values()), mip_gap=gap),
                 dict(van_capacity=Q, method="Greedy nearest-useful", km=nn[2], undone=nn[3],
                      moved=sum(abs(v) for v in nn[1].values()))]
        routes[Q] = [("Greedy nearest-useful route", nn[0], nn[1], nn[2], nn[3]),
                     ("Optimised route (Gurobi)", order, moved, km, undone)]
        print(f"Q={Q}: optimised {km:.1f} km, {undone} undone (size {size}, gap {gap:.1%}) | "
              f"greedy {nn[2]:.1f} km, {nn[3]} undone")
    res = pd.DataFrame(rows)
    res.round(2).to_csv(config.TABLES / "routing_results.csv", index=False)
    stops = [dict(stop=s, station=nodes.name.iat[k], bikes=routes[config.VAN_CAPACITY][1][2][k])
             for s, k in enumerate(routes[config.VAN_CAPACITY][1][1][1:], start=1)]
    pd.DataFrame(stops).to_csv(config.TABLES / "route_stops_Q20.csv", index=False)
    plot_routes(nodes, routes[config.VAN_CAPACITY], config.VAN_CAPACITY)


if __name__ == "__main__":
    main()

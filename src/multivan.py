"""Phase 3c: route the WHOLE overnight plan with several van tours.

Cluster-first, route-second (Gillett & Miller's sweep heuristic):
  1. Sort the plan's stations by compass angle around the depot, starting
     after the widest empty gap, and cut that order into K wedges carrying
     roughly equal work (bikes picked up + dropped off). Each wedge has at most
     MAX_TOUR_STOPS stations.
  2. Route each wedge as one van tour with the single-van MIP (routing.py).
Several values of K are compared; one van can run several tours in a shift.

Usage: python multivan.py [downtown|wide]
Outputs: outputs/tables/multivan_results{_scope}.csv, multivan_tours{_scope}.csv,
         outputs/figures/multivan_map{_scope}.png
"""
import math
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pulp

import config
import solver as S
from eda import BLUE, ORANGE, INK, INK2, MUTED, GREY, SURFACE, save
from routing import distances, solve_route


def split_big_moves(moves, Q):
    """A station needing more than one van load moved is visited more than once:
    it becomes several stops of at most Q bikes each (e.g. +23 -> +20 and +3)."""
    rows = []
    for sid, r in moves.iterrows():
        n = math.ceil(abs(r.change) / Q)
        for v in range(n):
            part = min(Q, abs(r.change) - v * Q) * np.sign(r.change)
            name = r["name"] if n == 1 else f"{r['name']} (visit {v + 1})"
            rows.append(dict(stop_id=f"{sid}-{v + 1}", name=name, lat=r.lat, lon=r.lon,
                             change=int(part)))
    return pd.DataFrame(rows).set_index("stop_id")


def sweep(moves, K):
    """Assign each station to one of K wedges around the depot (equal work per wedge)."""
    lat0, lon0 = config.DEPOT_LATLON
    angle = np.arctan2(moves.lat - lat0, (moves.lon - lon0) * np.cos(np.radians(lat0)))
    order = angle.sort_values()
    a = order.to_numpy()
    gaps = np.diff(np.r_[a, a[0] + 2 * np.pi])       # gap after each station, wrapping round
    ids = np.roll(order.index.to_numpy(), -((gaps.argmax() + 1) % len(a)))
    work = moves.change.abs().reindex(ids).to_numpy()
    mid = np.cumsum(work) - work / 2                  # where each station's work sits
    wedge = np.minimum((mid / work.sum() * K).astype(int), K - 1)
    return pd.Series(wedge, index=ids)


def balanced_assignment(moves, K, Q):
    """Fisher-Jaikumar style clustering: seeds = centres of the K sweep wedges;
    assign each station to one tour, minimising distance to the tour's seed, so that
    every tour's net bikes (drops - pickups) is within +-Q, i.e. a tour can start
    and end at the depot with one van load. Returns None if no such split exists."""
    wedge = sweep(moves, K)
    seeds = moves.groupby(wedge.reindex(moves.index))[["lat", "lon"]].mean()
    pts = np.vstack([moves[["lat", "lon"]].to_numpy(), seeds.to_numpy()])
    dist = distances(pts[:, 0], pts[:, 1])[: len(moves), len(moves):]   # station x seed
    m = pulp.LpProblem("assign", pulp.LpMinimize)
    ids, tours = list(moves.index), range(K)
    x = {(i, k): m.add_variable(f"x_{i}_{k}", cat="Binary") for i in ids for k in tours}
    m += pulp.lpSum(float(dist[a, k]) * x[i, k] for a, i in enumerate(ids) for k in tours)
    for i in ids:
        m += pulp.lpSum(x[i, k] for k in tours) == 1                     # one tour each
    for k in tours:
        net = pulp.lpSum(int(moves.change[i]) * x[i, k] for i in ids)
        m += net <= Q                                                     # depot load fits
        m += net >= -Q
        m += pulp.lpSum(x[i, k] for i in ids) <= config.MAX_TOUR_STOPS    # tour size
    stats = m.solve(S.make(time_limit=60))
    if not stats.has_solution:
        return None
    return pd.Series({i: next(k for k in tours if x[i, k].value() > 0.5) for i in ids})


def route_tours(moves, wedge, Q):
    """Solve one single-van route per wedge. Returns a list of tour dicts."""
    depot = pd.DataFrame({"name": ["Depot"], "lat": [config.DEPOT_LATLON[0]],
                          "lon": [config.DEPOT_LATLON[1]], "change": [0]})
    tours = []
    for t, ids in wedge.groupby(wedge).groups.items():
        nodes = pd.concat([depot, moves.loc[ids, ["name", "lat", "lon", "change"]]],
                          ignore_index=True)
        D = distances(nodes.lat.to_numpy(), nodes.lon.to_numpy())
        t0 = time.perf_counter()
        order, moved, km, undone, size, gap, _ = solve_route(nodes.change.astype(int).tolist(), D, Q)
        tours.append(dict(tour=len(tours) + 1, nodes=nodes, order=order, moved=moved, km=km,
                          undone=undone, work=int(nodes.change.abs().sum()), gap=gap,
                          seconds=time.perf_counter() - t0))
    return tours


def plot_tours(moves, tours, K, Q, fname, title):
    cols = min(K, 4)
    rows = math.ceil(K / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(3.6 * cols, 2.5 * rows + 1.3),
                             sharex=True, sharey=True, squeeze=False)
    lat0, lon0 = config.DEPOT_LATLON
    for ax in axes.flat[K:]:
        ax.axis("off")
    for ax, t in zip(axes.flat, tours):
        nodes, order = t["nodes"], t["order"]
        ax.scatter(moves.lon, moves.lat, s=6, color=GREY, zorder=1)        # whole plan, for context
        path = order + [0]
        ax.plot(nodes.lon.iloc[path], nodes.lat.iloc[path], color=MUTED, lw=1.2, zorder=2)
        st = nodes.iloc[1:]
        drop, pick = st[st.change > 0], st[st.change < 0]
        ax.scatter(drop.lon, drop.lat, s=8 + drop.change * 4, color=BLUE, ec=SURFACE, lw=0.6,
                   zorder=3, label="Drop off")
        ax.scatter(pick.lon, pick.lat, s=8 - pick.change * 4, color=ORANGE, ec=SURFACE, lw=0.6,
                   zorder=3, label="Pick up")
        ax.scatter(lon0, lat0, marker="s", s=30, color=INK, zorder=4, label="Depot")
        done = t["work"] - t["undone"]
        ax.set_title(f"Tour {t['tour']}: {len(order) - 1} stops, {t['km']:.1f} km\n"
                     f"{done} of {t['work']} pickups/drops done", fontsize=9)
        ax.set_aspect(1 / np.cos(np.radians(43.65)))
        ax.set_xticks([]); ax.set_yticks([])
        ax.grid(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=9, frameon=False)
    fig.suptitle(title, x=0.01, ha="left", fontweight="bold", fontsize=12)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(config.FIGURES / fname, dpi=150)
    plt.close(fig)
    print(f"  saved {fname}")


def main(scope):
    sfx = "" if scope == "downtown" else f"_{scope}"
    Q = config.VAN_CAPACITY
    plan = pd.read_csv(config.TABLES / f"plan_example{sfx}.csv", index_col="station_id")
    moves = split_big_moves(plan[plan.change != 0], Q)
    total = int(moves.change.abs().sum())
    print(f"[{scope}] plan: {moves.change.clip(lower=0).sum()} bikes, {len(moves)} stops (stations needing >Q bikes visited twice), "
          f"{total} pickups+drops; van capacity {Q}; solver {S.SOLVER}")

    k_min = math.ceil(len(moves) / config.MAX_TOUR_STOPS)
    results, all_tours = [], {}
    for K in range(k_min, k_min + 4):
        for method in ("Sweep (angle only)", "Balanced assignment"):
            wedge = sweep(moves, K) if method.startswith("Sweep") else balanced_assignment(moves, K, Q)
            if wedge is None or wedge.value_counts().max() > config.MAX_TOUR_STOPS:
                print(f"  K={K} {method}: no split within {config.MAX_TOUR_STOPS} stations"
                      + ("" if method.startswith("Sweep") else f" and +-{Q} net bikes"))
                continue
            tours = route_tours(moves, wedge, Q)
            all_tours[K, method] = tours
            km = [t["km"] for t in tours]
            undone = sum(t["undone"] for t in tours)
            results.append(dict(clustering=method, tours=K, total_km=sum(km),
                                longest_tour_km=max(km), drive_hours=sum(km) / config.DRIVE_KMH,
                                pickups_drops=total, not_done=undone,
                                share_done=1 - undone / total,
                                max_gap=max(t["gap"] for t in tours),
                                solve_seconds=sum(t["seconds"] for t in tours)))
            r = results[-1]
            print(f"  K={K} {method}: {r['total_km']:.1f} km (longest {r['longest_tour_km']:.1f}), "
                  f"{undone} of {total} not done, max gap {r['max_gap']:.1%}, "
                  f"{r['solve_seconds']:.0f}s")
    res = pd.DataFrame(results)
    res.round(3).to_csv(config.TABLES / f"multivan_results{sfx}.csv", index=False)

    # Show the fewest balanced tours that complete at least 99% of the plan
    bal = res[res.clustering == "Balanced assignment"]
    ok = bal[bal.share_done >= 0.99]
    K = int((ok if len(ok) else bal.nsmallest(1, "not_done")).tours.iat[0])
    tours = all_tours[K, "Balanced assignment"]
    rows = [dict(tour=t["tour"], stop=s, station=t["nodes"].name.iat[k], bikes=t["moved"][k],
                 tour_km=round(t["km"], 2))
            for t in tours for s, k in enumerate(t["order"][1:], start=1)]
    pd.DataFrame(rows).to_csv(config.TABLES / f"multivan_tours{sfx}.csv", index=False)
    r = bal[bal.tours == K].iloc[0]
    plot_tours(moves, tours, K, Q, f"multivan_map{sfx}.png",
               f"Whole overnight plan ({scope}, {moves.change.clip(lower=0).sum()} bikes) "
               f"in {K} van tours of up to {Q} bikes\n"
               f"{r.total_km:.0f} km in total, {r.share_done:.0%} of pickups/drops done")
    print(f"  shown: K={K}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "downtown")

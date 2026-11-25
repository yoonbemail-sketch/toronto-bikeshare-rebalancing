"""Phase 3a: overnight repositioning (Formulation 1 in docs/PLAN.md), evaluated
against two baselines on held-out mornings.

Train: May-Aug working days build each station's failure curve g_i(y).
Test:  every Sep-Oct working day. For each test night:
  1. estimate the no-rebalancing 6am inventory b_i (previous day replayed from 50%),
  2. choose a plan with each policy under a budget of bikes moved,
  3. replay that real morning from the planned levels and count failures.

Policies: no rebalancing | "fill to 50%" rule | optimised MIP (HiGHS by default,
Gurobi with SOLVER=gurobi; see solver.py).
Outputs: outputs/tables/rebalancing_*.csv, outputs/figures/budget_curve.png,
         outputs/figures/plan_example.png
"""
import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pulp

import config
import morning as M
import solver as S
from eda import BLUE, ORANGE, INK2, MUTED, SURFACE, AXIS, save  # shared chart style

BUDGETS = [0, 25, 50, 75, 100, 150, 200, 300, 400, None]  # bikes moved per night; None = no limit
MOVE_COST = 1e-3  # tiny cost per bike moved: never move a bike for zero benefit


# --- Policies ----------------------------------------------------------------
def solve_plan(st, g, b, budget, solver=None):
    """Formulation 1: choose each station's 6am level y_i to minimise expected
    morning failures, moving at most `budget` bikes between stations.
    Returns (levels y, (variables, constraints), optimal objective)."""
    m = pulp.LpProblem("overnight", pulp.LpMinimize)
    ids = list(st.index)
    # z[i, y] = 1 if station i starts the morning with exactly y bikes
    z = {(i, y): m.add_variable(f"z_{i}_{y}", cat="Binary")
         for i in ids for y in range(st.capacity[i] + 1)}
    p = {i: m.add_variable(f"p_{i}", 0, int(b[i]), "Integer") for i in ids}               # picked up
    q = {i: m.add_variable(f"q_{i}", 0, int(st.capacity[i]), "Integer") for i in ids}    # dropped
    m += (pulp.lpSum(float(g[i][y]) * z[i, y] for (i, y) in z)
          + MOVE_COST * pulp.lpSum(p.values()))                                          # objective
    for i in ids:
        levels = range(st.capacity[i] + 1)
        m += pulp.lpSum(z[i, y] for y in levels) == 1                                   # one level
        m += pulp.lpSum(y * z[i, y] for y in levels) == int(b[i]) - p[i] + q[i]         # balance
    m += pulp.lpSum(p.values()) == pulp.lpSum(q.values())   # vans only move bikes
    if budget is not None:
        m += pulp.lpSum(p.values()) <= budget                # overnight budget
    stats = S.solve(m, solver)
    assert stats.status == pulp.LpSolveStatus.Optimal, stats.status
    y = pd.Series({i: round(int(b[i]) - p[i].value() + q[i].value()) for i in ids})
    return y, (stats.num_variables, stats.num_constraints), stats.objective


def rule_fill_half(st, b, budget):
    """Rule of thumb: move bikes toward 50% of capacity at every station,
    largest surplus to largest deficit first, until the budget runs out."""
    y = b.copy()
    target = (0.5 * st.capacity).round().astype(int)
    left = math.inf if budget is None else budget
    while left > 0:
        surplus, deficit = (y - target).clip(lower=0), (target - y).clip(lower=0)
        if surplus.max() == 0 or deficit.max() == 0:
            break
        i, j = surplus.idxmax(), deficit.idxmax()
        k = int(min(surplus[i], deficit[j], left))
        y[i] -= k
        y[j] += k
        left -= k
    return y


def morning_failures(st, events, y):
    fp = fr = 0
    for sid in st.index:
        a, b_, _ = M.replay(events.get(sid, []), st.capacity[sid], int(y[sid]))
        fp, fr = fp + int(a), fr + int(b_)
    return fp, fr


# --- Evaluation --------------------------------------------------------------
def evaluate(st, ev, g, test_days):
    rows, plans, sizes = [], {}, set()
    for day in test_days:
        b = M.overnight_inventory(ev, st, day)
        events = M.morning(ev, day)
        n_events = sum(len(events.get(s, [])) for s in st.index)
        fp, fr = morning_failures(st, events, b)
        rows.append(dict(day=day, policy="No rebalancing", budget=0, moved=0,
                         fail_pick=fp, fail_ret=fr, events=n_events))
        for budget in BUDGETS[1:]:
            for policy in ("Fill to 50% rule", "Optimised"):
                if policy == "Optimised":
                    y, size, _ = solve_plan(st, g, b, budget)
                    sizes.add(size)
                else:
                    y = rule_fill_half(st, b, budget)
                fp, fr = morning_failures(st, events, y)
                moved = int((b - y).clip(lower=0).sum())
                rows.append(dict(day=day, policy=policy, budget=budget, moved=moved,
                                 fail_pick=fp, fail_ret=fr, events=n_events))
                plans[(day, policy, budget)] = (b, y)
    df = pd.DataFrame(rows)
    df["budget"] = df.budget.astype("object").where(df.budget.notna(), "no limit")
    df["failures"] = df.fail_pick + df.fail_ret
    return df, plans, sizes


def summarise(df):
    s = (df.groupby(["policy", "budget"], sort=False)
         .agg(moved=("moved", "mean"), fail_pick=("fail_pick", "mean"),
              fail_ret=("fail_ret", "mean"), failures=("failures", "mean"),
              events=("events", "mean")).reset_index())
    s["failure_rate"] = s.failures / s.events
    for qcap in config.VAN_CAPACITIES:
        s[f"van_loads_Q{qcap}"] = np.ceil(s.moved / qcap)
    return s


# --- Charts ------------------------------------------------------------------
def plot_budget_curve(s):
    base = s[s.policy == "No rebalancing"].failures.iat[0]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.axhline(base, color=MUTED, lw=1.5, ls="--")
    ax.annotate(f"No rebalancing: {base:.0f} failures per morning", (s.moved.max() * 1.22, base),
                xytext=(0, -12), textcoords="offset points", color=INK2, fontsize=9, ha="right")
    for policy, color in [("Fill to 50% rule", ORANGE), ("Optimised", BLUE)]:
        d = s[s.policy == policy]
        x = np.r_[0, d.moved]
        yv = np.r_[base, d.failures]
        ax.plot(x, yv, color=color, marker="o", ms=5, mec=SURFACE, mew=1.2)
        ax.annotate(policy, (x[-1], yv[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", color=INK2, fontsize=9)
    ax.set_ylim(0, s.failures.max() * 1.12)
    ax.set_xlim(0, s.moved.max() * 1.25)
    ax.set(xlabel="Bikes moved overnight (average per night)",
           ylabel="Failed pickups + returns, 6–10am")
    ax.set_title("Morning failures vs overnight effort, 37 stations\n"
                 "Held-out Sep–Oct 2025 working days (43 mornings)")
    save(fig, "budget_curve.png")


def plot_plan(st, b, y_opt, y_rule, title):
    prof = pd.read_csv(config.TABLES / "station_morning_profile.csv", index_col="station_id")
    order = prof.am_net_avg.reindex(st.index).sort_values().index
    pos = np.arange(len(order))
    cap = st.capacity[order].to_numpy()
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.barh(pos, cap, color="#f0efec", height=0.75, label="Docks")
    for k, sid in enumerate(order):
        ax.plot([b[sid], y_opt[sid]], [k, k], color=AXIS, lw=1.5, zorder=2)
    ax.scatter(b[order], pos, color=MUTED, s=28, zorder=3, label="6am without rebalancing")
    ax.scatter(y_rule[order], pos, color=ORANGE, marker="|", s=90, lw=2, zorder=3,
               label="Fill to 50% rule")
    ax.scatter(y_opt[order], pos, color=BLUE, s=34, ec=SURFACE, lw=1, zorder=4,
               label="Optimised plan")
    ax.set_yticks(pos, [st.name[i][:34] for i in order], fontsize=8)
    ax.set_xlabel("Bikes at the station at 6am")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=8)
    ax.text(0.99, 0.995, "top: fills in the morning\nbottom: empties in the morning",
            transform=ax.transAxes, ha="right", va="top", fontsize=8, color=INK2)
    ax.set_title(title)
    save(fig, "plan_example.png")


def main():
    st, valet = M.load_study()
    print(f"{len(st)} stations; excluded as valet-type: {', '.join(valet.name)}")
    ev = M.load_events(st.index)
    days = M.working_days()
    train, test = days[days.month <= 8], days[days.month >= 9]
    print(f"train {len(train)} mornings (May-Aug), test {len(test)} mornings (Sep-Oct)")
    g = M.failure_curves(ev, st, train)

    df, plans, sizes = evaluate(st, ev, g, test)
    print(f"solver {S.SOLVER}; model size (vars, constraints): {sorted(sizes)}")
    s = summarise(df)
    df.to_csv(config.TABLES / "rebalancing_by_night.csv", index=False)
    s.round(3).to_csv(config.TABLES / "rebalancing_results.csv", index=False)
    print(s[["policy", "budget", "moved", "fail_pick", "fail_ret", "failures",
             "failure_rate"]].round(2).to_string(index=False))

    # Headline budget: smallest budget reaching 90% of the best reduction seen on
    # test mornings. (The best is not always "no limit": beyond ~100 bikes the plan
    # fits May-Aug patterns slightly better than they hold in Sep-Oct.)
    base = s[s.policy == "No rebalancing"].failures.iat[0]
    opt = s[s.policy == "Optimised"].reset_index(drop=True)
    best = opt.failures.min()
    head = opt[base - opt.failures >= 0.9 * (base - best)].iloc[0]
    rule = s[(s.policy == "Fill to 50% rule") & (s.budget == head.budget)].iloc[0]
    print(f"headline budget: {head.budget} bikes -> optimised {head.failures:.1f}, "
          f"rule {rule.failures:.1f}, none {base:.1f} failures/morning")
    pd.Series({"headline_budget": head.budget, "base_failures": base,
               "opt_failures": head.failures, "rule_failures": rule.failures,
               "opt_moved": head.moved, "rule_moved": rule.moved,
               "best_unlimited_failures": best,
               "unlimited_moved": opt.moved.iat[-1]}).to_csv(
        config.TABLES / "rebalancing_headline.csv", header=["value"])

    plot_budget_curve(s)

    # Example night: the test night with the median no-rebalancing failures
    nb = df[df.policy == "No rebalancing"].sort_values("failures")
    day = nb.day.iat[len(nb) // 2]
    b, y_opt = plans[(day, "Optimised", head.budget)]
    _, y_rule = plans[(day, "Fill to 50% rule", head.budget)]
    plan = pd.DataFrame({"name": st.name, "capacity": st.capacity, "lat": st.lat, "lon": st.lon,
                         "b_6am_no_rebalancing": b, "y_optimised": y_opt, "y_rule": y_rule})
    plan["change"] = plan.y_optimised - plan.b_6am_no_rebalancing  # + drop off, - pick up
    plan.index.name = "station_id"
    plan.to_csv(config.TABLES / "plan_example.csv")
    row = df[(df.day == day)].set_index(["policy", "budget"]).failures
    plot_plan(st, b, y_opt, y_rule,
              f"Overnight plan for {day:%a %d %b %Y} (budget {head.budget:.0f} bikes)\n"
              f"Failures that morning: none {row[('No rebalancing', 0)]}, "
              f"rule {row[('Fill to 50% rule', head.budget)]}, "
              f"optimised {row[('Optimised', head.budget)]}")
    print(f"example night {day:%Y-%m-%d}: moved {int(plan.change.clip(lower=0).sum())} bikes")


if __name__ == "__main__":
    main()

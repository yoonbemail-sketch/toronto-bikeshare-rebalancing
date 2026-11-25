"""Cross-check: solve the same models with HiGHS and Gurobi and compare.

Sample: the overnight model on every 6th test night x three budgets, and the
routing model for each van capacity. Skipped if Gurobi is not installed or
licensed. Output: outputs/tables/solver_check.csv
"""
import time

import numpy as np
import pandas as pd

import config
import morning as M
import solver as S
from rebalance import solve_plan
from routing import distances, solve_route


def timed(fn, *args):
    t0 = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - t0


def main():
    if not (S.available("highs") and S.available("gurobi")):
        print("Gurobi not available: solver cross-check skipped")
        return
    highs, gurobi = S.make("highs"), S.make("gurobi")
    rows = []

    st, _ = M.load_study()
    st = M.usable(st)
    ev = M.load_events(st.index)
    days = M.working_days()
    train, test = days[days.month <= 8], days[days.month >= 9]
    g = M.failure_curves(ev, st, train)
    for day in test[::6]:
        b = M.overnight_inventory(ev, st, day)
        for budget in (25, 75, None):
            (_, size, oh), th = timed(solve_plan, st, g, b, budget, highs)
            (_, _, og), tg = timed(solve_plan, st, g, b, budget, gurobi)
            rows.append(dict(model="overnight", case=f"{day:%Y-%m-%d} budget={budget}",
                             variables=size[0], constraints=size[1],
                             obj_highs=oh, obj_gurobi=og, sec_highs=th, sec_gurobi=tg))

    plan = pd.read_csv(config.TABLES / "plan_example.csv", index_col="station_id")
    moves = plan[plan.change != 0]
    cl = moves.loc[moves.change.abs().sort_values(ascending=False).index[:config.ROUTE_STATIONS]]
    D = distances(np.r_[config.DEPOT_LATLON[0], cl.lat], np.r_[config.DEPOT_LATLON[1], cl.lon])
    r = [0] + cl.change.astype(int).tolist()
    for Q in config.VAN_CAPACITIES:
        out_h, th = timed(solve_route, r, D, Q, highs)
        out_g, tg = timed(solve_route, r, D, Q, gurobi)
        rows.append(dict(model="routing", case=f"van capacity {Q}",
                         variables=out_h[4][0], constraints=out_h[4][1],
                         obj_highs=out_h[6], obj_gurobi=out_g[6], sec_highs=th, sec_gurobi=tg))

    df = pd.DataFrame(rows)
    df["same_optimum"] = (df.obj_highs - df.obj_gurobi).abs() <= 1e-6 * (1 + df.obj_gurobi.abs())
    df.round(4).to_csv(config.TABLES / "solver_check.csv", index=False)
    for model, d in df.groupby("model", sort=False):
        print(f"{model}: {d.same_optimum.sum()}/{len(d)} same optimal objective; "
              f"mean time HiGHS {d.sec_highs.mean():.2f}s, Gurobi {d.sec_gurobi.mean():.2f}s")


if __name__ == "__main__":
    main()

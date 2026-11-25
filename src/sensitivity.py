"""Sensitivity of the downtown results to usable dock capacity.

A disabled bike fills a dock and cannot be ridden, and a disabled dock takes no
bike, so a station holds fewer usable bikes than its GBFS dock count. A live
snapshot (outputs/tables/station_status_2026-11-25.csv) found a median of 1 and
a mean of 1.4 unusable docks per study station.

This reruns the downtown evaluation in rebalance.py with every station's
capacity cut by 0, 1 and 2 docks (morning.usable). The failure curves, the
no-rebalancing baseline, both plans (optimised and the 50% rule) and the
held-out replay all use the reduced capacity. The station set is the same 37
in every run. Buffer 0 reproduces rebalancing_results.csv.

Output: outputs/tables/capacity_sensitivity.csv
"""
import pandas as pd

import config
import morning as M
import rebalance as R

BUFFERS = [0, 1, 2]                 # unusable docks per station
BUDGETS = [0, 25, 50, 75, 100]      # bikes moved per night (0 = no rebalancing)


def main():
    st0, _ = M.load_study("downtown")
    ev = M.load_events(st0.index)
    days = M.working_days()
    train, test = days[days.month <= 8], days[days.month >= 9]

    out = []
    for k in BUFFERS:
        st = M.usable(st0, k)
        g = M.failure_curves(ev, st, train)
        df, _, _ = R.evaluate(st, ev, g, test, BUDGETS)
        s = R.summarise(df)
        # Test mornings on which each policy beats no rebalancing (out of len(test))
        none = df[df.policy == "No rebalancing"].set_index("day").failures
        df["beats_none"] = df.failures.values < none.reindex(df.day).values
        s["mornings_better_than_none"] = (df.groupby(["policy", "budget"], sort=False)
                                          .beats_none.sum().values)
        s.insert(0, "usable_docks", int(st.capacity.sum()))
        s.insert(0, "capacity_buffer", k)
        out.append(s[["capacity_buffer", "usable_docks", "policy", "budget", "moved",
                      "fail_pick", "fail_ret", "failures", "mornings_better_than_none"]])
        print(f"buffer {k}: {int(st.capacity.sum())} usable docks")
        print(s[["policy", "budget", "moved", "fail_pick", "fail_ret", "failures"]]
              .round(1).to_string(index=False))

    res = pd.concat(out, ignore_index=True)
    res.round(3).to_csv(config.TABLES / "capacity_sensitivity.csv", index=False)
    print(f"saved capacity_sensitivity.csv ({len(test)} test mornings)")


if __name__ == "__main__":
    main()

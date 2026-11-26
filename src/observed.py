"""Phase 4: check the trip-only model against observed station counts.

Phase 3 never saw a station's real bike count. Its 6am starting state was
simulated, and failures were replayed against it. The 2025 snapshots
(snapshots.py) show what was really there. On the 43 held-out Sep-Oct mornings
at the 37 modelled stations:

  1. Validation: start each morning from the OBSERVED 6am count, replay the
     recorded trips, and compare the replayed count with later snapshots.
  2. No overnight moves: the observed 9pm state the evening before, rolled to
     6am with that night's trips and no vans. This replaces Phase 3's 24-hour
     simulation from 50% full.
  3. Actual 2025 practice: the observed 6am state, after the operator's real
     overnight moves, scored like any other policy.
  4. Plans: the 50% rule and the optimised MIP (rebalance.py, unchanged), starting
     from the no-overnight-moves state.
  5. Operator moves: changes in a station's count that trips do not explain.

Capacity on each morning is the observed usable capacity at 6am: rentable bikes
plus free docks, so disabled bikes and docks are left out. Every policy is
replayed over the same real 6-10am trips with no vans during the morning, so
the comparison is like for like. Absolute counts are still replayed estimates.

Outputs: outputs/tables/observed_*.csv, outputs/figures/observed_*.png
"""
from functools import lru_cache

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config
import morning as M
import rebalance as R
from eda import BLUE, ORANGE, INK, INK2, AXIS, SURFACE, save

H = pd.Timedelta(hours=1)
MAX_AGE = pd.Timedelta(minutes=config.SNAPSHOT_MAX_AGE)
BUDGETS = [25, 50, 75, 100]
EXAMPLE = (7682, pd.Timestamp("2025-09-26"))   # Bathurst St / Front St W, the Phase 3 example night


# --- Data ----------------------------------------------------------------------
def load_snapshots(ids):
    s = pd.read_parquet(config.PROCESSED / f"snapshots_{config.TRIP_YEAR}.parquet")
    s = s[s.station_id.isin(ids)].copy()
    s["t"] = s.t.astype("datetime64[ns]")
    s["phys"] = s.bikes + s.disabled      # bikes physically in a dock, rentable or not
    s["usable"] = s.bikes + s.docks       # rentable bikes + free docks
    return s


class Trips:
    """Recorded trips per station, for 'arrivals minus departures between t0 and t1'."""

    def __init__(self, ev):
        self.t, self.cum = {}, {}
        for sid, g in ev.groupby("station_id"):
            self.t[sid] = g.time.to_numpy().astype("datetime64[ns]")
            self.cum[sid] = np.r_[0, np.cumsum(g.d.to_numpy())]

    def net(self, sid, t0, t1):
        """Net trips in (t0, t1]; t0 and t1 may be arrays."""
        if sid not in self.t:
            return np.zeros(np.shape(t1), dtype=int)
        at = lambda x: self.cum[sid][np.searchsorted(  # noqa: E731
            self.t[sid], np.asarray(x, dtype="datetime64[ns]"), side="right")]
        return at(t1) - at(t0)

    def events(self, sid, t0, t1):
        """(times, +1/-1 deltas) of trips in [t0, t1)."""
        if sid not in self.t:
            return np.array([], dtype="datetime64[ns]"), np.array([], dtype=int)
        tt = self.t[sid]
        a, b = np.searchsorted(tt, np.datetime64(t0, "ns")), np.searchsorted(tt, np.datetime64(t1, "ns"))
        return tt[a:b], np.diff(self.cum[sid])[a:b]


def state_at(snap, trips, when):
    """Each station's observed state at `when`: the nearest snapshot within
    SNAPSHOT_MAX_AGE, moved to `when` with the recorded trips in between.
    Returns DataFrame [bikes, usable] indexed by station; stations with no
    snapshot that close are left out."""
    w = snap[(snap.t >= when - MAX_AGE) & (snap.t <= when + MAX_AGE)]
    w = w.loc[(w.t - when).abs().groupby(w.station_id).idxmin()]
    rows = {}
    for r in w.itertuples():
        adj = trips.net(r.station_id, r.t, when) if r.t <= when else -trips.net(r.station_id, when, r.t)
        rows[r.station_id] = (int(np.clip(r.bikes + adj, 0, r.usable)), int(r.usable))
    return pd.DataFrame.from_dict(rows, orient="index", columns=["bikes", "usable"])


def replay_path(times, deltas, capacity, start, at):
    """Same rule as morning.replay, but returns the count at each time in `at`."""
    inv, path = start, [start]
    for d in deltas:
        inv = min(inv + 1, capacity) if d > 0 else max(inv - 1, 0)
        path.append(inv)
    return np.array(path)[np.searchsorted(times, np.asarray(at, dtype="datetime64[ns]"), side="right")]


# --- 0. Coverage and consistency of the archive --------------------------------
def covered_mornings(times, days):
    """A morning is covered if a snapshot falls within 15 min of 6am and no gap
    before 10am exceeds 35 min. times: sorted Series of snapshot times."""
    ok = []
    for d in days:
        six, ten = d + 6 * H, d + 10 * H
        edges = pd.DatetimeIndex([six, *times[(times >= six) & (times <= ten)], ten]).asi8 / 6e10
        ok.append(((times - six).abs().min() <= pd.Timedelta(minutes=15)) and np.diff(edges).max() <= 35)
    return pd.Series(ok, index=days)


def coverage(st, snap, trips, days):
    """How well the archive covers the season, whether its counts move with the
    trips, and how its 2025 dock counts compare with the 2026 feed used in Phase 3."""
    out = {}
    times = pd.Series(np.sort(snap.t.unique()))
    gap = times.diff() / pd.Timedelta(minutes=1)
    out["snapshot_times"] = len(times)
    out["median_gap_min"] = gap.median()
    out["longest_gap_start"], out["longest_gap_hours"] = times[gap.idxmax() - 1], gap.max() / 60

    ok = covered_mornings(times, days)
    out["usable_mornings_train"], out["working_days_train"] = ok[days.month <= 8].sum(), (days.month <= 8).sum()
    out["usable_mornings_test"], out["working_days_test"] = ok[days.month >= 9].sum(), (days.month >= 9).sum()

    # Consecutive 6-10am snapshots at most 30 min apart: change in bikes docked vs net trips
    s = snap[snap.station_id.isin(st.index)].sort_values(["station_id", "t"])
    s = s.assign(prev_t=s.groupby("station_id").t.shift(), dphys=s.groupby("station_id").phys.diff())
    s = s.dropna(subset=["prev_t"])
    s = s[(s.t - s.prev_t <= pd.Timedelta(minutes=30)) & s.t.dt.normalize().isin(days)
          & (s.prev_t.dt.hour >= 6) & (s.t.dt.hour < 10) & (s.prev_t.dt.normalize() == s.t.dt.normalize())]
    for shift in (0, -2, 2):  # minutes; a shift should make the match worse if the clocks agree
        sh = pd.Timedelta(minutes=shift)
        net = np.concatenate([trips.net(sid, g.prev_t + sh, g.t + sh)
                              for sid, g in s.groupby("station_id", sort=False)])
        tag = "" if shift == 0 else f"_shift{shift:+d}min"
        out[f"intervals_exact_match{tag}"] = (s.dphys.values == net).mean()
        if shift == 0:
            out["intervals"] = len(s)
            out["intervals_within_1"] = (np.abs(s.dphys.values - net) <= 1).mean()

    # Docks: 2025 archive vs the 2026 feed (Phase 3)
    s37 = snap[snap.station_id.isin(st.index)]
    unaccounted = s37.capacity - (s37.bikes + s37.disabled + s37.docks + s37.docks_disabled)
    out["rows_with_unaccounted_docks"] = (unaccounted != 0).mean()
    cap = s37.groupby("station_id").capacity.agg(min_2025="min", max_2025="max", end_2025="last")
    cap = cap.join(st[["name", "capacity"]].rename(columns={"capacity": "gbfs_2026"}))
    out["stations_docks_differ_from_2026"] = ((cap.min_2025 != cap.gbfs_2026)
                                              | (cap.max_2025 != cap.gbfs_2026)).sum()
    out["docks_end_2025"], out["docks_2026_feed"] = cap.end_2025.sum(), cap.gbfs_2026.sum()
    return pd.Series(out), cap


# --- 1. Validation ---------------------------------------------------------------
def validate(st, snap, trips, test, b_sim):
    """Replay each test morning from the observed 6am count and compare with every
    later snapshot up to 10am. b_sim: Phase 3's simulated 6am counts, for contrast."""
    rows, starts = [], []
    for day in test:
        six, ten = day + 6 * H, day + 10 * H
        s6 = state_at(snap, trips, six)
        later = snap[(snap.t > six) & (snap.t <= ten)]
        for sid, obs in later.groupby("station_id"):
            if sid not in s6.index or sid not in st.index:
                continue
            b0, cap = s6.loc[sid]
            times, deltas = trips.events(sid, six, ten)
            rep = replay_path(times, deltas, cap, b0, obs.t)
            rows.append(pd.DataFrame({"day": day, "station_id": sid, "t": obs.t.values,
                                      "observed": obs.bikes.values, "observed_docks": obs.docks.values,
                                      "replayed": rep, "usable": cap}))
            starts.append(dict(day=day, station_id=sid, observed_6am=b0, usable_6am=cap,
                               phase3_simulated_6am=int(b_sim[day][sid])))
    v = pd.concat(rows, ignore_index=True)
    v["err"] = v.replayed - v.observed
    v["hours_after_6"] = ((v.t - v.day - 6 * H) / H).clip(upper=3.999).astype(int)
    return v, pd.DataFrame(starts)


def validation_summary(v, starts):
    obs_empty, rep_empty = v.observed == 0, v.replayed == 0
    obs_full, rep_full = v.observed_docks == 0, v.replayed == v.usable
    by_hour = v.groupby("hours_after_6").err.agg(
        within_1=lambda e: (e.abs() <= 1).mean(), within_3=lambda e: (e.abs() <= 3).mean(),
        mean_abs=lambda e: e.abs().mean())
    sim_gap = (starts.phase3_simulated_6am - starts.observed_6am).abs()
    s = {
        "comparisons": len(v),
        "station_mornings": len(starts),
        "within_1_bike": (v.err.abs() <= 1).mean(),
        "within_3_bikes": (v.err.abs() <= 3).mean(),
        "mean_abs_error": v.err.abs().mean(),
        "observed_empty_share": obs_empty.mean(),
        "replay_empty_share": rep_empty.mean(),
        "empty_both_share_of_observed_empty": (obs_empty & rep_empty).sum() / obs_empty.sum(),
        "observed_full_share": obs_full.mean(),
        "replay_full_share": rep_full.mean(),
        "full_both_share_of_observed_full": (obs_full & rep_full).sum() / obs_full.sum(),
        "phase3_6am_median_abs_gap": sim_gap.median(),
        "phase3_6am_within_3_share": (sim_gap <= 3).mean(),
    }
    for h, r in by_hour.iterrows():
        s[f"within_1_bike_hour{h + 1}"] = r.within_1
        s[f"mean_abs_error_hour{h + 1}"] = r.mean_abs
    return pd.Series(s)


# --- 2-4. Policies on observed starting states ----------------------------------
def make_curve(mornings):
    """Failure curves from a list of mornings ({station_id: +1/-1 events}).
    Returns curve(sid, cap): g(y) for y = 0..cap, averaged over the mornings."""
    @lru_cache(maxsize=None)
    def curve(sid, cap):
        levels = np.arange(cap + 1)
        total = np.zeros(cap + 1)
        for m in mornings:
            fp, fr, _ = M.replay(m.get(sid, []), cap, levels)
            total += fp + fr
        return total / len(mornings)
    return curve


def evaluate(st, ev, snap, trips, train, test, b_sim, train_mornings=None, test_draws=None):
    """Score every policy on each test morning. By default the failure curves come
    from the recorded training mornings and each policy is replayed over the
    recorded test morning. censored.py passes filled-in demand instead:
    train_mornings, a list of event dicts for the curves, and test_draws,
    {day: [event dict, ...]}, scored one by one and averaged (each draw's total is
    kept in `by_draw`)."""
    curve = make_curve([M.morning(ev, d) for d in train] if train_mornings is None else train_mornings)
    rows, states = [], []
    for day in test:
        six, nine_pm = day + 6 * H, day - 24 * H + config.NIGHT_START * H
        s6, s21 = state_at(snap, trips, six), state_at(snap, trips, nine_pm)
        ids = st.index.intersection(s6.index).intersection(s21.index)
        cap = s6.usable[ids]
        st_d = st.loc[ids].assign(capacity=cap)
        # No overnight moves: 9pm state rolled to 6am with the night's trips
        b_none = pd.Series({i: int(M.replay(trips.events(i, nine_pm, six)[1], int(cap[i]),
                                            min(int(s21.bikes[i]), int(cap[i])))[2]) for i in ids})
        b_obs = s6.bikes[ids].astype(int)
        states.append(pd.DataFrame({"day": day, "station_id": ids, "usable_6am": cap.values,
                                    "bikes_9pm": s21.bikes[ids].values, "no_moves_6am": b_none.values,
                                    "observed_6am": b_obs.values,
                                    "phase3_simulated_6am": b_sim[day][ids].values}))
        # The operator's overnight effort: bikes dropped or picked up at a station, counting
        # only changes of MOVE_THRESHOLD or more (smaller ones are mostly bikes becoming
        # unrentable, or a trip on the other side of a snapshot). Every dropped bike was
        # picked up somewhere, so effort = the larger of drops and pickups.
        net = b_obs - b_none
        net = net[net.abs() >= config.MOVE_THRESHOLD]
        effort = int(max(net.clip(lower=0).sum(), -net.clip(upper=0).sum()))
        draws = [M.morning(ev, day)] if test_draws is None else test_draws[day]
        g = {i: curve(i, int(cap[i])) for i in ids}

        def score(policy, budget, y, moved=None):
            f = np.array([R.morning_failures(st_d, e, y) for e in draws])
            fp, fr = f.mean(axis=0) if len(draws) > 1 else f[0].tolist()
            moved = int((b_none - y).clip(lower=0).sum()) if moved is None else moved
            row = dict(day=day, policy=policy, budget=budget, stations=len(ids),
                       moved=moved, fail_pick=fp, fail_ret=fr)
            if len(draws) > 1:
                row["by_draw"] = f.sum(axis=1)
            rows.append(row)

        score("No overnight moves", 0, b_none)
        score("Actual 2025 operation", "operator", b_obs, moved=effort)
        for budget in BUDGETS:
            score("Fill to 50% rule", budget, R.rule_fill_half(st_d, b_none, budget))
            score("Optimised", budget, R.solve_plan(st_d, g, b_none, budget)[0])
        score("Optimised, operator's effort", "operator", R.solve_plan(st_d, g, b_none, effort)[0])
    df = pd.DataFrame(rows)
    df["failures"] = df.fail_pick + df.fail_ret
    states = pd.concat(states, ignore_index=True)
    states["operator_net"] = states.observed_6am - states.no_moves_6am
    return df, states


def policy_summary(df):
    actual = df[df.policy == "Actual 2025 operation"].set_index("day").failures
    df = df.assign(beats_actual=df.failures.values < actual.reindex(df.day).values)
    return (df.groupby(["policy", "budget"], sort=False)
            .agg(moved=("moved", "mean"), fail_pick=("fail_pick", "mean"),
                 fail_ret=("fail_ret", "mean"), failures=("failures", "mean"),
                 mornings_better_than_actual=("beats_actual", "sum"))
            .reset_index())


# --- 5. Operator moves by hour ---------------------------------------------------
def operator_moves(snap, trips, days, valet_ids):
    """Unexplained change between consecutive snapshots (bikes physically docked,
    minus net trips). Changes of MOVE_THRESHOLD bikes or more count as operator moves;
    smaller ones are mostly a trip landing on the other side of a snapshot."""
    s = snap.sort_values(["station_id", "t"])
    s = s.assign(prev_t=s.groupby("station_id").t.shift(), dphys=s.groupby("station_id").phys.diff())
    s = s.dropna(subset=["prev_t"])
    s = s[((s.t - s.prev_t) <= H) & s.t.dt.normalize().isin(days)]
    s["trips"] = np.concatenate([trips.net(sid, g.prev_t, g.t) for sid, g in s.groupby("station_id", sort=False)])
    s["moved"] = s.dphys - s.trips
    s["hour"] = s.t.dt.hour
    s["hours"] = (s.t - s.prev_t) / H
    s["group"] = np.where(s.station_id.isin(valet_ids), "3 valet-type stations", "37 modelled stations")
    big = s[s.moved.abs() >= config.MOVE_THRESHOLD]
    # Scale each hour by how much of it the archive covered (evening snapshots are sparser)
    covered = s.groupby(["group", "hour"]).hours.sum()
    n_st = s.groupby("group").station_id.nunique()
    share = covered / (n_st.reindex(covered.index.get_level_values(0)).values * len(days))
    agg = big.groupby(["group", "hour"]).moved.agg(added=lambda m: m[m > 0].sum(),
                                                   removed=lambda m: -m[m < 0].sum())
    agg = agg.reindex(share.index, fill_value=0)
    out = agg.div(len(days)).div(share, axis=0).assign(coverage=share).reset_index()
    return out


# --- Charts --------------------------------------------------------------------------
def plot_example(st, snap, trips, b_sim):
    sid, day = EXAMPLE
    six, ten = day + 6 * H, day + 10 * H
    s6 = state_at(snap, trips, six)
    b0, cap = s6.loc[sid]
    obs = snap[(snap.station_id == sid) & (snap.t >= six - MAX_AGE) & (snap.t <= ten)]
    times, deltas = trips.events(sid, six, ten)
    grid = pd.date_range(six, ten, freq="1min")
    fig, ax = plt.subplots(figsize=(8, 4.4))
    for start, color, ls, label, tag in [
            (b0, BLUE, "-", "Replay from the observed 6am count", f"observed 6am: {b0}"),
            (int(b_sim), ORANGE, "--", "Replay from Phase 3's simulated 6am count",
             f"Phase 3 simulated 6am: {int(b_sim)}")]:
        path = replay_path(times, deltas, cap, start, grid)
        ax.step(grid, path, where="post", color=color, ls=ls, lw=2, label=label)
        ax.annotate(tag, (grid[0], start), xytext=(4, 5), textcoords="offset points",
                    fontsize=8, color=INK2)
    ax.scatter(obs.t, obs.bikes, s=36, color=INK, ec=SURFACE, lw=1.2, zorder=4,
               label="Observed rentable bikes (archive snapshot)")
    ax.axhline(cap, color=AXIS, lw=1)
    ax.annotate(f"usable capacity: {cap}", (grid[0], cap), xytext=(4, 4), textcoords="offset points",
                fontsize=8, color=INK2)
    ax.set_ylim(-1, cap + 4)
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%-I:%M"))
    ax.set(xlabel=f"{day:%A %d %B %Y}, morning", ylabel="Bikes at the station")
    ax.set_title(f"{st.name[sid]}: replayed vs observed bike count")
    ax.legend(loc="upper right", bbox_to_anchor=(1, 0.9), fontsize=8)
    save(fig, "observed_validation_example.png")


def plot_moves(moves):
    groups = ["37 modelled stations", "3 valet-type stations"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharex=True)
    for ax, grp in zip(axes, groups):
        d = moves[moves.group == grp].set_index("hour").reindex(range(24), fill_value=0)
        ax.bar(d.index, d.added, color=BLUE, width=0.75, label="Bikes added by the operator")
        ax.bar(d.index, -d.removed, color=ORANGE, width=0.75, label="Bikes removed by the operator")
        ax.axhline(0, color=AXIS, lw=1)
        ax.set_xticks(range(0, 24, 3), [f"{h % 12 or 12}{'am' if h < 12 else 'pm'}" for h in range(0, 24, 3)])
        ax.grid(axis="x", visible=False)
        ax.set_title(grp, fontsize=11)
        ax.set_ylabel("Bikes per hour (average working day)")
    axes[0].legend(loc="lower left", fontsize=8)
    fig.suptitle("Bike count changes that trips don't explain, May–Oct 2025 working days",
                 x=0.01, ha="left", fontweight="bold", fontsize=12)
    save(fig, "observed_operator_moves.png")


def main():
    st, valet = M.load_study("downtown")
    ev = M.load_events(list(st.index) + list(valet.index))
    trips = Trips(ev)
    snap = load_snapshots(list(st.index) + list(valet.index))
    days = M.working_days()
    train, test = days[days.month <= 8], days[days.month >= 9]
    b_sim = {d: M.overnight_inventory(ev, st, d) for d in test}      # Phase 3's simulated 6am

    print("0. Archive coverage")
    cov, cap = coverage(st, snap, trips, days)
    cov.to_csv(config.TABLES / "observed_coverage.csv", header=["value"])
    cap.to_csv(config.TABLES / "observed_docks_2025.csv")
    print(cov.to_string())

    print("1. Validation: replay from the observed 6am count")
    v, starts = validate(st, snap, trips, test, b_sim)
    vs = validation_summary(v, starts)
    vs.round(4).to_csv(config.TABLES / "observed_validation.csv", header=["value"])
    print(vs.round(3).to_string())

    print("2-4. Policies from observed starting states")
    df, states = evaluate(st, ev, snap, trips, train, test, b_sim)
    df.to_csv(config.TABLES / "observed_by_night.csv", index=False)
    states.to_csv(config.TABLES / "observed_station_states.csv", index=False)
    s = policy_summary(df)
    s.round(3).to_csv(config.TABLES / "observed_results.csv", index=False)
    print(s.round(1).to_string(index=False))
    big = states[states.operator_net.abs() >= config.MOVE_THRESHOLD].groupby("day").operator_net
    print(f"operator overnight moves (9pm-6am, |change| >= {config.MOVE_THRESHOLD}) per night: "
          f"dropped {big.apply(lambda x: x.clip(lower=0).sum()).mean():.1f}, "
          f"picked up {big.apply(lambda x: -x.clip(upper=0).sum()).mean():.1f}; "
          f"stations per night {states.groupby('day').size().min()}-{states.groupby('day').size().max()}; "
          f"group total 9pm {states.groupby('day').bikes_9pm.sum().mean():.0f}, "
          f"6am without moves {states.groupby('day').no_moves_6am.sum().mean():.0f}, "
          f"6am observed {states.groupby('day').observed_6am.sum().mean():.0f}")

    print("5. Operator moves by hour")
    moves = operator_moves(snap, trips, list(days), set(valet.index))
    moves.round(2).to_csv(config.TABLES / "observed_operator_moves.csv", index=False)
    print(moves.groupby("group")[["added", "removed"]].sum().round(0).to_string())

    plot_example(st, snap, trips, b_sim[EXAMPLE[1]][EXAMPLE[0]])
    plot_moves(moves)


if __name__ == "__main__":
    main()

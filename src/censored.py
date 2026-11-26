"""Phase 4b: the demand the trip data misses, and whether the Phase 4 results survive it.

Recorded trips include only riders who found a bike or a free dock. While a
station is empty its pickups go unrecorded; while it is full, its returns do.
Those riders gave up or used a nearby station. The trips were recorded under the
operator's real 2025 station counts, so replaying them never charges that
operation for the riders it turned away, and never credits a plan for serving
them: observed.py's comparison leans toward what the operator actually did.

1. Time at the cap, measured: the share of 6-10am snapshots in which a station
   had no rentable bike (empty) or no free dock (full), by station and by time.
2. Fill-in. Each station's count is rebuilt minute by minute, 6-10am, forward
   from the previous snapshot and back from the next one with the recorded
   trips; a minute where only one says empty (full) counts half. Rates are
   estimated per station and FILL_SLOT-minute slot from the minutes the station
   was not empty (pickups) or not full (returns), scaled by how busy that
   morning was. Random pickups are then added during empty minutes and random
   returns during full minutes. Two versions bracket what a turned-away rider did:
     nothing removed:    each added pickup is a whole missing trip, so its return
                         is added too, at a destination and duration drawn from
                         that station's recorded trips. Nothing is taken away,
                         so a rider turned away from a full dock also keeps the
                         recorded return at the station they used instead.
     moved from nearby:  the rider used a modelled station within NEARBY_M, so
                         the first matching recorded event there within
                         NEARBY_MIN minutes is moved to the station they wanted.
                         Added events with no match are handled as above.
   observed.py's comparison is then rerun: failure curves from the filled-in
   training mornings, every policy scored on FILL_DRAWS filled-in versions of
   each test morning (the same draws in both versions). Training uses only the
   May-Aug mornings the archive covers, since without snapshots there is no way
   to tell when a station was capped, so the recorded version is rerun on the
   same mornings for a like-for-like comparison.

Outputs: outputs/tables/censored_*.csv, outputs/figures/censored_time_at_cap.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config
import morning as M
import observed as O
import routing
from eda import BLUE, ORANGE, INK2, save

H = pd.Timedelta(hours=1)
N_MIN = 240                                   # minutes 6:00-9:59
MIN64 = np.timedelta64(1, "m")
VERSIONS = ["Recorded", "Filled in, nothing removed", "Filled in, moved from nearby"]


# --- 1. Time at the cap, measured ------------------------------------------------
def time_at_cap(st, snap, days, test):
    """Share of 6-10am snapshots with no rentable bike / no free dock."""
    s = snap[snap.station_id.isin(st.index)]
    s = s.assign(day=s.t.dt.normalize())
    s = s[s.day.isin(days) & (s.t.dt.hour >= 6) & (s.t.dt.hour < 10)]
    s = s.assign(no_bike=s.bikes == 0, no_dock=s.docks == 0, test=s.day.isin(test),
                 slot=(s.t - s.day - 6 * H) // pd.Timedelta(minutes=config.FILL_SLOT))
    s["capped"] = s.no_bike | s.no_dock
    per = pd.DataFrame({
        "name": st.name,
        "no_bike_share": s.groupby("station_id").no_bike.mean(),
        "no_dock_share": s.groupby("station_id").no_dock.mean(),
        "no_bike_share_test": s[s.test].groupby("station_id").no_bike.mean(),
        "no_dock_share_test": s[s.test].groupby("station_id").no_dock.mean(),
    })
    by_slot = s.groupby("slot")[["no_bike", "no_dock"]].mean()
    by_slot.index = [f"{6 + k * config.FILL_SLOT // 60}:{k * config.FILL_SLOT % 60:02d}" for k in by_slot.index]
    sm = s.groupby(["day", "station_id"])[["no_bike", "no_dock", "capped"]].any()
    summary = {
        "snapshots": len(s), "mornings": s.day.nunique(), "station_mornings": len(sm),
        "no_bike_share": s.no_bike.mean(), "no_dock_share": s.no_dock.mean(),
        "capped_share": s.capped.mean(),
        "no_bike_share_test": s[s.test].no_bike.mean(), "no_dock_share_test": s[s.test].no_dock.mean(),
        "station_mornings_no_bike": sm.no_bike.mean(), "station_mornings_no_dock": sm.no_dock.mean(),
        "station_mornings_capped": sm.capped.mean(),
        "stations_capped_5pct_or_more": ((per.no_bike_share + per.no_dock_share) >= 0.05).sum(),
    }
    return per, by_slot, summary


# --- 2. Fill-in -----------------------------------------------------------------
def cap_minutes(st, snap, trips, days):
    """How empty and how full each station was at the start of each minute
    6:00-9:59, shape [day, station, minute], from two rebuilds of its count:
    forward (the previous snapshot rolled forward with the recorded trips, same
    rule as the replay) and backward (the next snapshot rolled back). They agree
    unless the operator moved bikes between the snapshots, at a time the data
    doesn't show (forward misses a drop until the next snapshot; backward counts
    it too early). A minute counts 1 if both say empty (full), 0.5 if one does."""
    empty = np.zeros((len(days), len(st), N_MIN))
    full = np.zeros_like(empty)
    for j, sid in enumerate(st.index):
        s = snap[snap.station_id == sid].sort_values("t")
        ts, bikes, usable = s.t.to_numpy(), s.bikes.to_numpy(), s.usable.to_numpy()
        for i, day in enumerate(days):
            grid = pd.date_range(day + 6 * H, periods=N_MIN, freq="1min").to_numpy()
            fe, ff = np.zeros(N_MIN, bool), np.zeros(N_MIN, bool)
            k = np.searchsorted(ts, grid, side="right") - 1
            for kk in np.unique(k[k >= 0]):
                at = k == kk
                t1 = ts[kk + 1] if kk + 1 < len(ts) else grid[-1] + MIN64
                times, deltas = trips.events(sid, ts[kk], t1)
                cap = int(usable[kk])
                path = O.replay_path(times, deltas, cap, min(int(bikes[kk]), cap), grid[at])
                fe[at], ff[at] = path == 0, path == cap
            n = np.searchsorted(ts, grid, side="left")      # next snapshot at or after the minute
            ok = n < len(ts)
            n = np.where(ok, n, 0)
            back = bikes[n] - trips.net(sid, grid, ts[n])
            be, bf = np.where(ok, back <= 0, fe), np.where(ok, back >= usable[n], ff)
            empty[i, j] = (fe.astype(float) + be) / 2   # astype: bool + bool would be OR
            full[i, j] = (ff.astype(float) + bf) / 2
    return empty, full


def minute_counts(ev, st, days):
    """Recorded pickups and returns per [day, station, minute], 6:00-9:59."""
    w = ev[ev.station_id.isin(st.index)]
    w = w.assign(day=w.time.dt.normalize())
    w = w[w.day.isin(days) & (w.time.dt.hour >= 6) & (w.time.dt.hour < 10)]
    i = w.day.map({d: k for k, d in enumerate(days)}).to_numpy()
    j = w.station_id.map({s: k for k, s in enumerate(st.index)}).to_numpy()
    m = ((w.time - w.day - 6 * H) // pd.Timedelta(minutes=1)).to_numpy()
    pick, ret = (np.zeros((len(days), len(st), N_MIN), int) for _ in range(2))
    p = w.d.to_numpy() < 0
    np.add.at(pick, (i[p], j[p], m[p]), 1)
    np.add.at(ret, (i[~p], j[~p], m[~p]), 1)
    return pick, ret


def demand_rate(count, capped):
    """Expected events per [day, station, minute]: the station's rate per
    uncapped minute in its FILL_SLOT slot (falling back to the hour, then the
    whole morning, when the slot has under an hour of uncapped time across the
    days), times that morning's busyness (recorded / expected events over its
    uncapped minutes). capped: 0-1 per minute (cap_minutes). Multiplied by
    `capped`, the rate is the unrecorded demand."""
    open_ = 1 - capped
    n, x = (count * open_).sum(axis=0), open_.sum(axis=0)
    lam = np.full(n.shape, np.nan)
    for width in (config.FILL_SLOT, 60, N_MIN):
        ns = n.reshape(len(n), -1, width).sum(2).repeat(width, 1)
        xs = x.reshape(len(x), -1, width).sum(2).repeat(width, 1)
        need = np.isnan(lam) & (xs >= (60 if width < N_MIN else 1))
        lam[need] = ns[need] / xs[need]
    lam = np.nan_to_num(lam)
    expected = (lam[None] * open_).sum(axis=(1, 2))
    busy = (count * open_).sum(axis=(1, 2)) / np.where(expected > 0, expected, 1)
    return lam[None] * busy[:, None, None]


def before_spells(count, capped, rate, window=15):
    """Recorded / expected events in the uncapped minutes up to `window` before
    each spell starts. Above 1 suggests spells begin in surges, so the slot
    average understates demand during them; but the events that empty or fill a
    station also make those minutes busy, so this is a hint, not a test."""
    on = capped > 0
    start = np.zeros_like(on)
    start[:, :, 1:] = on[:, :, 1:] & ~on[:, :, :-1]
    win = np.zeros_like(on)
    for k in range(1, window + 1):
        win[:, :, :-k] |= start[:, :, k:]
    win &= ~on
    return count[win].sum() / rate[win].sum()


def destinations(st, days):
    """Recorded trips leaving each station 6-10am: {(station, slot): (end_id, duration)},
    pooled over `days`, with hour and whole-morning pools as fallbacks."""
    t = pd.read_parquet(config.PROCESSED / f"trips_{config.TRIP_YEAR}.parquet",
                        columns=["start_id", "end_id", "start_time", "end_time"])
    t = t[t.start_id.isin(st.index)]
    day = t.start_time.dt.normalize()
    t = t[day.isin(days) & (t.start_time.dt.hour >= 6) & (t.start_time.dt.hour < 10)]
    minute = ((t.start_time - t.start_time.dt.normalize() - 6 * H) // pd.Timedelta(minutes=1)).to_numpy()
    dur = (t.end_time - t.start_time).to_numpy()
    pools = {}
    for width in (config.FILL_SLOT, 60, N_MIN):
        key = pd.MultiIndex.from_arrays([t.start_id.to_numpy(), minute // width])
        for (sid, k), idx in pd.Series(np.arange(len(t)), index=key).groupby(level=[0, 1]):
            pools[(width, sid, k)] = (t.end_id.to_numpy()[idx.values], dur[idx.values])
    return pools


def sample_destination(pools, sid, minute, rng):
    for width in (config.FILL_SLOT, 60, N_MIN):
        p = pools.get((width, sid, minute // width))
        if p is not None and (width == N_MIN or len(p[0]) >= 10):
            k = rng.integers(len(p[0]))
            return int(p[0][k]), p[1][k]
    return None, None


def nearby(st):
    """For each station, the other modelled stations within NEARBY_M, nearest first."""
    d = routing.distances(st.lat.to_numpy(), st.lon.to_numpy()) / config.ROAD_CIRCUITY * 1000
    ids = st.index.to_numpy()
    return {sid: [ids[k] for k in np.argsort(d[j]) if k != j and d[j, k] <= config.NEARBY_M]
            for j, sid in enumerate(ids)}


def fill(ev, st, days, empty, full, rng_seed, near):
    """FILL_DRAWS filled-in versions of every morning, in both versions.
    Returns {version: {day: [event dict per draw]}} and per-morning fill statistics."""
    pick, ret = minute_counts(ev, st, days)
    rate_pick, rate_ret = demand_rate(pick, empty), demand_rate(ret, full)
    mu_pick, mu_ret = rate_pick * empty, rate_ret * full
    check = {"pickups": before_spells(pick, empty, rate_pick), "returns": before_spells(ret, full, rate_ret)}
    pools = destinations(st, days)
    ids = st.index.to_numpy()
    in_study = set(ids)
    w = ev[ev.station_id.isin(in_study)]
    # Each morning's recorded events, and their positions by (station, sign); ev is
    # sorted by station then time, so each group's times are in order
    recs = {}
    for day in days:
        rec = w[(w.time >= day + 6 * H) & (w.time < day + 10 * H)].reset_index(drop=True)
        pos = {key: g.index.to_numpy() for key, g in rec.groupby(["station_id", "d"])}
        recs[day] = rec, pos, {key: rec.time.to_numpy()[p] for key, p in pos.items()}
    out = {v: {d: [] for d in days} for v in VERSIONS[1:]}
    stats = []
    for k in range(config.FILL_DRAWS):
        rng = np.random.default_rng([rng_seed, k])
        n_pick, n_ret = rng.poisson(mu_pick), rng.poisson(mu_ret)
        for i, day in enumerate(days):
            six, ten = (day + 6 * H).to_datetime64(), (day + 10 * H).to_datetime64()
            rec, pos, times = recs[day]
            # Added events: (station, time, sign, destination, return time)
            added = []
            for n, sign in ((n_pick[i], -1), (n_ret[i], 1)):
                for j, m in zip(*np.nonzero(n)):
                    for _ in range(n[j, m]):
                        t = six + ((m + rng.random()) * 60e9).astype("timedelta64[ns]")
                        end, dur = sample_destination(pools, ids[j], m, rng) if sign < 0 else (None, None)
                        added.append((ids[j], t, sign, end, None if end is None else t + dur))
            added.sort(key=lambda a: a[1])
            for version in VERSIONS[1:]:
                used = {key: np.zeros(len(v), bool) for key, v in times.items()}
                extra, moved, trips_added = [], 0, 0
                for sid, t, sign, end, t_end in added:
                    extra.append((sid, t, sign))
                    matched = False
                    if version == VERSIONS[2]:
                        for nb in near[sid]:
                            tt = times.get((nb, sign))
                            if tt is None:
                                continue
                            a, b = np.searchsorted(tt, [t, t + np.timedelta64(config.NEARBY_MIN, "m")], side="right")
                            free = np.flatnonzero(~used[(nb, sign)][a:b])
                            if len(free):
                                used[(nb, sign)][a + free[0]] = True
                                matched = True
                                break
                    moved += matched
                    if sign < 0 and not matched and end in in_study and t_end < ten:
                        extra.append((end, t_end, 1))     # the missing trip's return
                        trips_added += 1
                keep = np.ones(len(rec), bool)
                for key, u in used.items():
                    keep[pos[key][u]] = False
                e = pd.concat([rec[keep][["station_id", "time", "d"]],
                               pd.DataFrame(extra, columns=["station_id", "time", "d"])], ignore_index=True)
                e = e.sort_values("time", kind="stable")
                out[version][day].append({s: g.d.to_numpy() for s, g in e.groupby("station_id")})
                stats.append(dict(version=version, draw=k, day=day, recorded=len(rec),
                                  added_pickups=int(n_pick[i].sum()), added_returns=int(n_ret[i].sum()),
                                  moved_from_nearby=moved, trip_returns_added=trips_added,
                                  removed=int((~keep).sum())))
    expected = pd.DataFrame({"recorded_pickups": pick.sum(axis=(0, 2)) / len(days),
                             "recorded_returns": ret.sum(axis=(0, 2)) / len(days),
                             "missing_pickups": mu_pick.sum(axis=(0, 2)) / len(days),
                             "missing_returns": mu_ret.sum(axis=(0, 2)) / len(days)}, index=ids)
    return out, pd.DataFrame(stats), expected, check


def ideal_fill(curve, sid, cap):
    """Middle of the best starting levels, as a share of capacity."""
    g = curve(sid, cap)
    best = np.flatnonzero(g <= g.min() + 1e-9)
    return (best[0] + best[-1]) / 2 / cap if cap else np.nan


# --- Chart ------------------------------------------------------------------------
def plot_time_at_cap(per, by_slot):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 7.5), gridspec_kw={"width_ratios": [1, 1.3]})
    x = np.arange(len(by_slot))
    a1.plot(x, 100 * by_slot.no_bike, color=ORANGE, lw=2, marker="o", ms=4, label="No rentable bike")
    a1.plot(x, 100 * by_slot.no_dock, color=BLUE, lw=2, marker="o", ms=4, label="No free dock")
    a1.set_xticks(x[::4], by_slot.index[::4])
    a1.set(xlabel="Time of morning (15-minute slots)", ylabel="Share of station snapshots (%)", ylim=(0, None))
    a1.set_title("When: all 37 stations", fontsize=11)
    a1.legend(loc="upper left", fontsize=9)
    p = per.assign(total=per.no_bike_share + per.no_dock_share).sort_values("total")
    pos = np.arange(len(p))
    a2.barh(pos, 100 * p.no_bike_share, color=ORANGE, height=0.75, label="No rentable bike")
    a2.barh(pos, 100 * p.no_dock_share, left=100 * p.no_bike_share, color=BLUE, height=0.75,
            label="No free dock")
    a2.set_yticks(pos, [n[:34] for n in p.name], fontsize=7.5)
    a2.grid(axis="y", visible=False)
    a2.set_xlabel("Share of 6–10am snapshots (%)")
    a2.set_title("Where: each station", fontsize=11)
    fig.suptitle("Downtown stations with no bike or no dock, working-day mornings, May–Oct 2025\n"
                 "Measured from station snapshots; riders turned away then are missing from the trip data",
                 x=0.01, ha="left", fontweight="bold", fontsize=12, color=INK2)
    save(fig, "censored_time_at_cap.png")


def main():
    st, valet = M.load_study("downtown")
    ev = M.load_events(st.index)
    trips = O.Trips(ev)
    snap = O.load_snapshots(st.index)
    days = M.working_days()
    train, test = days[days.month <= 8], days[days.month >= 9]

    print("1. Time at the cap, measured from snapshots")
    per, by_slot, summary = time_at_cap(st, snap, days, test)
    plot_time_at_cap(per, by_slot)
    by_slot.round(4).to_csv(config.TABLES / "censored_cap_by_slot.csv", index_label="slot_start")
    print(pd.Series(summary).round(3).to_string())

    print("2. Fill in the missing demand and rerun the Phase 4 comparison")
    times = pd.Series(np.sort(snap.t.unique()))
    cov = O.covered_mornings(times, days)
    train_c, test_c = train[cov[train].values], test[cov[test].values]
    assert len(test_c) == len(test), "every test morning needs snapshots"
    print(f"training mornings with snapshots: {len(train_c)} of {len(train)}")
    near = nearby(st)
    filled, stats, expected = {}, [], {}
    for period, d, seed in (("train", train_c, config.FILL_SEED), ("test", test_c, config.FILL_SEED + 1)):
        empty, full = cap_minutes(st, snap, trips, d)
        f, s, expected[period], check = fill(ev, st, d, empty, full, seed, near)
        filled[period] = f
        for kind, ratio in check.items():
            summary[f"before_spell_recorded_vs_expected_{kind}_{period}"] = ratio
        stats.append(s.assign(period=period))
        per[f"rebuilt_empty_share_{period}"] = pd.Series(empty.mean(axis=(0, 2)), index=st.index)
        per[f"rebuilt_full_share_{period}"] = pd.Series(full.mean(axis=(0, 2)), index=st.index)
        summary[f"rebuilt_empty_share_{period}"] = empty.mean()
        summary[f"rebuilt_full_share_{period}"] = full.mean()
    stats = pd.concat(stats, ignore_index=True)
    # Calibration: snapshots sample each station at times unrelated to its state, so
    # their shares are unbiased for the time spent empty or full; the rebuild should match
    for kind, snap_col in (("empty", "no_bike_share_test"), ("full", "no_dock_share_test")):
        summary[f"rebuilt_vs_snapshot_station_gap_{kind}_test"] = (
            per[f"rebuilt_{kind}_share_test"] - per[snap_col]).abs().mean()
    for c in expected["test"]:
        per[f"{c}_per_test_morning"] = expected["test"][c]
    fill_summary = (stats.groupby(["period", "version"])
                    [["recorded", "added_pickups", "added_returns", "moved_from_nearby",
                      "trip_returns_added", "removed"]].mean())
    fill_summary.round(2).to_csv(config.TABLES / "censored_fill.csv")
    print(fill_summary.round(1).to_string())

    b_sim = {d: M.overnight_inventory(ev, st, d) for d in test}
    results, med_cap = [], None
    for version in VERSIONS:
        if version == "Recorded":
            train_m, draws = [M.morning(ev, d) for d in train_c], None
        else:
            train_m = [m for d in train_c for m in filled["train"][version][d]]
            draws = filled["test"][version]
        df, states = O.evaluate(st, ev, snap, trips, train_c, test, b_sim, train_m, draws)
        s = O.policy_summary(df)
        if "by_draw" in df:  # range over draws of the 43-morning average
            per_draw = df.groupby(["policy", "budget"], sort=False).by_draw.apply(lambda x: np.mean(np.stack(x), axis=0))
            s["failures_draw_min"] = per_draw.apply(np.min).values
            s["failures_draw_max"] = per_draw.apply(np.max).values
        results.append(s.assign(version=version))
        print(f"\n{version}")
        print(s.round(1).to_string(index=False))
        # Each station's best 6am fill, at its median usable capacity on test mornings
        if med_cap is None:
            med_cap = states.groupby("station_id").usable_6am.median().round().astype(int)
        curve = O.make_curve(train_m)
        per[f"ideal_fill_{version}"] = pd.Series({i: ideal_fill(curve, i, int(med_cap[i])) for i in med_cap.index})

    res = pd.concat(results, ignore_index=True)
    res = res[["version"] + [c for c in res.columns if c != "version"]]
    res.round(3).to_csv(config.TABLES / "censored_results.csv", index=False)
    rec_fill = per["ideal_fill_Recorded"]
    for v in VERSIONS[1:]:
        summary[f"ideal_fill_corr_{v}"] = rec_fill.corr(per[f"ideal_fill_{v}"])
        summary[f"ideal_fill_mean_shift_{v}"] = (per[f"ideal_fill_{v}"] - rec_fill).mean()
    per.index.name = "station_id"
    per.round(4).to_csv(config.TABLES / "censored_stations.csv")
    pd.Series(summary).to_csv(config.TABLES / "censored_summary.csv", header=["value"])
    print(pd.Series(summary).round(3).to_string())


if __name__ == "__main__":
    main()

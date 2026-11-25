"""Phase 2: exploratory analysis. Answers the EDA questions in docs/PLAN.md.

Outputs:
  outputs/figures/*.png                         charts used in the README
  outputs/tables/station_morning_profile.csv    per-station morning stats (Phase 3 input)
  outputs/tables/eda_summary.csv                headline numbers quoted in the README
  outputs/tables/swing_vs_capacity.csv          morning vs 24h swing check, 37 modelled stations
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

import config
import morning as M  # Phase 3 helpers: same events and station set as the model

# --- Chart style (reference palette, light mode) -----------------------------
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#c3c2b7"
# Diverging: red = station loses bikes, grey = balanced, blue = station gains bikes
DIVERGING = LinearSegmentedColormap.from_list(
    "net", ["#a32f2f", "#e34948", "#f0efec", "#3987e5", "#184f95"])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 10,
    "text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": AXIS, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "lines.linewidth": 2, "legend.frameon": False,
})

summary = {}  # headline numbers for the README


def save(fig, name):
    fig.tight_layout()
    fig.savefig(config.FIGURES / name, dpi=150)
    plt.close(fig)
    print(f"  saved {name}")


# --- Data --------------------------------------------------------------------
def load():
    t = pd.read_parquet(config.PROCESSED / f"trips_{config.TRIP_YEAR}.parquet",
                        columns=["start_id", "end_id", "start_time", "end_time", "user_type"])
    t = t[t.start_time.dt.year == config.TRIP_YEAR]  # a few trips start on 31 Dec 2024
    holidays = pd.to_datetime(config.HOLIDAYS_2025)
    t["date"] = t.start_time.dt.normalize()
    t["workday"] = (t.start_time.dt.day_of_week < 5) & ~t.date.isin(holidays)
    t["season"] = t.start_time.dt.month.isin(config.SEASON_MONTHS)
    t["hour"] = t.start_time.dt.hour
    stations = pd.read_csv(config.PROCESSED / "stations.csv").set_index("station_id")
    study = pd.read_csv(config.PROCESSED / "study_stations.csv").set_index("station_id")
    return t, stations, study


# --- Q1, Q2: when and who ----------------------------------------------------
def monthly(t):
    m = t.groupby(t.start_time.dt.month).size()
    fig, ax = plt.subplots(figsize=(8, 3.6))
    colors = [BLUE if k in config.SEASON_MONTHS else GREY for k in m.index]
    ax.bar(m.index, m.values / 1e3, color=colors, width=0.8)
    ax.set_xticks(range(1, 13), ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
                                 "Sep", "Oct", "Nov", "Dec"])
    ax.set_ylabel("Trips (thousands)")
    ax.grid(axis="x", visible=False)
    peak = m.idxmax()
    ax.annotate(f"{m.max() / 1e6:.2f}M", (peak, m.max() / 1e3), ha="center", va="bottom",
                color=INK2, xytext=(0, 3), textcoords="offset points")
    ax.set_title("Trips per month, 2025 (study season May–Oct in blue)")
    save(fig, "trips_by_month.png")
    summary["trips_2025"] = int(m.sum())
    summary["season_share"] = round(m[list(config.SEASON_MONTHS)].sum() / m.sum(), 3)
    summary["peak_month_trips"] = int(m.max())


def day_of_week(t):
    s = t[t.season]
    per_day = s.groupby("date").size()
    dow = per_day.groupby(per_day.index.day_of_week).mean()
    hol = per_day[per_day.index.isin(pd.to_datetime(config.HOLIDAYS_2025))].mean()
    fig, ax = plt.subplots(figsize=(7, 3.4))
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Holidays"]
    vals = list(dow.values) + [hol]
    ax.bar(labels, np.array(vals) / 1e3, color=[BLUE] * 5 + [GREY] * 3, width=0.75)
    ax.set_ylabel("Average trips per day (thousands)")
    ax.grid(axis="x", visible=False)
    ax.set_title("Average daily trips by day of week, May–Oct 2025")
    save(fig, "trips_by_weekday.png")
    summary["avg_trips_workday_season"] = int(per_day[s.groupby("date").workday.first()].mean())
    summary["avg_trips_weekend_season"] = int(per_day[~s.groupby("date").workday.first()].mean())


def hourly_by_user(t):
    s = t[t.season]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, (flag, title) in zip(axes, [(True, "Working days"),
                                        (False, "Weekends and holidays")]):
        d = s[s.workday == flag]
        n_days = d.date.nunique()
        prof = d.groupby(["hour", "user_type"], observed=True).size().unstack() / n_days
        for col, color in [("Member", BLUE), ("Casual", ORANGE)]:
            ax.plot(prof.index, prof[col], color=color)
            ax.annotate(col, (23, prof[col].iloc[-1]), color=INK2, xytext=(4, 0),
                        textcoords="offset points", va="center")
        if flag:
            lo, hi = config.MORNING_WINDOW
            ax.axvspan(lo, hi, color=GRID, alpha=0.6, lw=0)
            ax.text((lo + hi) / 2, ax.get_ylim()[1] * 0.02, "6–10am\nwindow",
                    ha="center", va="bottom", color=INK2, fontsize=8)
        ax.set_title(title, fontsize=11)
        ax.set_xticks([0, 6, 12, 18, 23], ["0h", "6h", "12h", "18h", "23h"])
        ax.set_xlim(0, 25.5)
    axes[0].set_ylabel("Trips started per hour (avg)")
    fig.suptitle("Hourly trip starts by rider type, May–Oct 2025", x=0.01, ha="left",
                 fontweight="bold", fontsize=12)
    save(fig, "trips_by_hour_user.png")

    w = s[s.workday]
    prof = w.groupby("hour").size() / w.date.nunique()
    summary["workday_peak_hour"] = int(prof.idxmax())
    summary["member_share_workday_am"] = round(
        (w[w.hour.between(6, 9)].user_type == "Member").mean(), 3)
    summary["member_share_all"] = round((t.user_type == "Member").mean(), 3)

    # Check: holidays look like weekends, not like working days
    h = s[s.date.isin(pd.to_datetime(config.HOLIDAYS_2025))]
    am_share = lambda d: d.hour.between(7, 8).mean()  # noqa: E731
    summary["am_7_9_share_workday"] = round(am_share(s[s.workday]), 3)
    summary["am_7_9_share_holiday"] = round(am_share(h), 3)
    summary["am_7_9_share_weekend"] = round(am_share(s[~s.workday & ~s.date.isin(h.date)]), 3)


# --- Q3: where ---------------------------------------------------------------
def top_stations(t, stations, study):
    w = t[t.season & t.workday]
    n_days = w.date.nunique()
    per_day = (w.start_id.value_counts().add(w.end_id.value_counts(), fill_value=0)
               / n_days).sort_values(ascending=False)
    top = per_day.head(20)[::-1]
    # Stations gone from today's feed: use their 2025 trip-data name, marked "removed"
    gone = pd.read_csv(config.TABLES / "stations_missing_from_gbfs.csv", index_col="start_id")
    names = stations.name.reindex(top.index).fillna(gone.name.reindex(top.index).str.slice(0, 34) + " †")
    colors = [BLUE if i in study.index else GREY for i in top.index]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(range(len(top)), top.values, color=colors, height=0.75)
    ax.set_yticks(range(len(top)), [f"{n[:38]}" for n in names])
    ax.set_xlabel("Trip starts + ends per working day (avg)")
    ax.grid(axis="y", visible=False)
    ax.scatter([], [], c=BLUE, marker="s", label="Study station")
    ax.scatter([], [], c=GREY, marker="s", label="Not in study set")
    ax.legend(loc="lower right")
    ax.text(0, -0.12, "† not in the current station feed (seasonal island station or removed), "
            "so it cannot be studied", transform=ax.transAxes, fontsize=8, color=INK2)
    ax.set_title("20 busiest stations, May–Oct 2025 working days")
    save(fig, "top_stations.png")
    summary["study_in_top20"] = int(sum(i in study.index for i in top.index))


# --- Q4: net flow by hour ----------------------------------------------------
def hourly_net_flow(t, study):
    """Average arrivals minus departures per station per hour, season working days."""
    w = t[t.season & t.workday]
    n_days = w.date.nunique()
    dep = w[w.start_id.isin(study.index)].groupby(["start_id", "hour"]).size()
    arr_mask = t.end_id.isin(study.index) & t.season & t.workday  # arrival by end hour
    arr = t[arr_mask].groupby(["end_id", t.loc[arr_mask, "end_time"].dt.hour]).size()
    dep.index.names = arr.index.names = ["station_id", "hour"]
    net = (arr.sub(dep, fill_value=0) / n_days).unstack(fill_value=0).reindex(
        index=study.index, columns=range(24), fill_value=0)
    return net, n_days


def heatmap(net, study):
    lo, hi = config.MORNING_WINDOW
    order = net.loc[:, lo:hi - 1].sum(axis=1).sort_values().index
    data = net.loc[order]
    cap = 20
    fig, ax = plt.subplots(figsize=(10, 9))
    im = ax.imshow(data.clip(-cap, cap), aspect="auto", cmap=DIVERGING, vmin=-cap, vmax=cap)
    ax.set_yticks(range(len(order)), [study.name[i][:34] for i in order], fontsize=8)
    ax.set_xticks(range(0, 24, 2), [f"{h}h" for h in range(0, 24, 2)])
    ax.grid(False)
    for x in (lo - 0.5, hi - 0.5):
        ax.axvline(x, color=INK2, lw=0.8, ls="--")
    cb = fig.colorbar(im, ax=ax, shrink=0.5, pad=0.02)
    cb.set_label("Net bikes per hour (arrivals − departures)\ncolour capped at ±20", color=INK2)
    cb.outline.set_visible(False)
    ax.set_title("When each study station gains (blue) or loses (red) bikes\n"
                 "Average working day, May–Oct 2025; sorted by 6–10am net flow")
    save(fig, "net_flow_heatmap.png")


def am_vs_pm(net, study):
    a0, a1 = config.MORNING_WINDOW
    p0, p1 = config.PM_WINDOW
    am = net.loc[:, a0:a1 - 1].sum(axis=1)
    pm = net.loc[:, p0:p1 - 1].sum(axis=1)
    lim = 70
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.axhline(0, color=AXIS, lw=1)
    ax.axvline(0, color=AXIS, lw=1)
    inside = (am.abs() <= lim) & (pm.abs() <= lim)
    ax.scatter(am[inside], pm[inside], s=40, color=BLUE, ec=SURFACE, lw=1.5, zorder=3)
    # Off-scale stations listed in a note instead of squeezed onto the border
    off = [f"{study.name[i]}: AM {am[i]:+.0f}, PM {pm[i]:+.0f}" for i in am.index[~inside]]
    if off:
        ax.text(lim, -lim + 12, "Off the scale (fills AM, empties PM):\n" + "\n".join(off),
                ha="right", va="bottom", fontsize=8, color=INK2)
    for i in pd.concat([am[inside].nsmallest(2), pm[inside].nlargest(1)]).index:
        ax.annotate(study.name[i][:26], (am[i], pm[i]), xytext=(6, -2),
                    textcoords="offset points", fontsize=8, color=INK2)
    ax.set(xlim=(-lim - 5, lim + 5), ylim=(-lim - 5, lim + 5),
           xlabel="Morning net flow, 6–10am (bikes per day)",
           ylabel="Evening net flow, 3–7pm (bikes per day)")
    ax.text(lim, lim, "fills all day", ha="right", va="top", color=MUTED, fontsize=8)
    ax.text(-lim, -lim, "empties all day", ha="left", va="bottom", color=MUTED, fontsize=8)
    ax.text(lim, -lim, "fills AM, empties PM", ha="right", va="bottom", color=MUTED, fontsize=8)
    ax.text(-lim, lim, "empties AM, fills PM", ha="left", va="top", color=MUTED, fontsize=8)
    ax.set_title("Morning vs evening imbalance at the 40 study stations")
    save(fig, "am_vs_pm_net_flow.png")
    summary["corr_am_pm"] = round(am.corr(pm), 2)
    summary["n_reverse"] = int(((am > 2) & (pm < -2)).sum() + ((am < -2) & (pm > 2)).sum())
    return am, pm


# --- Q5, Q6: stability and whether overnight moves can fix it -----------------
def morning_days(t, study):
    """Per station and working day: net flow and 'swing' during the morning window.

    Swing = highest minus lowest point of the running bike count (starting at 0).
    If the swing exceeds capacity, no starting inventory avoids a failure that
    morning, so overnight rebalancing alone cannot fix it.
    """
    lo, hi = config.MORNING_WINDOW
    w = t[t.season & t.workday]
    dep = w[w.start_id.isin(study.index) & w.hour.between(lo, hi - 1)]
    arr_m = (t.season & t.workday & t.end_id.isin(study.index)
             & t.end_time.dt.hour.between(lo, hi - 1) & (t.end_time.dt.date == t.start_time.dt.date))
    arr = t[arr_m]
    ev = pd.concat([
        pd.DataFrame({"station_id": dep.start_id, "time": dep.start_time, "d": -1}),
        pd.DataFrame({"station_id": arr.end_id, "time": arr.end_time, "d": 1}),
    ]).sort_values(["station_id", "time"])
    ev["date"] = ev.time.dt.normalize()
    ev["cum"] = ev.groupby(["station_id", "date"]).d.cumsum()
    g = ev.groupby(["station_id", "date"]).cum
    days = pd.DataFrame({"net": g.last(),
                         "swing": g.max().clip(lower=0) - g.min().clip(upper=0)})
    # Include days with no events at a station as zero (rare at these stations)
    all_days = pd.MultiIndex.from_product([study.index, w.date.unique()],
                                          names=["station_id", "date"])
    days = days.reindex(all_days, fill_value=0)
    days["capacity"] = study.capacity.reindex(days.index.get_level_values(0)).values
    days["swing_gt_cap"] = days.swing > days.capacity
    return days


def stability_and_feasibility(days, study):
    st = days.groupby("station_id").agg(
        net_mean=("net", "mean"), net_p10=("net", lambda x: x.quantile(0.1)),
        net_med=("net", "median"), net_p90=("net", lambda x: x.quantile(0.9)),
        swing_med=("swing", "median"), share_swing_gt_cap=("swing_gt_cap", "mean"))
    st = st.join(study[["name", "capacity"]])
    order = st.net_med.sort_values().index
    st = st.loc[order]
    y = np.arange(len(st))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 9), sharey=True,
                                 gridspec_kw={"width_ratios": [3, 2]})
    a1.hlines(y, st.net_p10.clip(-80, 80), st.net_p90.clip(-80, 80), color="#86b6ef", lw=4)
    a1.scatter(st.net_med.clip(-80, 80), y, color=BLUE, s=24, zorder=3, ec=SURFACE, lw=1)
    a1.axvline(0, color=AXIS, lw=1)
    for yi, (_, r) in zip(y, st.iterrows()):  # say the true value for off-scale stations
        if r.net_med > 80:
            a1.annotate(f"median +{r.net_med:.0f} →", (80, yi), xytext=(-6, 0),
                        textcoords="offset points", ha="right", va="center", fontsize=8,
                        color=INK2)
    a1.set_yticks(y, [n[:34] for n in st.name], fontsize=8)
    a1.set_xlim(-85, 85)
    a1.set_xlabel("Net bikes gained 6–10am\n(dot = median day, bar = 10th–90th percentile;\n"
                  "values beyond ±80 drawn at the edge)")
    a1.set_title("How much the morning imbalance varies day to day", fontsize=11)
    a1.grid(axis="y", visible=False)
    a2.barh(y, st.share_swing_gt_cap * 100, color=BLUE, height=0.7)
    a2.set_xlim(0, 100)
    a2.set_xlabel("% of mornings where the swing exceeds dock capacity")
    a2.set_title("Mornings no overnight plan can fix", fontsize=11)
    a2.grid(axis="y", visible=False)
    for yi, v in zip(y, st.share_swing_gt_cap * 100):
        if v >= 10:
            a2.annotate(f"{v:.0f}%", (v, yi), xytext=(3, 0), textcoords="offset points",
                        va="center", fontsize=8, color=INK2)
    fig.suptitle("Study stations, May–Oct 2025 working days, 6–10am", x=0.01, ha="left",
                 fontweight="bold", fontsize=12)
    save(fig, "morning_stability_feasibility.png")
    summary["stations_unfixable_majority"] = int((st.share_swing_gt_cap > 0.5).sum())
    summary["stations_unfixable_any10"] = int((st.share_swing_gt_cap >= 0.1).sum())
    return st


def swing_vs_capacity():
    """At the 37 modelled stations, the share of working days on which the swing
    exceeds dock capacity, in three windows:
      am       6-10am, the window the overnight plan protects
      day      the calendar day, 0-24h
      6am_6am  6am the previous day to 6am, the window the no-rebalancing
               baseline replays (rebalance.py)
    A swing above capacity means the recorded trips could not all have happened
    without bikes being moved during that window (daytime vans or valet)."""
    st, _ = M.load_study("downtown")
    ev = M.load_events(st.index)
    days = M.working_days()
    lo, _ = config.MORNING_WINDOW
    share = st[["name", "capacity"]].assign(
        share_am=M.swing_exceeds_capacity(ev, st, days),
        share_day=M.swing_exceeds_capacity(ev, st, days, (0, 24)),
        share_6am_6am=M.swing_exceeds_capacity(ev, st, days, (lo - 24, lo)))
    share.round(3).to_csv(config.TABLES / "swing_vs_capacity.csv")
    # Every station has the same days, so the mean over stations is the station-day share
    summary["am_station_mornings_fit_37"] = round(1 - share.share_am.mean(), 3)
    summary["day_station_days_swing_gt_cap_37"] = round(share.share_day.mean(), 3)
    summary["day_stations_gt_cap_over_10pct"] = int((share.share_day > 0.1).sum())
    summary["6am_6am_station_days_swing_gt_cap_37"] = round(share.share_6am_6am.mean(), 3)


def main():
    print("Loading")
    t, stations, study = load()
    print("Charts")
    monthly(t)
    day_of_week(t)
    hourly_by_user(t)
    top_stations(t, stations, study)
    net, n_days = hourly_net_flow(t, study)
    summary["season_workdays"] = n_days
    heatmap(net, study)
    am, pm = am_vs_pm(net, study)
    days = morning_days(t, study)
    st = stability_and_feasibility(days, study)
    st["am_net_avg"], st["pm_net_avg"] = am, pm
    st.round(2).to_csv(config.TABLES / "station_morning_profile.csv")
    swing_vs_capacity()
    pd.Series(summary).to_csv(config.TABLES / "eda_summary.csv", header=["value"])
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

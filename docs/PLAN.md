# Project plan: Toronto Bike Share overnight rebalancing

## The business question

Every weekday morning, commuters empty some downtown stations and fill others.
A rider who finds a station empty cannot start a trip. One who finds it full
cannot end a trip. Operators move bikes overnight with vans to prevent this.

**Question:** With a limited overnight van budget, which bikes should go where,
and in what order, to minimise failed pickups and returns the next morning?
How much better is that than doing nothing, or than a simple rule of thumb?

## Pipeline

| Phase | Script | Output |
|---|---|---|
| 1 Data | `src/download.py`, `src/clean.py` | `data/processed/trips.parquet`, `stations.csv`, data-issues log |
| 2 EDA | `src/eda.py` | charts in `outputs/figures/`, findings in README |
| 3a Overnight plan + evaluation | `src/morning.py`, `src/rebalance.py` | target inventory per station, failures on held-out days |
| 3b Van route | `src/routing.py` | stop sequence and load for one cluster |
| 3c Whole-night routing | `src/multivan.py` | balanced van tours for the full plan |
| 3d Wider network | `src/rebalance.py wide`, `src/multivan.py wide` | same models on the 145 busiest stations |
| 4 Check against observed counts | `src/snapshots.py`, `src/observed.py` | replay validated against 2025 station counts; policies, including the operator's actual practice, scored from observed starting states |

`run_all.sh` runs the pipeline end to end.

## EDA questions (Phase 2)

Each question feeds a later decision.

1. **When are trips taken?** Volume by hour, weekday vs weekend, and month.
   This sets the time window to protect. Expectation to test: a weekday 6–10am
   commuter peak, with the most trips from May to October.
2. **Who rides when?** Members vs casual users by hour and day. If members drive
   the weekday peaks, the imbalance should repeat from day to day, which is what
   makes an overnight plan possible.
3. **Where are trips concentrated?** Busiest stations, and the share of all
   trips that the top 40 downtown stations account for. This justifies the
   study subset.
4. **Which stations empty out and which fill up?** Weekday net flow
   (arrivals minus departures) per station by hour. We expect it to flip
   between the morning and evening peaks.
5. **How stable is the morning imbalance?** The spread of each station's
   morning net flow across days. A stable pattern means a fixed overnight
   target works. A volatile one means each station needs a buffer.
6. **Can overnight moves fix it?** Compare each station's typical morning
   swing with its dock capacity. If the swing is larger than the capacity, no
   starting level prevents failures, and those stations need daytime
   rebalancing. This shows where the model stops being useful.
7. **Data quality.** Missing or unknown station IDs, stations in the trips that
   are missing from today's GBFS feed, impossible durations, and duplicates.

## Key modelling inputs, and an honest limitation

- **Morning demand scenarios.** Each historical weekday morning in the training
  period is one scenario: the actual sequence of departures and arrivals at each
  station.
- **Failure function g_i(y).** For station i, start at y bikes, replay every
  scenario, and count pickups that find the station empty and returns that find
  it full. g_i(y) is the average over scenarios, computed for every y = 0..C_i.
  It comes directly from the data, so the model does not need a demand
  distribution.
- **Limitation 1: censored demand.** Trip data records only trips that happened.
  Riders turned away by an empty station leave no record, so true demand at
  stations that often run empty is underestimated. Results will be reported as
  failures on the trips we can see. That count is a likely undercount, not a
  lower bound: most missing riders were turned away, which hides failures, but
  a missing rider can also hide a success that would have prevented one (an
  unrecorded pickup frees a dock for a recorded return). Failures avoided is
  therefore an estimate, not a bound in either direction.
- **Limitation 2: no inventory history.** The open data has no historical count
  of bikes per station, so the overnight starting inventory b_i must be
  estimated. Options are listed under "Decisions for review" below.
  *Update (Phase 4):* an unofficial community archive of the live feed does
  cover 2025, about every 16 minutes. Phase 4 uses it to validate the replay
  and to start each policy from the observed state.
- **Stations treated independently.** In the replay, a failed pickup at
  station i does not cancel the matching arrival at station j. This is a common
  simplification and is stated as such.

## Formulation 1: overnight inventory repositioning (mixed-integer program)

**Decision:** how many bikes each station should hold at 6am, and how many to
pick up or drop off overnight to get there.

Sets and data

- S: the 40 study stations. C_i: usable capacity, the GBFS dock count minus
  `CAPACITY_BUFFER` unusable docks (0 by default; 1 and 2 as a sensitivity).
- b_i: estimated inventory at the start of the night.
- g_i(y): expected morning failures if station i starts at y bikes (from data).
- B: overnight handling budget (bikes moved). λ: small cost per bike moved, so
  bikes are not moved without a benefit.

Variables

- z_{i,y} ∈ {0,1}: 1 if station i starts the morning with exactly y bikes.
- p_i, q_i ∈ ℤ≥0: bikes picked up from / dropped at station i.

Model

```
min   Σ_i Σ_y g_i(y) · z_{i,y}  +  λ · Σ_i p_i

s.t.  Σ_y z_{i,y} = 1                        ∀ i     (one starting level per station)
      Σ_y y · z_{i,y} = b_i − p_i + q_i      ∀ i     (inventory balance)
      p_i ≤ b_i                              ∀ i     (cannot remove more than are there)
      Σ_i p_i = Σ_i q_i                              (vans only move bikes; fleet conserved)
      Σ_i p_i ≤ B                                    (overnight crew/van budget)
```

Size: about Σ_i (C_i + 1) + 2|S| variables, roughly 1,000 to 1,700 for 40
stations depending on dock counts, and about 2|S| + 2 constraints. This fits
the 2,000-variable limit of Gurobi's free licence (HiGHS, the default solver, has no limit). If the large downtown stations push it over,
the fallback is to group levels in steps of 2 bikes, or, if g_i is convex, to
replace z with Gurobi's piecewise-linear objective (about 120 variables).

**Why this is realistic for an operator**

- It answers the question a night dispatcher actually has: "how many bikes
  should be at each station when the morning rush starts?"
- It trades service against effort explicitly. Solving it for a range of
  budgets B gives a curve of failures avoided against bikes moved. That curve
  shows the marginal value of an extra van-hour, which is useful for sizing
  crews.
- The objective is defined in terms of real past mornings, not an assumed
  demand distribution, so it is easy to explain and to audit.
- It does not yet account for van routes or truck capacity per trip. That is
  the job of Formulation 2.

## Formulation 2: single-van pickup-and-delivery route (mixed-integer program)

**Decision:** for one cluster of about 10–12 nearby stations, the order in which
one van should visit them, and how many bikes to load or unload at each stop,
to deliver the moves that Formulation 1 requires.

Sets and data

- N: depot 0 plus the cluster stations. r_i: required net change at i, taken
  from Formulation 1 (positive means drop off, negative means pick up).
- d_ij: road distance, estimated as straight-line distance × circuity factor.
- Q: van capacity. M: penalty per bike of a required move left undone.

Variables

- x_ij ∈ {0,1}: the van drives directly from i to j.
- f_ij ≥ 0: bikes on board while driving from i to j.
- s⁺_i, s⁻_i ≥ 0: part of r_i left undone, in either direction (so the model
  stays feasible on a tight shift). The objective penalises Σ_i (s⁺_i + s⁻_i).
- u_i: visit order, used to rule out subtours (MTZ constraints).

Model

```
min   Σ_ij d_ij · x_ij  +  M · Σ_i (s⁺_i + s⁻_i)

s.t.  Σ_j x_ij = Σ_j x_ji = 1                     ∀ i ≠ 0 with r_i ≠ 0   (visit once)
      Σ_j x_0j = Σ_j x_j0 = 1                                           (one tour from the depot)
      Σ_j f_ji − Σ_j f_ij = r_i − s⁺_i + s⁻_i     ∀ i ≠ 0               (load changes by what is unloaded)
      0 ≤ f_ij ≤ Q · x_ij                         ∀ i, j                (van capacity; no load on unused arcs)
      u_i − u_j + |N| · x_ij ≤ |N| − 1            ∀ i ≠ j, i, j ≠ 0     (no subtours)
      Σ_ij (d_ij / speed) · x_ij + h · Σ_i |r_i| ≤ shift length         (optional time limit)
```

Size, for 12 stations: about 340 variables and 400 constraints, well inside the
license limit.

**Why this is realistic for an operator**

- The output is something a driver can follow: a stop list such as "load 14 at
  A, drop 8 at B, drop 6 at C."
- Van capacity matters. With Q = 20, the van must often visit a station with
  surplus bikes before one with a shortage. The load-flow constraints capture
  this, and a simple nearest-neighbour route ignores it.
- The time limit links bikes moved to shift hours, which is the cost that
  operators manage.

## Evaluation (Phase 3c)

- **Train/test split by date.** The scenarios used to build g_i come from
  training weekdays. Results are reported on held-out weekdays that the model
  never saw.
- **Policies compared, all on the same held-out mornings:**
  1. No rebalancing: start at b_i.
  2. Rule of thumb: fill every station to 50% of capacity, with the same bike
     budget as the optimised plan.
  3. Optimised plan from Formulation 1.
- **Metrics:** failed pickups, failed returns, bikes moved, and, for the
  routed cluster, van kilometres.
- The rule-of-thumb baseline matters. It shows how much of the improvement comes
  from optimising rather than from simply moving bikes.

## Decisions (agreed after Phase 0 review)

How the operator works today, and what is not publicly known, is summarised in
[CURRENT_PRACTICE.md](CURRENT_PRACTICE.md). The decisions below reflect it.

1. **Overnight inventory b_i:** simulate it by starting each station at a stated
   fill level and replaying the previous day's trips. Live GBFS `station_status`
   snapshots taken at about 2am serve only as a sanity check on typical
   overnight fill levels, since they are from 2026 rather than the study year.
   The one prior Toronto study rebuilt inventory from its own per-minute
   snapshot archive, which is not public.
2. **Season:** weekdays from May to October only, for now.
3. **Station subset:** the 40 busiest downtown stations (by May–Oct weekday
   trip starts plus ends). "Downtown" means 13 City neighbourhoods that approximate the
   Downtown Plan area, since the Plan boundary is not published as open data.
   Stations must still exist today (capacity is needed) and have 2025 history.
   Toronto Island stations are excluded (ferry access only). See README, Data.
4. **Van capacity:** no public source gives a figure. It is treated as a
   scenario: Q ∈ {10, 20, 30} bikes, with 20 as the central case.
5. **Depot:** 25 Booth Ave, the depot used in the prior Toronto study.
6. **Scope statement:** Toronto rebalances 24/7. This project models the
   overnight leg only. Stations that overnight moves cannot fix are reported as
   candidates for daytime rebalancing or valet service.

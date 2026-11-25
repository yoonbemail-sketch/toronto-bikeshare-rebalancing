# How Bike Share Toronto rebalances today

This summarises what public sources say about current operations, so the model
can be compared with how the operator actually works. It also records what
those sources *do not* say. Research done November 2026.

## Who does it

- The **Toronto Parking Authority (TPA)** owns the system. It contracts
  day-to-day operations to **Shift Transit** [1][2].
- System size: 680+ stations, 7,100 bikes and 4.6 million rides in 2022. The
  growth plan targets 1,000+ stations and 10,000 bikes by 2025 [3].

## How it works

| Aspect | What the sources say | Source |
|---|---|---|
| Vehicles | "Rebalancing vans." In early 2020 Shift Transit acquired "12 vehicles that were specifically outfitted for transporting bikeshare bikes." | [1] |
| Fleet growth | TPA's 2023 budget included "a 26 percent increase in operations vehicles to drive a better rebalancing of the system." | [3] |
| Schedule | Bikes move "from full stations to empty stations on a 24/7/365 schedule," with overnight shifts. Rebalancing happens **during the day as well as overnight**. | [1], [2] |
| Depot | 25 Booth Ave, Toronto. The paper's routing model starts and ends every truck tour there. | [2] |
| How stations are chosen | An "AI" rebalancing software tool that "leans significantly on historical usage patterns," by time of day and day of week. "Top performing stations" are programmed as a priority. | [1] |
| Other tools | **Valet stations**: staffed stations with extra bikes on site, which effectively remove the dock limit. They suit stations that fill in the morning and empty in the evening. | [2] |
| Scale | In the 2021 simulation, the median day's observed truck tours totalled **1,058 km**. In summer, roughly 1,000 bikes per day were removed from full stations. That figure is read off a chart, so it is approximate. | [2] |

## The operator's decisions, in OR terms

- **Where and how many:** which stations to visit, and how many bikes to add or
  remove at each. This matches the decision variables of Formulation 1.
- **When:** overnight or during the day, and before which peak.
- **Route:** the order of stops for each van, within van capacity. This matches
  Formulation 2.
- **Fleet and crew:** how many vans per shift. This is a longer-term decision;
  the budget sweep in Formulation 1 informs it.

## What the sources do not say

- **Van capacity in bikes.** Neither the operator, the TPA reports nor the
  Toronto paper gives a figure. The paper's routing model has a capacity
  constraint but does not state its value. The only number found is an informal
  estimate in a Portland blog comment: about 15–20 bikes per van [4]. That is
  not a reliable source.
- Fill-level targets or thresholds used by the operator's software.
- How many vans run overnight, or in the downtown core specifically.
- Service-level KPIs in the operating contract. The operator reports only
  year-over-year improvements: 68% fewer empty stations and 46% fewer full
  stations, May–Oct 2019 vs 2020 [1].

## Evidence from the closest prior study

McNee & Miller (2023) [2] simulated every day of 2021 in Toronto. They replayed
observed trips under three scenarios: no rebalancing, the rebalancing actually
observed, and an optimised plan with perfect foresight.

- Without rebalancing, delayed trips reached several hundred per day in summer.
- Their optimised plan used 36% fewer rebalancing movements and 36% less truck
  distance than observed operations.
- Stations that ran empty clustered in **northern downtown** and near Yonge-line
  and Broadview subway stations. Stations near the **core** tended to fill up.
- They inferred historical inventory from **per-minute GBFS snapshots** they
  collected themselves from January 2021 to July 2022. That archive is not
  published. (Phase 4 later found a separate community archive that covers
  2025; see below.)

## What the 2025 station counts show (Phase 4)

A community archive of the live station-status feed, with snapshots about every
16 minutes, makes the 2025 operation measurable. A change in a station's count
of 3 or more bikes that trips don't explain is counted as an operator move. At
the 37 modelled downtown stations, on May–Oct 2025 working days:

- **Bikes are moved around the clock**, not only overnight: about 144 added and
  156 removed per day, including about 6 each way per hour during the morning
  peak.
- **Overnight** (9pm–6am, 43 Sep–Oct test nights), the operator dropped about
  29 bikes a night at these stations, mostly in one or two drops of 10 or more,
  and picked up about 7. Net, about 18 bikes a night came from outside the group.
- **The three valet-type stations** lost about 495 bikes a day without a trip,
  470 of them between 6 and 11am, and gained about 238, mostly between 3 and 8pm.
  That matches staffed valet clearing.
- Scored like any other policy, the operator's overnight result cut replayed
  morning failures from 60.3 (no overnight moves) to 37.9. The optimised plan at
  the same effort reaches 37.3, and at 50 bikes 29.7 (README, Phase 4).

The decisions (where, how many, when) are now visible in data. Van routes,
van capacity and crew numbers still are not.

## What this means for this project

1. **Our scope is the overnight leg of a 24/7 operation.** The model answers
   "what should the stations look like at 6am?" Stations whose morning swing is
   larger than their capacity cannot be fixed overnight. For those, the EDA will
   point to daytime moves or valet service, which matches what the operator
   already does.
2. **Van capacity is treated as a scenario, not a fact.** Results are reported
   for Q = 10, 20 and 30 bikes, so the conclusions do not depend on a number
   nobody has published.
3. **Depot = 25 Booth Ave**, as in [2].
4. **Baselines.** Phase 3 had no inventory history, so it compared against no
   rebalancing and a simple rule. Phase 4 found an archive of 2025 station
   counts and adds the operator's actual practice as a baseline.

## Sources

1. Shift Transit, "How We Tackle One of the Biggest – and Most Important –
   Challenges of Bikeshare Operations," 11 Nov 2020. https://shifttransit.net/?p=1312
2. S. McNee & E. J. Miller, "Modelling the Impacts of Rebalancing Strategies on
   Bike Share Toronto," TAC Conference 2023.
   https://tac-atc.ca/wp-content/uploads/modelling_the_impacts_of_rebalancing_strategies_on_bike_share_toronto.pdf
3. Toronto Parking Authority, "Modernizing Bike Share Toronto Rate Structure,"
   report to the Board, 27 Feb 2023.
   https://www.toronto.ca/legdocs/mmis/2023/ie/bgrd/backgroundfile-234851.pdf
4. BikePortland, "Biketown is now using bikes to refill bikes at bike share
   stations," 7 Sep 2016 (reader comment).
   https://bikeportland.org/2016/09/07/portland-now-using-pedal-powered-trikes-to-help-rebalance-bike-share-stations-191007

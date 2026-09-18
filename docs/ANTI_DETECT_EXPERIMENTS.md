# Anti-cheat letters: what we know and what we are testing

Written 2026-09-17, while the operator is away. Everything here is measured
from this repo's own logs or quoted from the game's letters. Where something is
a guess it says so.

## The letters

Three came from "Nhom Chong Gian Lan Rise of Kingdoms":

| # | Sent | Accusation | Consequence |
|---|------|------------|-------------|
| 1 | 09/14 15:52 | third-party software **to gather resources** | reclaimed the resources gathered on **UTC 2026/09/13**, 3,006 gems |
| 2 | 09/14 | third-party software **to obtain Gems illegitimately** | warning; punished if seen again at the next daily check |
| 3 | 09/17 14:55 | third-party software **to play against the rules** | warning; **no reclaim** |

Letter 3's wording ("vi pham quy tac tien hanh tro choi") is the generic
category -- "playing with third-party software" -- not a complaint about any
particular action. An earlier reading of it as "how the game is operated" was
over-reading a translated phrase and has been dropped.

## What the letters tell us about the audit

* **It runs daily, around 08:00 UTC** (15:00 local, UTC+7). Letter 1 arrived
  08:52 UTC, letter 3 at 07:55 UTC, and both letters say "the next daily
  check".
* **It judges a UTC day.** Letter 1 names "ngay UTC 2026/09/13". So the check
  at 08:00 UTC on day D judges UTC day D-1, which in local time is
  **07:00 on D-1 through 07:00 on D**.
* The operator's reading of the account's state: it is inside the beginner
  window, so warnings will not turn into a ban yet. That is why this is the
  moment to experiment rather than to hide.

## What the farm actually did, per UTC day

From `logs/overnight/farm_run.log`.

| UTC day | farm alive (min) | client quits | median gap between quits | gathers | letter judging it |
|---------|------------------|--------------|--------------------------|---------|-------------------|
| 09-09 | 276 | 27 | 30 min | 84 | -- |
| 09-10 | 293 | 28 | 30 min | 90 | -- |
| 09-11 | 304 | 22 | 24 min | 75 | -- |
| 09-12 | 132 | 15 | 28 min | 46 | -- |
| 09-13 | 378 | 30 | 30 min | 105 | **gathering + reclaim** |
| 09-14 | 176 | 15 | 30 min | 57 | -- |
| 09-16 | 206 | 28 | **16 min** | 61 | **generic warning** |
| 09-17 | 194 | 30 | **15 min** | 59 | judged 09-18 ~15:00 |

Two things stand out and neither is proof:

1. **09-13 was the heaviest day on record** -- 378 minutes and 105 gathers,
   about 40% above the next -- and it is the day flagged for gathering.
   Days at 276-304 min and 75-90 gathers were never flagged.
2. **09-16 was a light day** (206 min, 61 gathers -- less than several days
   that drew nothing) **and was still flagged**. So volume does not explain it.
   The one large behavioural change that day was the quit threshold going in
   at 10:57, which halved the gap between client restarts.

## The rhythm measurement

4,156 gaps between consecutive clicks, six days, from the farm's own logs:

| | |
|---|---|
| median gap | 6.60 s |
| coefficient of variation | 1.37 (not a metronome) |
| within +-25% of the median | 19% |
| gaps over 10 s | 34% |
| **gaps under 1 s** | **0%** |
| 5th percentile | 2.20 s |

The overall spread is human enough. The hole is at the fast end: in 4,156
clicks the bot has **never once** sent two less than a second apart, because
every click waits for a fresh frame first. A person collecting a city, closing
a panel or confirming a dialog does it constantly. "Never fast, often slow" is
a shape, and it is ours.

## 2026-09-18: the design above does not work

UTC 09-17 drew **no letter**. Checked three ways on the evening of 09-18, well
past the 14:55-15:52 window both earlier letters arrived in: the tab row at
16:25 carried no badge on any tab, the system tab's list at 10:25 held nothing
newer than the 09-17 warning, and every mail check from 16:25 to 17:47
accounted for the new mail exactly against finished gathers -- "0 unexplained"
each time. The gem counter only rose, 73,368 to 75,128.

So:

| UTC day | alive | gathers | quit cadence | burst clicks | letter |
|---------|-------|---------|--------------|--------------|--------|
| 09-16 | 206 min | 61 | 16 min | no | **yes** |
| 09-17 | 194 min | 59 | 15 min | no | **no** |

Two days alike in every measured way, opposite outcomes. Nothing measured here
explains the letters. One variable per day cannot work against a signal that
gives two answers to the same question, and it was never going to: a coarse
yes/no read once a day needs many days per configuration before a difference
means anything.

There is a second problem underneath it. The letter judging UTC day D arrives
at ~15:00 on D+1, and UTC day D+1 began at 07:00 that morning -- **eight hours
of the next test day are already spent by the time the verdict lands**. Two
ways out, neither free:

* hold each configuration for several days and count letters per day, so the
  overlap stops mattering. Slow, and what this now does.
* farm only from ~16:00 to 23:00, after the letter window. Then no farming has
  happened in the current UTC day when the verdict arrives, and each day can be
  configured knowing the last one's result. It costs more than half the running
  hours -- and leaves the account offline about 17 hours a day, which is its
  own kind of safe.

**What this does now:** keep the configuration still, keep running, and change
nothing until a letter arrives. The record then carries several days of the
same setup on both sides of it rather than one day of each.

## The experiments as originally planned

One variable per UTC day, because the letters only give a coarse yes/no.

### UTC 09-17 (in progress) -- replication

Nothing changed. Same 15-minute restart cadence as 09-16. The burst harvest
below is committed but deliberately **not** loaded: the farm kept running the
17:27 process so the day stays clean.

* **Prediction:** a letter around 15:00 on 09-18.
* A letter confirms 09-16 was not a one-off. No letter means 09-16 was noise
  and the whole cadence line of thought is weak.

### UTC 09-18 -- burst clicks

Live automatically at the next farm start (commit `35e9643`). The city harvest
now picks one bubble per kind from a single frame and taps all five 0.25-0.80s
apart, then looks once. That puts sub-second gaps into the click distribution
for the first time. Cadence stays at 15 minutes so only one thing changes.

* **Prediction if the click rhythm is what the audit sees:** no letter on 09-19.
* Safety guards, both tested: a dim-ratio check between burst taps stops it the
  moment anything covers the city, and a burst where all five bubbles are still
  there ends the harvest instead of drumming.

### UTC 09-19 -- restart cadence

Put `WAIT_QUIT_FLOOR_S` back to roughly the old 8 minutes so mid-length waits
alt-tab instead of quitting, and keep the burst. This tests the other
candidate. Note this costs nothing in offline time -- the opposite: the 8
minute threshold produced **638** offline minutes on 09-13 against **344** on
09-16, because quitting constantly lets the farm cram in more cycles.

### Later, if both come back clean

Things worth testing after that, roughly in order of how cheap they are:

* gather something other than gems for a day (the first two letters both named
  resources and gems specifically);
* vary the daily volume -- 09-13 at 105 gathers drew a reclaim, 75-90 never
  did, so there may be a threshold between them;
* stop refilling the march queue to 5/5 the instant a slot frees.

## Running it while the operator is away

* **Start:** send `!start` on Discord. As of commit `c3f19cb` the plain command
  works -- it waits for the machine to go quiet for 30s and then starts, so
  `!start force` is no longer needed.
* **Stop:** the run window stops the farm by itself at 23:00. `!stop` also
  works.
* **Watch:** `!status`, `!shot`, `!check`.
* **The signal to look for each day at ~15:00:** open the mail, HE THONG tab.
  A letter from Nhom Chong Gian Lan is the experiment's result. No letter is
  also a result -- write down which.

## Open holes

* The farm reads its mailbox daily but **never reads the letters**, so it ran
  for six hours after the 09-17 warning without knowing. Detecting a letter
  from the anti-cheat team and stopping on it is the obvious next feature; the
  three screenshots in this conversation are the samples to build it from.
* Nothing here explains what the audit actually measures. Every line above is
  correlation over seven days with two positives.

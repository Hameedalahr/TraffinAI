# Mathematical Model

## Purpose

This file explains the mathematical logic currently used in TraffinAI to decide:

- how lane congestion is measured
- how fairness is introduced
- how green time is allocated
- how the next green lane is selected
- how emergency override interrupts the normal cycle

This document reflects the **current implementation**, not only the original idea in `PROJECT.md`.

---

## High-Level Flow

For each control cycle, the system does the following:

1. Count vehicles inside each lane ROI
2. Convert counts into a raw traffic pressure score
3. Measure how long each lane has been waiting since its last green
4. Add a waiting-time bonus to create a fairness-aware priority score
5. Allocate green durations using those priority scores
6. Select the next active lane
7. Run green phase, then yellow phase
8. Interrupt everything immediately if an emergency vehicle is detected

---

## Variables

We use 4 lanes:

```text
i ∈ {1, 2, 3, 4}
```

For each lane `i`:

- `count_{i,j}` = number of vehicles of class `j`
- `w_j` = weight of vehicle class `j`
- `S_i` = raw traffic score
- `W_i` = waiting time in seconds since lane `i` last got green
- `α` = waiting-time weight factor
- `P_i` = priority score
- `G_i` = allocated green time for lane `i`

Global parameters:

- `G_total` = total green-time budget across all lanes
- `G_min` = minimum guaranteed green time per lane
- `G_emergency` = emergency green hold duration
- `Y` = yellow transition duration
- `N` = number of lanes, here `N = 4`

---

## 1. Vehicle Weights

Each class contributes differently to congestion.

Current defaults from [backend/config.py](d:/4-2%20Projects/TraffinAI/backend/config.py):

| Vehicle Class | Weight |
| --- | ---: |
| `truck` | 3.0 |
| `bus` | 3.0 |
| `car` | 1.5 |
| `auto_rickshaw` | 1.2 |
| `motorcycle` | 0.5 |
| `bicycle` | 0.5 |
| `emergency_vehicle` | not scored |

Interpretation:

- large vehicles carry more congestion cost
- smaller vehicles contribute less
- emergency vehicles do not increase score; they trigger a hard override instead

---

## 2. Raw Traffic Pressure Score

The first mathematical layer is the lane pressure score:

```text
S_i = Σ_j ( count_{i,j} × w_j )
```

This is the weighted sum of all detected vehicles in lane `i`.

### Example

Suppose Lane 1 has:

- 2 trucks
- 5 cars
- 3 auto-rickshaws
- 4 motorcycles

Then:

```text
S_1 = 2×3.0 + 5×1.5 + 3×1.2 + 4×0.5
    = 6.0 + 7.5 + 3.6 + 2.0
    = 19.1
```

This is the **raw congestion score** before fairness is applied.

---

## 3. Waiting Time

To avoid the same lane winning repeatedly, the system also tracks how long each lane has waited since its **last completed green phase**.

For lane `i`:

```text
W_i = current_time - wait_started_at_i
```

Rules:

- if lane `i` is currently green, then `W_i = 0`
- once a lane finishes its green and yellow phases, its waiting timer is reset
- all other lanes continue accumulating waiting time

This waiting time is the fairness signal.

---

## 4. Priority Score

The current implementation does **not** choose the next lane using only raw traffic score.

Instead it uses:

```text
P_i = S_i + α × W_i
```

Where:

- `P_i` = priority score
- `S_i` = raw traffic score
- `W_i` = waiting time in seconds
- `α` = waiting-time weight

Current default:

```text
α = 0.35
```

This means every additional second of waiting adds `0.35` to the lane’s selection priority.

### Interpretation

- high `S_i` means heavy traffic pressure
- high `W_i` means fairness pressure
- `P_i` combines both

So the model is trying to answer:

> Which lane is both congested and overdue for service?

---

## 5. Consecutive Green Blocking

There is an additional fairness rule in the implementation:

```text
BLOCK_CONSECUTIVE_GREEN = True
```

When enabled:

- the lane that just had green is temporarily excluded from selection
- but only if at least one other lane has a meaningful positive priority score

This prevents one lane from immediately winning again unless the alternatives have effectively no demand.

So selection is not simply:

```text
argmax(P_i)
```

It is:

1. build the candidate set
2. remove the last green lane if fairness blocking applies
3. select the max-priority lane from the remaining candidates

---

## 6. Green Time Allocation

Once all priority scores are computed, green durations are assigned proportionally.

The current implementation uses:

```text
G_i = G_min + ( P_i / Σ_k P_k ) × ( G_total - N × G_min )
```

Where:

- every lane gets at least `G_min`
- the remaining budget is distributed according to **priority score**
- priority score already includes fairness

### Edge Case: No Demand

If all priority scores are zero:

```text
G_i = G_total / N
```

for every lane.

This ensures the controller still behaves predictably even when no vehicles are detected.

---

## 7. Lane Selection

After computing `P_i` for each lane, the next active lane is chosen as:

```text
Active_lane = argmax_i(P_i)
```

with the consecutive-green blocking rule applied first if enabled.

So:

- raw score affects how urgent the lane is
- waiting time affects how fair it is to keep delaying that lane
- the final selected lane is the one with the best combined pressure

---

## 8. Normal Phase Timeline

A normal control phase looks like this:

```text
1. Choose active lane
2. Set that lane GREEN
3. Hold for G_i seconds
4. Set that lane YELLOW
5. Hold for Y seconds
6. Recompute everything
7. Select next lane
```

The yellow duration is currently:

```text
Y = 3 seconds
```

This is always inserted between normal green phases.

---

## 9. Emergency Override

Emergency handling is not part of the weighted score.

Instead, it is a hard interrupt:

```text
if emergency_detected(lane_e):
    suspend normal cycle
    set all lanes red
    set lane_e green
    hold for G_emergency
```

Current default:

```text
G_emergency = 30 seconds
```

### Important details

- emergency vehicles do not get a finite numerical weight
- they bypass the normal scoring model entirely
- yellow transition is skipped when emergency mode begins
- if the emergency is still being seen, the emergency phase can be extended
- when it clears, the controller resumes normal scheduling from a fresh recomputation

---

## 10. Worked Example Without Fairness

Suppose the lanes have the following raw counts:

### Lane 1

- 2 trucks
- 5 cars
- 3 auto-rickshaws
- 4 motorcycles

### Lane 2

- 0 trucks
- 8 cars
- 6 auto-rickshaws
- 2 motorcycles

### Lane 3

- 3 trucks
- 3 cars
- 2 auto-rickshaws
- 6 motorcycles

### Lane 4

- 1 truck
- 4 cars
- 5 auto-rickshaws
- 3 motorcycles

Then:

```text
S1 = 19.1
S2 = 20.2
S3 = 18.9
S4 = 16.5
```

If fairness were ignored, Lane 2 would win because `20.2` is the highest raw score.

---

## 11. Worked Example With Fairness

Now suppose the waiting times are:

```text
W1 = 88
W2 = 37
W3 = 12
W4 = 116
```

and:

```text
α = 0.35
```

Then the priority scores become:

```text
P1 = 19.1 + 0.35×88  = 49.9
P2 = 20.2 + 0.35×37  = 33.15
P3 = 18.9 + 0.35×12  = 23.10
P4 = 16.5 + 0.35×116 = 57.10
```

Now Lane 4 wins even though it did **not** have the highest raw traffic score.

Why?

Because it has waited the longest, and the system is intentionally balancing:

- congestion
- fairness

This is exactly the behavior introduced to stop one lane from repeatedly dominating the cycle.

---

## 12. Green Allocation Example With Priority Score

Using the priority scores above:

```text
P1 = 49.9
P2 = 33.15
P3 = 23.10
P4 = 57.10
```

Total:

```text
ΣP = 163.25
```

If:

```text
G_total = 120
G_min = 10
N = 4
```

then extra budget is:

```text
120 - 4×10 = 80
```

Now:

```text
G1 = 10 + (49.9 / 163.25) × 80 ≈ 34.45 → 34
G2 = 10 + (33.15 / 163.25) × 80 ≈ 26.24 → 26
G3 = 10 + (23.10 / 163.25) × 80 ≈ 21.32 → 21
G4 = 10 + (57.10 / 163.25) × 80 ≈ 37.98 → 38
```

So:

- Lane 4 gets the next green
- Lane 4 gets the largest green duration

because it has the highest **priority score**, not just the highest raw score

---

## 13. Why This Model Is Better Than Raw Pressure Alone

If only raw pressure is used:

- busy lanes can keep winning again and again
- low-pressure lanes may starve
- fairness is weak

If only waiting time is used:

- fairness improves
- but the system can ignore real congestion pressure

The current model combines both:

```text
priority = congestion + fairness bonus
```

This gives a more practical balance.

---

## 14. Current Parameters

Current defaults from [backend/config.py](d:/4-2%20Projects/TraffinAI/backend/config.py):

```text
G_TOTAL = 120
G_MIN = 10
G_EMERGENCY = 30
YELLOW_DURATION = 3
WAIT_TIME_WEIGHT = 0.35
BLOCK_CONSECUTIVE_GREEN = True
```

Vehicle weights:

```text
truck = 3.0
bus = 3.0
car = 1.5
auto_rickshaw = 1.2
motorcycle = 0.5
bicycle = 0.5
emergency_vehicle = None
```

These values can also be changed through the Config tab in the UI.

---

## 15. Actual Functions In Code

The mathematical logic is implemented primarily in:

- [backend/signal_controller.py](d:/4-2%20Projects/TraffinAI/backend/signal_controller.py)

Important functions:

- `compute_scores`
- `compute_waiting_times`
- `compute_priority_scores`
- `compute_green_times`
- `select_active_lane`
- `run_emergency_phase`

---

## 16. One-Sentence Summary

The system first computes **weighted traffic pressure**, then adds a **waiting-time fairness bonus**, then allocates green time proportionally from the resulting **priority score**, unless an **emergency vehicle** forces an immediate override.

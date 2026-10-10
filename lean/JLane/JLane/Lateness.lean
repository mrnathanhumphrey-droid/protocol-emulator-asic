import JLane.Pass
/-!
# Brick 5 — the lateness recurrence
One lane's timeline as sequences indexed by job. Port/Pass give the two shapes
of `c (j+1)`: not queued (`≤ w + D* + B`, from `port_wait_bound_19`) or queued
behind the lane's previous refill (`≤ c j + D* + B`, from `next_pass`). Here `B`
is the branch-1 interference budget per wait.

`D* + B ≤ d` keeps lateness from growing (throughput), and
`R + D* + B + 3 ≤ 2d` meets the deadline (latency). With `B = 0` these are
`d ≥ 20` and `2d ≥ R + 23`.
-/
namespace JLane

/-- One lane's timeline. -/
structure Timeline where
  /-- release of job `j` -/
  r : Nat → Nat
  /-- writeback of job `j` -/
  w : Nat → Nat
  /-- hit for the refill owed at `w j` (it fetches job `j + 2`) -/
  c : Nat → Nat

/-- Lateness never exceeds `R + 2 + D* + B` as long as `D* + B ≤ d`. -/
theorem lateness_bound (T : Timeline) (d R B : Nat)
    (hr : ∀ j, T.r (j + 1) = T.r j + d)
    (hw : ∀ j, T.w j ≤ T.r j + R + 2)
    (hc0 : T.c 0 ≤ T.w 0 + DSTAR + B)
    (hc : ∀ j, T.c (j + 1) ≤ T.w (j + 1) + DSTAR + B ∨
               T.c (j + 1) ≤ T.c j + DSTAR + B)
    (hd : DSTAR + B ≤ d) :
    ∀ j, T.c j ≤ T.r j + R + 2 + DSTAR + B
  | 0 => by
    have := hw 0
    omega
  | j + 1 => by
    have ih := lateness_bound T d R B hr hw hc0 hc hd j
    have h1 := hc j
    have h2 := hw (j + 1)
    have h3 := hr j
    omega

/-- **The deadline.** The refill owed at `w j` is valid by the release of job `j + 2`. -/
theorem deadline_met (T : Timeline) (d R B : Nat)
    (hr : ∀ j, T.r (j + 1) = T.r j + d)
    (hw : ∀ j, T.w j ≤ T.r j + R + 2)
    (hc0 : T.c 0 ≤ T.w 0 + DSTAR + B)
    (hc : ∀ j, T.c (j + 1) ≤ T.w (j + 1) + DSTAR + B ∨
               T.c (j + 1) ≤ T.c j + DSTAR + B)
    (hd : DSTAR + B ≤ d)
    (hlat : R + DSTAR + B + 3 ≤ 2 * d) :
    ∀ j, T.c j + 1 ≤ T.r (j + 2) := by
  intro j
  have h := lateness_bound T d R B hr hw hc0 hc hd j
  have h1 := hr j
  have h2 : T.r (j + 2) = T.r (j + 1) + d := hr (j + 1)
  omega

/-- A timeline at `d = 19` that satisfies every hypothesis except `D* ≤ d`, with
`R = 0` and `B = 0`, and misses the deadline at job 16. -/
def slowTimeline : Timeline := ⟨fun j => 19 * j, fun j => 19 * j + 2, fun j => 20 * j + 22⟩

/-- **The recurrence is sharp.** At `d = 19` the queued branch grows lateness by one
cycle per job until it misses. (Abstract witness; the chip's own witness is the
uniform-19 stall in PORT_SPEC PS1.) -/
theorem recurrence_sharp :
    (∀ j, slowTimeline.r (j + 1) = slowTimeline.r j + 19) ∧
    (∀ j, slowTimeline.w j ≤ slowTimeline.r j + 0 + 2) ∧
    slowTimeline.c 0 ≤ slowTimeline.w 0 + DSTAR + 0 ∧
    (∀ j, slowTimeline.c (j + 1) ≤ slowTimeline.w (j + 1) + DSTAR + 0 ∨
          slowTimeline.c (j + 1) ≤ slowTimeline.c j + DSTAR + 0) ∧
    ¬ (slowTimeline.c 16 + 1 ≤ slowTimeline.r 18) := by
  refine ⟨fun j => ?_, fun j => ?_, ?_, fun j => ?_, ?_⟩
  · show 19 * (j + 1) = 19 * j + 19
    omega
  · show 19 * j + 2 ≤ 19 * j + 0 + 2
    omega
  · decide
  · right
    show 20 * (j + 1) + 22 ≤ 20 * j + 22 + 20 + 0
    omega
  · decide

end JLane

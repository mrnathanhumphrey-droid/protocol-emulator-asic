import JLane.Br1Sep
/-!
# Brick O — HALF: the ARM that rebases to the edge plus half a period (agent 1's batch, 11-14)

RTL (agent 1's batch 9c0df0c, diffed 11-14): HALF is the ARM's `count[0]` (latched per ARM,
l.3812); at its edge `E` the lane's timestamp is rebased to `E + l_t[DLY_W-1:1]` (`ck_rebase`,
l.1630), `l_t` the lane header's period; `rel_q` reads `now ≥ ts`, so the lane is released at
`E + h` with `h = max(1, ⌊l_t/2⌋)` (`⌊l_t/2⌋ = 0` rebases to `E`, released at `E + 1` past the
armed flag). A plain ARM rebases to `E` and is released at `E + 1`: the case `h = 1`. `h` is a
function of the ARM's writeback time and lane, so a per-ARM bit is covered.

**So HALF needs no new engine.** `Armed.lean`'s model releases an ARM's lane one past its edge
input (`arm_release`); fed the edge input shifted by `h − 1` (`halfEdge`), it releases at
`E + h` -- the RTL's release -- and in `[E, E + h)` the lane is not ready in both (RTL: armed
cleared, `ts = E + h > now`; model: still armed). Every theorem of `Armed`, `ArmClose`,
`GapRun` and the checker applies to HALF ARMs through `halfEdge`, whose premise (`edge ≥ t + 1`)
`halfEdge_ok` discharges. The correspondence is argued here, not mechanized against an RTL model;
it is checked against agent 1's RTL when pushed (and by their sims).

The one change the checker sees: a HALF ARM's release gap is its edge's distance plus `h − 1`;
with the nop gone from every `arm_sop` site, the first receive word follows `arm_sop` directly.
-/
namespace JLane

/-- The edge input the model is fed for an ARM released `h` past its edge (`h = 1`: plain;
`h = l_t/2`: HALF). -/
def halfEdge (edge : Nat → Lane → Nat) (h : Nat → Lane → Nat) : Nat → Lane → Nat :=
  fun t l => edge t l + h t l - 1

/-- The model's edge premise holds for the shifted input. -/
theorem halfEdge_ok (edge : Nat → Lane → Nat) (h : Nat → Lane → Nat)
    (hedge : ∀ t l, t + 1 ≤ edge t l) (hh : ∀ t l, 1 ≤ h t l) :
    ∀ t l, t + 1 ≤ halfEdge edge h t l := by
  intro t l
  unfold halfEdge
  have := hedge t l
  have := hh t l
  omega

/-- A plain ARM is the case `h = 1`: the input is unchanged. -/
theorem halfEdge_plain (edge : Nat → Lane → Nat) : halfEdge edge (fun _ _ => 1) = edge := by
  funext t l
  show edge t l + 1 - 1 = edge t l
  omega

/-- **The HALF ARM's release.** After a (HALF or plain) ARM's writeback, its lane's V4b release
is its edge plus `h` (`arm_release` on the shifted input). -/
theorem arm_release_half (P : Program2) (Wn : Nat) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (h : Nat → Lane → Nat) (hh : ∀ t l, 1 ≤ h t l)
    (w : Option Lane) (X : Engine3) (hI : ArmInv Wn X) (harm : X.armWB P = true) :
    (πE (step3 P fw (halfEdge edge h) w X)).ts X.x.e.cur =
      edge X.x.e.now X.x.e.cur + h X.x.e.now X.x.e.cur := by
  rw [arm_release P Wn fw (halfEdge edge h) w X hI harm]
  unfold halfEdge
  have := hh X.x.e.now X.x.e.cur
  omega

#print axioms halfEdge_ok
#print axioms arm_release_half

end JLane

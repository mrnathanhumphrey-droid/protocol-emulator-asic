import JLane.Armed
import JLane.GapRun
/-!
# Brick Z — a plain ARM retires before its successor is released (Wilson 11-15, ArmRetire)

GapRun's certificate charges the word two after a retirement `x` with `Z x - rd x x2`: how long
past the next release the refill owed from `x` may still be pending. For a plain ARM the
certificate (stage 6) took `Z x` = the ARM's full response bound and `rd x x2` = the 4-cycle
floor (the edge may come at once), so the word after the ARM's successor came out late (17 at
B = 0), B grew and every D*-spaced word fell behind: J 138 on a `within … else abort` lane,
where the RTL trace measured at most 13 (agent 2's slot trace, 11-15).

But the ARM's successor is released by the EDGE, and the edge comes after the ARM's
writeback (`Armed.arm_release`, premise `hedge`): the release is at least the writeback + 2.
So the ARM's OWN response, less the release distance to its successor, is at most -2. The part
of `Z x` propagated from earlier retirements (refill backlog) is not touched.

* `arm_release_ge` — on the ARM model: after a plain ARM's writeback its lane's release is at
  least `now + 2`;
* `arm_rd` — on GapRun's run: given that at the ARM's retirement (`hgap`, what the refinement
  supplies), the release distance to any later retirement is at least the ARM's own response
  offset + 4;
* `cap_zc`, `cap_hn` — with `Z x = max own prop`, the certificate's capped checks (stage 6:
  `min (own - rd) (-2)` for the own part, `prop - rd` for the propagated part) give GapRun's
  `hZC` and `hHN` at the ARM pair. `hc` takes either form the certificate establishes:
  `min (own - rd) (-2)` is -2 (first disjunct) or the own part uncapped (second).
-/
namespace JLane

/-- **After a plain ARM's writeback, its lane's release is at least two cycles later.** -/
theorem arm_release_ge (P : Program2) (Wn : Nat) (fw : Engine2 → Word)
    (edge : Nat → Lane → Nat) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (w : Option Lane) (X : Engine3) (h : ArmInv Wn X) (harm : X.armWB P = true) :
    X.x.e.now + 2 ≤ (πE (step3 P fw edge w X)).ts X.x.e.cur := by
  rw [arm_release P Wn fw edge w X h harm]
  have := hedge X.x.e.now X.x.e.cur
  omega

/-- **On GapRun's run:** an ARM retirement at `x` whose gap reaches past its writeback by 2
(`hgap`, the refinement's `arm_release_ge`) is followed by a release at least its own response
offset + 4 later, at any later cycle. -/
theorem arm_rd (P : Program) (win : Engine → Option Lane) (y : Lane) (e0 : Engine) (x x2 own : Nat)
    (hw : IsWB y (run P win x e0)) (hxx : x < x2)
    (hown : (run P win x e0).now = (run P win x e0).ts y + own + 2)
    (hgap : (run P win x e0).now + 2 ≤ (run P win x e0).ts y + gp P win y e0 x) :
    own + 4 ≤ rd P win y e0 x x2 := by
  have h1 := ts_gap P win y e0 x x2 hw hxx
  have h2 := rd_eq P win y e0 x x2 (Nat.le_of_lt hxx)
  omega

/-- **`hZC` at an ARM pair from the capped check.** `Z x = max own prop`: the own part is
capped (`own + 4 ≤ rd`, `arm_rd`; the certificate checked `-2 + D* + B ≤ Z x2`), the
propagated part is checked as it stands. -/
theorem cap_zc (own prop rd Z2 D B : Nat) (hA : own + 4 ≤ rd)
    (hc : D + B ≤ 2 + Z2 ∨ own + D + B ≤ rd + Z2)
    (hp : prop + D + B ≤ rd + Z2) : max own prop + D + B ≤ rd + Z2 := by
  rcases Nat.le_total own prop with h | h
  · rw [Nat.max_eq_right h]; exact hp
  · rw [Nat.max_eq_left h]; omega

/-- **`hHN` at an ARM pair from the capped check** (the certificate checked
`-2 + 26 + B ≤ gp x2 + L x2` and the propagated part). -/
theorem cap_hn (own prop rd g2 L2 HS B : Nat) (hA : own + 4 ≤ rd)
    (hc : HS + B ≤ 2 + g2 + L2 ∨ own + HS + B ≤ rd + g2 + L2)
    (hp : prop + HS + B ≤ rd + g2 + L2) : max own prop + HS + B ≤ rd + g2 + L2 := by
  rcases Nat.le_total own prop with h | h
  · rw [Nat.max_eq_right h]; exact hp
  · rw [Nat.max_eq_left h]; omega

#print axioms arm_release_ge
#print axioms arm_rd
#print axioms cap_zc
#print axioms cap_hn

end JLane

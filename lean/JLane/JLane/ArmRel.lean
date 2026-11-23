import JLane.ComposeB
import JLane.RespWinB
import JLane.SchedK11
/-!
# Brick K11d — K11 derived: an armed lane is not released before its edge (Wilson 11-22)

Ruling (b) rewords K11 as "the scheduler never chooses an armed lane before its deadline", and
the ruling of 11-22 (K11's three checks, item 2) makes it DERIVED: it follows from an invariant
-- an armed lane's release is ahead of `now` -- and `disp_released_only` (the scheduler names only
released lanes, `hwin`), which is already a contract.

The armed run (`runBA`) disarms a lane only at its edge (`hit`); the timeout path is the
FALLTHROUGH engine's. So the armed run is the model of an arming whose EDGE comes BEFORE its
DEADLINE -- the deadline is the release the ARM's writeback sets (`ts + dly + ext`). That scope is
`EdgeFirst`: every armed lane's edge cycle `armE` is strictly before its release.

* `edgeFirst_step` / `edgeFirst_runBA` -- the scope is kept: an armed lane is not dispatched
  (`ArmInvB`), so neither its release nor its edge cycle moves; a lane armed this cycle has its
  edge before the deadline its writeback sets (`hfirst`, per arming);
* `armed_unreleased_runBA` -- every armed lane is unreleased: `now ≤ armE` (`ArmInvB`) and
  `armE < ts` (`EdgeFirst`);
* `K11At_of_unreleased` / `K11At_runBA` -- **K11 derived**: the scheduler names only released lanes
  (`hwin`, disp_released_only), and no armed lane is released, so it never names an armed lane.
-/
namespace JLane

/-- The armed run's scope: every armed lane's edge comes strictly before its release (its
deadline). -/
def EdgeFirst (A : EngBA) : Prop := ∀ l, A.armed l = true → A.armE l < A.X.x.e.ts l

/-- **K11 from the release**: a scheduler that names only released lanes never names an
unreleased one -- so, with every armed lane unreleased, never an armed lane. -/
theorem K11At_of_unreleased (P : Program) (win : Engine → Option Lane) (armed : Lane → Bool)
    (e : Engine) (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hu : ∀ l, armed l = true → e.now < e.ts l) : K11At P win armed e := by
  intro v hv ha
  have h1 := (hwin e v hv).2
  have h2 := hu v ha
  omega

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)

/-- **The scope is kept for a cycle.** -/
theorem edgeFirst_step (k : Lane → Nat) (A : EngBA) (hA : ArmInvB A) (hE : EdgeFirst A)
    (hfirst : ∀ l, A.arms P isArm l = true →
      edge A.X.x.e.now l < A.X.x.e.ts l + P.dly l + P.ext A.X.x.e.now l) :
    EdgeFirst (stepBA P win usb sreq isArm edge k A) := by
  intro l ha
  rw [stepBA_armed] at ha
  by_cases hh : A.hit l = true
  · rw [if_pos hh] at ha; cases ha
  · rw [if_neg hh] at ha
    have hts : (stepBA P win usb sreq isArm edge k A).X.x.e.ts l = tsNext P A.X.x.e l :=
      stepBKK_ts_y P (winA win A.armed) usb sreq A.hit k A.X l (by simpa using hh)
    show (if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l) < _
    rw [hts]
    by_cases har : A.arms P isArm l = true
    · rw [if_pos har]
      have h := hfirst l har
      unfold EngBA.arms at har
      simp only [Bool.and_eq_true, decide_eq_true_eq] at har
      unfold tsNext
      rw [if_pos ⟨har.1.1.1, har.1.1.2⟩]
      exact h
    · rw [if_neg har] at ha ⊢
      have hnd := hA.1 l ha
      unfold tsNext
      rw [if_neg (fun h => hnd ⟨by rw [h.1]; decide, h.2.symm⟩)]
      exact hE l ha

/-- **The scope along the armed run.** -/
theorem edgeFirst_runBA (hedge : ∀ t l, t + 1 ≤ edge t l) (kt : Nat → Lane → Nat) (A0 : EngBA)
    (hA : ArmInvB A0) (hE : EdgeFirst A0)
    (hfirst : ∀ n l, (runBA P win usb sreq isArm edge kt n A0).arms P isArm l = true →
      edge (runBA P win usb sreq isArm edge kt n A0).X.x.e.now l
        < (runBA P win usb sreq isArm edge kt n A0).X.x.e.ts l + P.dly l
          + P.ext (runBA P win usb sreq isArm edge kt n A0).X.x.e.now l) :
    ∀ n, EdgeFirst (runBA P win usb sreq isArm edge kt n A0)
  | 0 => hE
  | n + 1 => by
    rw [runBA_succ]
    exact edgeFirst_step P win usb sreq isArm edge _ _
      (armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA n)
      (edgeFirst_runBA hedge kt A0 hA hE hfirst n) (hfirst n)

/-- **Every armed lane is unreleased** along the armed run. -/
theorem armed_unreleased_runBA (hedge : ∀ t l, t + 1 ≤ edge t l) (kt : Nat → Lane → Nat)
    (A0 : EngBA) (hA : ArmInvB A0) (hE : EdgeFirst A0)
    (hfirst : ∀ n l, (runBA P win usb sreq isArm edge kt n A0).arms P isArm l = true →
      edge (runBA P win usb sreq isArm edge kt n A0).X.x.e.now l
        < (runBA P win usb sreq isArm edge kt n A0).X.x.e.ts l + P.dly l
          + P.ext (runBA P win usb sreq isArm edge kt n A0).X.x.e.now l)
    (n : Nat) (l : Lane) (ha : (runBA P win usb sreq isArm edge kt n A0).armed l = true) :
    (runBA P win usb sreq isArm edge kt n A0).X.x.e.now
      < (runBA P win usb sreq isArm edge kt n A0).X.x.e.ts l := by
  have h1 := (armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA n).2 l ha
  have h2 := edgeFirst_runBA P win usb sreq isArm edge hedge kt A0 hA hE hfirst n l ha
  omega

/-- **K11, derived** along the armed run: from the armed lanes being unreleased and
`disp_released_only`. -/
theorem K11At_runBA (hedge : ∀ t l, t + 1 ≤ edge t l) (kt : Nat → Lane → Nat) (A0 : EngBA)
    (hA : ArmInvB A0) (hE : EdgeFirst A0)
    (hfirst : ∀ n l, (runBA P win usb sreq isArm edge kt n A0).arms P isArm l = true →
      edge (runBA P win usb sreq isArm edge kt n A0).X.x.e.now l
        < (runBA P win usb sreq isArm edge kt n A0).X.x.e.ts l + P.dly l
          + P.ext (runBA P win usb sreq isArm edge kt n A0).X.x.e.now l)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now) :
    ∀ n, K11At P win (runBA P win usb sreq isArm edge kt n A0).armed
      (runBA P win usb sreq isArm edge kt n A0).X.x.e :=
  fun n => K11At_of_unreleased P win _ _ hwin
    (fun l ha => armed_unreleased_runBA P win usb sreq isArm edge hedge kt A0 hA hE hfirst n l ha)

end

end JLane

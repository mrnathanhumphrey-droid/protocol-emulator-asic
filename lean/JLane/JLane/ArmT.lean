import JLane.ArmRel
/-!
# Brick K11e — one armed run for both FALLTHROUGH paths (Wilson 11-22 ruling)

Ruling (11-22): the buffered machine is the final hardware, so its timeout path needs the same
armed model behind it as the edge path. **Each arming ends at whichever comes first, its edge or
its deadline:**
* at the edge: the keep-flush as now (K1–K5), keeping the edge word (`hit`);
* at the deadline: PC+1 stays as the head and PC+2 is dropped (K6 as ruled), as the keep-flush
  with the kept index PC+1's -- `OrderT`'s model of the timeout path, now driven by the armed run
  (`tmo`: armed, the release -- the deadline the ARM's writeback set -- reached, no edge this cycle);
* a tie (the edge on the deadline cycle): the edge wins (`tmo` excludes a `hit` cycle), as the RTL
  and the slot-off FT engine.

`stepBT` is `FlushHeld.stepBA` with the flush set `ends = hit || tmo` in place of `hit`. Its state
part is `stepBKK` with `fl := ends`, so the run is a `runBK` run and every theorem proved there
applies; on a cycle with no timeout it IS `stepBA` (`stepBT_eq_stepBA`).

* `hit_tmo_excl`, `arming_cover` -- **no cycle uncovered**: an armed lane, on each cycle, is in
  exactly one of continuing armed, its edge flush, its timeout; and it ends no later than its edge
  cycle (`now ≤ armE` is kept, `armInvT_step` / `armInvT_runBT`);
* `released_armed_ends`, `K11At_unless_ending` -- **K11 with its exception**: K11 holds at every cycle
  where no arming ends; an armed lane is released only on the cycle its arming ends -- the timeout
  cycles (and the edge-on-deadline tie), which is what `branch_budget._disarm_S` charges.

The RTL's timeout decision is the first idle cycle at or after the deadline that the lane wins; the
ruling places it AT the deadline. Recorded with the report (11-22).
-/
namespace JLane

/-- The timeout: armed, the release (deadline) reached, and no edge this cycle (the edge wins a
tie). -/
def EngBA.tmo (A : EngBA) (l : Lane) : Bool :=
  A.armed l && decide (A.X.x.e.ts l ≤ A.X.x.e.now) && !A.hit l

/-- The arming ends this cycle: its edge or its timeout. -/
def EngBA.ends (A : EngBA) (l : Lane) : Bool := A.hit l || A.tmo l

/-- **The edge wins a tie**: an edge cycle is never a timeout cycle. -/
theorem hit_tmo_excl (A : EngBA) (l : Lane) (h : A.hit l = true) : A.tmo l = false := by
  unfold EngBA.tmo; rw [h]; simp

/-- An armed lane whose release has arrived ends its arming this cycle. -/
theorem released_armed_ends (A : EngBA) (l : Lane) (ha : A.armed l = true)
    (hr : A.X.x.e.ts l ≤ A.X.x.e.now) : A.ends l = true := by
  unfold EngBA.ends EngBA.tmo
  cases hh : A.hit l
  · simp [ha, hr]
  · rfl

/-- **K11 with its exception**: at a cycle where no arming ends, the scheduler (naming only
released lanes) never names an armed lane. -/
theorem K11At_unless_ending (P : Program) (win : Engine → Option Lane) (A : EngBA)
    (hwin : ∀ e w, win e = some w → P.live w = true ∧ e.ts w ≤ e.now)
    (hno : ∀ l, A.armed l = true → A.ends l = false) : K11At P win A.armed A.X.x.e :=
  K11At_of_unreleased P win _ _ hwin (fun l ha => by
    by_cases hr : A.X.x.e.ts l ≤ A.X.x.e.now
    · have h := hno l ha
      rw [released_armed_ends A l ha hr] at h
      cases h
    · omega)

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)

/-- **One cycle of the armed run with both paths**: `stepBA` with the flush set `ends`. -/
def stepBT (k : Lane → Nat) (A : EngBA) : EngBA :=
  { X := stepBKK P (winA win A.armed) usb sreq A.ends k A.X
    armed := fun l => if A.ends l = true then false
      else if A.arms P isArm l = true then true else A.armed l
    armE := fun l => if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l }

def runBT (kt : Nat → Lane → Nat) : Nat → EngBA → EngBA
  | 0, A => A
  | n + 1, A => stepBT P win usb sreq isArm edge (kt (runBT kt n A).X.x.e.now) (runBT kt n A)

theorem runBT_succ (kt : Nat → Lane → Nat) (A0 : EngBA) (n : Nat) :
    runBT P win usb sreq isArm edge kt (n + 1) A0
      = stepBT P win usb sreq isArm edge (kt (runBT P win usb sreq isArm edge kt n A0).X.x.e.now)
          (runBT P win usb sreq isArm edge kt n A0) := rfl

/-- **On a cycle with no timeout the step is `stepBA`.** -/
theorem stepBT_eq_stepBA (k : Lane → Nat) (A : EngBA) (h : ∀ l, A.tmo l = false) :
    stepBT P win usb sreq isArm edge k A = stepBA P win usb sreq isArm edge k A := by
  have he : A.ends = A.hit := by
    funext l; unfold EngBA.ends; rw [h l]; simp
  unfold stepBT stepBA
  rw [he]

theorem stepBT_now (k : Lane → Nat) (A : EngBA) :
    (stepBT P win usb sreq isArm edge k A).X.x.e.now = A.X.x.e.now + 1 := by
  show (stepB P (winA win A.armed) usb sreq A.X.base).e.now = _
  rw [stepB_e_now, base_e]

/-- **The armed invariant is kept** by the step with both paths: an armed lane is not dispatched,
and its edge cycle is not past. -/
theorem armInvT_step (k : Lane → Nat) (hedge : ∀ t l, t + 1 ≤ edge t l) (A : EngBA)
    (hA : ArmInvB A) : ArmInvB (stepBT P win usb sreq isArm edge k A) := by
  have hn := stepBT_now P win usb sreq isArm edge k A
  constructor
  · intro l ha
    show ¬((stepB P (winA win A.armed) usb sreq A.X.base).e.st ≠ .idle ∧
      (stepB P (winA win A.armed) usb sreq A.X.base).e.cur = l)
    change (if A.ends l = true then false
      else if A.arms P isArm l = true then true else A.armed l) = true at ha
    by_cases hh : A.ends l = true
    · rw [if_pos hh] at ha
      cases ha
    · rw [if_neg hh] at ha
      by_cases har : A.arms P isArm l = true
      · unfold EngBA.arms at har
        simp only [Bool.and_eq_true, decide_eq_true_eq] at har
        have hwb := har.1.1.1
        rintro ⟨hne, -⟩
        apply hne
        show (dispNext (winA win A.armed) A.X.base.e).st = .idle
        rw [base_e]
        simp [dispNext, hwb]
      · rw [if_neg har] at ha
        exact fun ⟨hne, hc⟩ => next_disp_ne P win usb sreq A hA l ha hne hc
  · intro l ha
    rw [hn]
    change (if A.ends l = true then false
      else if A.arms P isArm l = true then true else A.armed l) = true at ha
    show A.X.x.e.now + 1 ≤ (if A.arms P isArm l = true then edge A.X.x.e.now l else A.armE l)
    by_cases hh : A.ends l = true
    · rw [if_pos hh] at ha
      cases ha
    · rw [if_neg hh] at ha
      by_cases har : A.arms P isArm l = true
      · rw [if_pos har]
        exact hedge _ _
      · rw [if_neg har] at ha ⊢
        have h1 := hA.2 l ha
        have h2 : A.X.x.e.now ≠ A.armE l := by
          intro h
          apply hh
          unfold EngBA.ends EngBA.hit
          rw [ha, h]
          simp
        omega

theorem armInvT_runBT (hedge : ∀ t l, t + 1 ≤ edge t l) (kt : Nat → Lane → Nat) (A0 : EngBA)
    (hA : ArmInvB A0) : ∀ n, ArmInvB (runBT P win usb sreq isArm edge kt n A0)
  | 0 => hA
  | n + 1 => armInvT_step P win usb sreq isArm edge _ hedge _ (armInvT_runBT hedge kt A0 hA n)

/-- **No cycle uncovered**: an armed lane is, on each cycle, in exactly one of: continuing armed
(no edge, no timeout), its edge flush, its timeout; and its arming ends no later than its edge
cycle. -/
theorem arming_cover (hedge : ∀ t l, t + 1 ≤ edge t l) (kt : Nat → Lane → Nat) (A0 : EngBA)
    (hA : ArmInvB A0) (n : Nat) (l : Lane)
    (ha : (runBT P win usb sreq isArm edge kt n A0).armed l = true) :
    ((runBT P win usb sreq isArm edge kt n A0).hit l = true ∧
        (runBT P win usb sreq isArm edge kt n A0).tmo l = false) ∨
      ((runBT P win usb sreq isArm edge kt n A0).tmo l = true ∧
        (runBT P win usb sreq isArm edge kt n A0).hit l = false) ∨
      ((runBT P win usb sreq isArm edge kt n A0).hit l = false ∧
        (runBT P win usb sreq isArm edge kt n A0).tmo l = false) ∧
    (runBT P win usb sreq isArm edge kt n A0).X.x.e.now
      ≤ (runBT P win usb sreq isArm edge kt n A0).armE l := by
  have hI := (armInvT_runBT P win usb sreq isArm edge hedge kt A0 hA n).2 l ha
  cases hh : (runBT P win usb sreq isArm edge kt n A0).hit l with
  | true => exact Or.inl ⟨rfl, hit_tmo_excl _ l hh⟩
  | false =>
    cases ht : (runBT P win usb sreq isArm edge kt n A0).tmo l with
    | true => exact Or.inr (Or.inl ⟨rfl, rfl⟩)
    | false => exact Or.inr (Or.inr ⟨⟨rfl, rfl⟩, hI⟩)

/-- On its edge cycle an armed lane's arming ends: the edge (the tie included). -/
theorem ends_at_edge (A : EngBA) (l : Lane) (ha : A.armed l = true)
    (he : A.X.x.e.now = A.armE l) : A.ends l = true := by
  unfold EngBA.ends EngBA.hit
  rw [ha, he]
  simp

end

end JLane

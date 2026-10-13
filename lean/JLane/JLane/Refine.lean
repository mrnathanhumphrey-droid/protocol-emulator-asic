import JLane.DStar39
import JLane.Act
/-!
# Brick V1 — v1 theorems carry over to v2 runs on plain programs
`run2` runs the v2 engine under a v2 scheduler `sched : Engine2 → Option Lane` and an
arbitrary fetch stream `fw`. On plain words (`Plain dly`, preserved when `fw` only
delivers plain words), the projected trajectory **is** a v1 run, under a single v1
scheduler `win1` built from `sched` (time-indexed along the trajectory, with a
first-ready fallback off it so the v1 contract holds globally).

Consequence (`dstar39_v2`): the hypothesis-free `d ≥ 39` theorem holds for the v2 engine,
for every plain program stream.
-/
namespace JLane

/-- `n` v2 cycles. -/
def run2 (P : Program2) (fw : Engine2 → Word) (sched : Engine2 → Option Lane) :
    Nat → Engine2 → Engine2
  | 0, x => x
  | n + 1, x => run2 P fw sched n (step2 P fw (sched x) x)

theorem run2_succ' (P : Program2) (fw : Engine2 → Word) (sched : Engine2 → Option Lane) :
    ∀ (n : Nat) (x : Engine2),
      run2 P fw sched (n + 1) x = step2 P fw (sched (run2 P fw sched n x)) (run2 P fw sched n x)
  | 0, _ => rfl
  | n + 1, x => run2_succ' P fw sched n (step2 P fw (sched x) x)

theorem now_run2 (P : Program2) (fw : Engine2 → Word) (sched : Engine2 → Option Lane) :
    ∀ (n : Nat) (x : Engine2), (run2 P fw sched n x).e.now = x.e.now + n
  | 0, _ => rfl
  | n + 1, x => by
    rw [run2_succ' P fw sched n x]
    show (run2 P fw sched n x).e.now + 1 = x.e.now + (n + 1)
    rw [now_run2 P fw sched n x]
    omega

theorem plain_run2 (P : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (hf : ∀ y, PlainW dly y.e.pl (fw y)) :
    ∀ (n : Nat) (x : Engine2), Plain dly x → Plain dly (run2 P fw sched n x)
  | 0, _, h => h
  | n + 1, x, h => plain_run2 P dly fw sched hf n _ (plain_step P dly fw _ x h hf)

/-- The five lanes, in index order. -/
def laneList : List Lane := [L0, L1, L2, L3, L4]

theorem mem_laneList (y : Lane) : y ∈ laneList := by
  rcases lane_cases y with h | h | h | h | h <;> subst h <;> simp [laneList]

/-- First ready lane in index order (the fallback scheduler). -/
def firstReady (P : Program) (e : Engine) : Option Lane :=
  laneList.find? (fun l => P.live l && decide (e.ts l ≤ e.now))

theorem firstReady_some (P : Program) (e : Engine) (w : Lane) (h : firstReady P e = some w) :
    P.live w = true ∧ e.ts w ≤ e.now := by
  have := List.find?_some h
  simp only [Bool.and_eq_true, decide_eq_true_eq] at this
  exact this

theorem firstReady_none (P : Program) (e : Engine) (h : firstReady P e = none) (y : Lane) :
    ¬Ready P y e := by
  intro hy
  have := (List.find?_eq_none.mp h) y (mem_laneList y)
  apply this
  simp [hy.1, hy.2]

/-- The v1 scheduler induced by `sched` along the trajectory from `x0`. -/
def win1 (P : Program) (P2 : Program2) (fw : Engine2 → Word) (sched : Engine2 → Option Lane)
    (x0 : Engine2) (e : Engine) : Option Lane :=
  match sched (run2 P2 fw sched (e.now - x0.e.now) x0) with
  | some w => if P.live w && decide (e.ts w ≤ e.now) then some w else firstReady P e
  | none   => firstReady P e

theorem win1_ready (P : Program) (P2 : Program2) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) :
    ∀ e w, win1 P P2 fw sched x0 e = some w → P.live w = true ∧ e.ts w ≤ e.now := by
  intro e w h
  unfold win1 at h
  split at h
  · split at h
    · rename_i hc
      cases h
      simp only [Bool.and_eq_true, decide_eq_true_eq] at hc
      exact hc
    · exact firstReady_some P e w h
  · exact firstReady_some P e w h

theorem win1_wc (P : Program) (P2 : Program2) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) :
    ∀ y e, Ready P y e → win1 P P2 fw sched x0 e ≠ none := by
  intro y e hy h
  unfold win1 at h
  split at h
  · split at h
    · cases h
    · exact firstReady_none P e h y hy
  · exact firstReady_none P e h y hy

/-- Along the trajectory, `win1` is `sched`, given the v2 scheduler's contract. -/
theorem win1_on (P : Program) (P2 : Program2) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2)
    (hsw : ∀ x w, sched x = some w → P.live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready P y x.e → sched x ≠ none) (n : Nat) :
    win1 P P2 fw sched x0 (run2 P2 fw sched n x0).e = sched (run2 P2 fw sched n x0) := by
  have hk : (run2 P2 fw sched n x0).e.now - x0.e.now = n := by
    rw [now_run2]
    omega
  unfold win1
  rw [hk]
  cases hs : sched (run2 P2 fw sched n x0) with
  | some w =>
    have := hsw _ w hs
    have hc : (P.live w && decide ((run2 P2 fw sched n x0).e.ts w ≤
        (run2 P2 fw sched n x0).e.now)) = true := by
      simp [this.1, this.2]
    dsimp only
    rw [if_pos hc]
  | none =>
    dsimp only
    cases hf : firstReady P (run2 P2 fw sched n x0).e with
    | none => rfl
    | some v =>
      have := firstReady_some P _ v hf
      exact absurd hs (hss v _ ⟨this.1, this.2⟩)

/-- **Run refinement.** On plain programs the projected v2 run is a v1 run. -/
theorem run2_proj (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2)
    (hx0 : Plain dly x0) (hf : ∀ y, PlainW dly y.e.pl (fw y))
    (hsw : ∀ x w, sched x = some w → (P2.toP dly).live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (P2.toP dly) y x.e → sched x ≠ none) :
    ∀ n, (run2 P2 fw sched n x0).e =
      run (P2.toP dly) (win1 (P2.toP dly) P2 fw sched x0) n x0.e
  | 0 => rfl
  | n + 1 => by
    rw [run2_succ', run_succ', ← run2_proj P2 dly fw sched x0 hx0 hf hsw hss n]
    rw [step_win_congr (P2.toP dly) (win1 (P2.toP dly) P2 fw sched x0),
      win1_on (P2.toP dly) P2 fw sched x0 hsw hss n]
    exact step2_proj P2 dly fw _ _ (plain_run2 P2 dly fw sched hf n x0 hx0)

/-- **D\* for the v2 engine on plain programs, d ≥ 39, no external hypotheses.**
For every plain program stream `fw` and every work-conserving v2 scheduler that picks a
ready lane: no dispatch decision ever stalls, and branch 1 never issues. -/
theorem dstar39_v2 (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2)
    (hx0 : Plain dly x0) (hf : ∀ y, PlainW dly y.e.pl (fw y))
    (hW : Wf x0.e) (hfull : ∀ l s, P2.live l = true → x0.e.actv l s = true)
    (h0 : x0.e.st = .idle) (h0ts : ∀ l, x0.e.now ≤ x0.e.ts l)
    (hsw : ∀ x w, sched x = some w → P2.live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (P2.toP dly) y x.e → sched x ≠ none)
    (hd : ∀ l, P2.live l = true → 39 ≤ dly l) :
    ∀ T, ((run2 P2 fw sched T x0).e.st = .idle →
            ∀ w, sched (run2 P2 fw sched T x0) = some w →
              (run2 P2 fw sched T x0).e.headValid w = true) ∧
         NoBr1 (P2.toP dly) (run2 P2 fw sched T x0).e := by
  intro T
  have hsw' : ∀ x w, sched x = some w → (P2.toP dly).live w = true ∧ x.e.ts w ≤ x.e.now :=
    hsw
  have key := dstar39 (P2.toP dly) (win1 (P2.toP dly) P2 fw sched x0) x0.e hW hfull h0 h0ts
    (win1_ready _ P2 fw sched x0) (fun y e _ hy => win1_wc _ P2 fw sched x0 y e hy) hd T
  have hr := run2_proj P2 dly fw sched x0 hx0 hf hsw' hss T
  rw [← hr] at key
  refine ⟨fun hi w hw => key.1 hi w ?_, key.2⟩
  rw [win1_on (P2.toP dly) P2 fw sched x0 hsw' hss T]
  exact hw

#print axioms dstar39_v2

end JLane

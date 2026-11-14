import JLane.HoldSt
/-!
# Bricks F0–F1 — the FALLTHROUGH flush: a step that can empty a lane (agent 1's batch, 11-14)

RTL, as built (agent 1, 11-14): a FALLTHROUGH ARM's edge takes PC+2 **at the edge**, emptying
both of the lane's slots (`l_actv[hix] <= 0; l_actv[six] <= 0`, `l_fpc <= PC+2`). A refill for
that lane already in flight is not aborted: the port runs REQ → WAIT → CAP as usual (4 cycles),
but an edge during REQ / WAIT sets `pkill` (l.4424) and CAP then files nothing (l.3269); an
edge in CAP's own cycle is written after the capture in the same `always` block, so the slot
ends empty. Agent 1's fix for the hole they found: the scan never selects a lane whose edge
fires that cycle — here, the port reads the program with that cycle's flushed lanes not live
(`liveFl`), which masks both the round-robin and the branch-1 choice.

F0 (`stepF`):
* `stepF_noflush` — with no flush and no kill it **is** the V4b step;
* `stepF_flush_empty` — a flushed lane has both slots empty after the cycle;
* `stepF_fill`, `stepF_kill_set`, `stepF_kill_keep` — a slot fills only by a live, unflushed
  capture; an edge on the lane in flight kills its refill until its CAP: **a refill selected or
  in flight at a flush is never filed**, while the port still spends its normal 4 cycles.

F1 (runs across flushes):
* `stepF_actv_le` — every slot `stepF` leaves valid, the V4b step leaves valid too;
* `struct_stepF` — the structural invariant survives a flush, given the flushed lane is not
  being dispatched (an armed lane never is, `Armed.ArmInv`);
* `killInv_step` — a kill is only ever pending in WAIT or CAP, so it clears within two cycles;
* `runF_seg` — **between flushes, with no kill pending, the run is a V4b run**: the whole
  library applies segment by segment.
-/
namespace JLane

/-- The engine with the port's kill register (`pkill`). -/
structure EngineF where
  e     : Engine
  pkill : Bool

/-- The program the port sees in a cycle with flushes `fl`: flushed lanes are not live, so the
scan selects none of them (agent 1's fix). -/
def liveFl (P : Program) (fl : Lane → Bool) : Program :=
  { P with live := fun l => P.live l && !fl l }

/-- The slot update with flushes and the kill. -/
def actvF (P : Program) (fl : Lane → Bool) (X : EngineF) (l : Lane) (s : Slot) : Bool :=
  if fl l = true then false
  else if X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true then X.e.actv l s
  else actvNext P X.e l s

/-- One cycle with flushes `fl`. -/
def stepF (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool) (X : EngineF) :
    EngineF :=
  { e := { step (liveFl P fl) win X.e with actv := actvF P fl X }
    pkill := if X.e.pst = .cap then false
             else X.pkill || (fl X.e.pl && (decide (X.e.pst = .req) || decide (X.e.pst = .wait))) }

/-- The V4b step reads `live` only in the port. -/
theorem step_liveFl (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool) (e : Engine)
    (hfl : ∀ l, fl l = false) : step (liveFl P fl) win e = step P win e := by
  have hl : (liveFl P fl).live = P.live := by
    funext l
    show (P.live l && !fl l) = P.live l
    rw [hfl l]
    simp
  have hp : portNext (liveFl P fl) e = portNext P e := by
    show portNextW (liveFl P fl) e.wantFetch e = portNextW P e.wantFetch e
    exact portNextW_live _ _ hl _ _
  show ({ now := e.now + 1, actv := actvNext (liveFl P fl) e, sel := selNext (liveFl P fl) e,
          ts := tsNext (liveFl P fl) e,
          pst := (portNext (liveFl P fl) e).pst, pl := (portNext (liveFl P fl) e).pl,
          prr := (portNext (liveFl P fl) e).prr, pbr1 := (portNext (liveFl P fl) e).pbr1,
          pslot := (portNext (liveFl P fl) e).pslot, winq := win e,
          st := (dispNext win e).st, cur := (dispNext win e).cur,
          npf := npfNext (liveFl P fl) e } : Engine) = step P win e
  rw [hp]
  rfl

/-- **No flush, no kill: the V4b step.** -/
theorem stepF_noflush (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hfl : ∀ l, fl l = false) (hk : X.pkill = false) :
    (stepF P win fl X).e = step P win X.e ∧ (stepF P win fl X).pkill = false := by
  constructor
  · have ha : actvF P fl X = actvNext P X.e := by
      funext l s
      unfold actvF
      rw [hfl l, hk]
      simp
    show { step (liveFl P fl) win X.e with actv := actvF P fl X } = step P win X.e
    rw [ha, step_liveFl P win fl X.e hfl]
    rfl
  · show (if X.e.pst = .cap then false
          else X.pkill || (fl X.e.pl && (decide (X.e.pst = .req) || decide (X.e.pst = .wait))))
        = false
    rw [hk, hfl X.e.pl]
    split <;> simp

/-- **A flushed lane is emptied.** -/
theorem stepF_flush_empty (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (l : Lane) (h : fl l = true) (s : Slot) :
    (stepF P win fl X).e.actv l s = false := by
  show actvF P fl X l s = false
  unfold actvF
  rw [if_pos h]

/-- **Only a live capture fills.** -/
theorem stepF_fill (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (l : Lane) (s : Slot) (h0 : X.e.actv l s = false)
    (h1 : (stepF P win fl X).e.actv l s = true) :
    X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = false ∧ fl l = false := by
  change actvF P fl X l s = true at h1
  unfold actvF at h1
  by_cases hf : fl l = true
  · rw [if_pos hf] at h1
    cases h1
  · rw [if_neg hf] at h1
    have hf' : fl l = false := by cases hc : fl l <;> simp_all
    by_cases hk : X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true
    · rw [if_pos hk, h0] at h1
      cases h1
    · rw [if_neg hk] at h1
      by_cases hc : X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot
      · refine ⟨hc.1, hc.2.1, hc.2.2, ?_, hf'⟩
        cases hp : X.pkill
        · rfl
        · exact absurd ⟨hc.1, hc.2.1, hc.2.2, hp⟩ hk
      · exfalso
        unfold actvNext at h1
        rw [if_neg hc] at h1
        split at h1
        · cases h1
        · rw [h0] at h1
          cases h1

/-- **An edge on the lane in flight kills its refill**, and the kill holds until its CAP. -/
theorem stepF_kill_set (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hp : X.e.pst = .req ∨ X.e.pst = .wait) (hf : fl X.e.pl = true) :
    (stepF P win fl X).pkill = true := by
  show (if X.e.pst = .cap then false
    else X.pkill || (fl X.e.pl && (decide (X.e.pst = .req) || decide (X.e.pst = .wait)))) = true
  rcases hp with hp | hp <;> rw [hp, hf] <;> simp

theorem stepF_kill_keep (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hk : X.pkill = true) (hc : X.e.pst ≠ .cap) :
    (stepF P win fl X).pkill = true := by
  show (if X.e.pst = .cap then false
    else X.pkill || (fl X.e.pl && (decide (X.e.pst = .req) || decide (X.e.pst = .wait)))) = true
  rw [if_neg hc, hk]
  rfl

/-! ### F1 — runs across flushes -/

/-- Every slot `stepF` leaves valid, the (masked-port) V4b step leaves valid too. -/
theorem stepF_actv_le (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hI : InFlightEmpty X.e) (l : Lane) (s : Slot)
    (h : (stepF P win fl X).e.actv l s = true) :
    (step (liveFl P fl) win X.e).actv l s = true := by
  change actvF P fl X l s = true at h
  show actvNext (liveFl P fl) X.e l s = true
  unfold actvF at h
  by_cases hf : fl l = true
  · rw [if_pos hf] at h
    cases h
  · rw [if_neg hf] at h
    by_cases hk : X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true
    · rw [if_pos hk] at h
      -- the in-flight slot is empty
      have hne : X.e.pst ≠ .scan := by rw [hk.1]; decide
      have := hI hne
      rw [← hk.2.1, ← hk.2.2.1] at this
      rw [this] at h
      cases h
    · rw [if_neg hk] at h
      exact h

/-- **The structural invariant survives a flush**, given no flushed lane is dispatched next. -/
theorem struct_stepF (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hS : Struct X.e)
    (hmid : ∀ l, fl l = true →
      ¬((dispNext win X.e).st ≠ .idle ∧ (dispNext win X.e).cur = l)) :
    Struct (stepF P win fl X).e := by
  obtain ⟨h1, h2⟩ := hS
  have hs := struct_step (liveFl P fl) win X.e ⟨h1, h2⟩
  obtain ⟨g1, g2⟩ := hs
  constructor
  · -- InFlightEmpty: stepF only clears slots relative to the step
    intro hne
    have hne' : (step (liveFl P fl) win X.e).pst ≠ .scan := hne
    have hz := g1 hne'
    cases hv : (stepF P win fl X).e.actv (stepF P win fl X).e.pl (stepF P win fl X).e.pslot
    · rfl
    · have := stepF_actv_le P win fl X h1 _ _ hv
      exact absurd (this.symm.trans hz) (by decide)
  · -- DispHeadValid: the dispatched lane is not flushed; a kill touches only the empty
    -- in-flight slot, never a valid head
    intro hne
    have hne' : (step (liveFl P fl) win X.e).st ≠ .idle := hne
    have hnd : (dispNext win X.e).st ≠ .idle := hne
    have hv := g2 hne'
    show actvF P fl X (dispNext win X.e).cur (selNext (liveFl P fl) X.e (dispNext win X.e).cur)
      = true
    unfold actvF
    have hnf : fl (dispNext win X.e).cur = false := by
      cases hc : fl (dispNext win X.e).cur
      · rfl
      · exact absurd ⟨hne', rfl⟩ (hmid _ hc)
    rw [hnf, if_neg (by decide)]
    by_cases hk : X.e.pst = .cap ∧ (dispNext win X.e).cur = X.e.pl ∧
        selNext (liveFl P fl) X.e (dispNext win X.e).cur = X.e.pslot ∧ X.pkill = true
    · -- the killed capture targets the in-flight slot, which is empty before the cycle; the
      -- step would fill it, but then the dispatched head was the in-flight slot: contradiction
      exfalso
      have hne0 : X.e.pst ≠ .scan := by rw [hk.1]; decide
      have hz0 := h1 hne0
      -- after the step that slot is valid only through the capture; the head of the lane
      -- dispatched next must already be valid now (a decision reads the head) or be the
      -- current dispatch's head
      have hv' : (step (liveFl P fl) win X.e).headValid (dispNext win X.e).cur = true := hv
      -- the step's head slot is the in-flight slot; before the step it was empty
      have hsel : (step (liveFl P fl) win X.e).sel (dispNext win X.e).cur = X.e.pslot := hk.2.2.1
      unfold Engine.headValid at hv'
      rw [hsel] at hv'
      -- so the dispatched lane's head before the step is not that slot or is empty: use the
      -- dispatch facts
      cases hst : X.e.st with
      | idle =>
        -- a fresh decision: it read the head valid now
        cases hw : win X.e with
        | none => simp [dispNext, hst, hw] at hnd
        | some w =>
          by_cases hvw : X.e.headValid w = true
          · have hcw : (dispNext win X.e).cur = w := by simp [dispNext, hst, hw, hvw]
            rw [hcw] at hk
            -- the decided lane's head is valid now and is not retired this cycle (idle)
            have hsel0 : selNext (liveFl P fl) X.e w = X.e.sel w := by
              unfold selNext
              rw [if_neg (by rw [hst]; intro h; cases h.1)]
            rw [hsel0] at hk
            unfold Engine.headValid at hvw
            rw [hk.2.2.1] at hvw
            rw [← hk.2.1] at hz0
            rw [hvw] at hz0
            cases hz0
          · simp [dispNext, hst, hw, hvw] at hnd
      | drive =>
        -- continuing dispatch: its head is valid now (DispHeadValid) and not retired yet
        have hcw : (dispNext win X.e).cur = X.e.cur := by simp [dispNext, hst]
        rw [hcw] at hk
        have hv0 := h2 (by rw [hst]; decide)
        have hsel0 : selNext (liveFl P fl) X.e X.e.cur = X.e.sel X.e.cur := by
          unfold selNext
          rw [if_neg (by rw [hst]; intro h; cases h.1)]
        rw [hsel0] at hk
        unfold Engine.headValid at hv0
        rw [hk.2.2.1] at hv0
        rw [← hk.2.1] at hz0
        rw [hv0] at hz0
        cases hz0
      | wb => simp [dispNext, hst] at hnd
    · rw [if_neg hk]
      exact hv

/-- A pending kill sits in WAIT or CAP. -/
def KillInv (X : EngineF) : Prop := X.pkill = true → X.e.pst = .wait ∨ X.e.pst = .cap

theorem killInv_step (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (h : KillInv X) : KillInv (stepF P win fl X) := by
  intro hk
  change (if X.e.pst = .cap then false
    else X.pkill || (fl X.e.pl && (decide (X.e.pst = .req) || decide (X.e.pst = .wait)))) = true
    at hk
  show (portNext (liveFl P fl) X.e).pst = .wait ∨ (portNext (liveFl P fl) X.e).pst = .cap
  cases hs : X.e.pst with
  | cap => rw [hs] at hk; simp at hk
  | scan =>
    rw [hs] at hk
    simp only [reduceCtorEq, ↓reduceIte, decide_false, Bool.or_false, Bool.and_false] at hk
    have := h hk
    rw [hs] at this
    rcases this with h' | h' <;> cases h'
  | req =>
    left
    show (portNextW (liveFl P fl) X.e.wantFetch X.e).pst = .wait
    simp [portNextW, hs]
  | wait =>
    right
    show (portNextW (liveFl P fl) X.e.wantFetch X.e).pst = .cap
    simp [portNextW, hs]

/-- `n` cycles with the flush input read by time. -/
def runF (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) :
    Nat → EngineF → EngineF
  | 0, X => X
  | n + 1, X => runF P win fl n (stepF P win (fl X.e.now) X)

/-- **Between flushes, with no kill pending, the run is a V4b run.** -/
theorem runF_seg (P : Program) (win : Engine → Option Lane) (fl : Nat → Lane → Bool) :
    ∀ (n : Nat) (X : EngineF), X.pkill = false →
      (∀ i, i < n → ∀ l, fl (X.e.now + i) l = false) →
      (runF P win fl n X).e = run P win n X.e ∧ (runF P win fl n X).pkill = false
  | 0, _, hk, _ => ⟨rfl, hk⟩
  | n + 1, X, hk, hfl => by
    obtain ⟨he, hk'⟩ := stepF_noflush P win (fl X.e.now) X
      (fun l => by have := hfl 0 (Nat.succ_pos n) l; rwa [Nat.add_zero] at this) hk
    have ih := runF_seg P win fl n (stepF P win (fl X.e.now) X) hk' (fun i hi l => by
      have h := hfl (i + 1) (Nat.succ_lt_succ hi) l
      show fl ((stepF P win (fl X.e.now) X).e.now + i) l = false
      rw [he]
      show fl (X.e.now + 1 + i) l = false
      rw [Nat.add_assoc, Nat.add_comm 1 i]
      exact h)
    show (runF P win fl n (stepF P win (fl X.e.now) X)).e = run P win n (step P win X.e) ∧ _
    rw [← he]
    exact ih

#print axioms stepF_noflush
#print axioms stepF_fill
#print axioms stepF_kill_set
#print axioms struct_stepF
#print axioms killInv_step
#print axioms runF_seg

end JLane

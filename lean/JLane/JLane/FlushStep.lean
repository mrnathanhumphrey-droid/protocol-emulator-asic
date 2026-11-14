import JLane.HoldSt
/-!
# Brick F0 — the FALLTHROUGH flush: a step that can empty a lane (agent 1's batch, 11-14)

RTL, as built (agent 1, 11-14): a FALLTHROUGH ARM's edge takes PC+2 **at the edge**, emptying
both of the lane's slots (`l_actv[hix] <= 0; l_actv[six] <= 0`, `l_fpc <= PC+2`). A refill for
that lane already in flight is not aborted: the port runs REQ → WAIT → CAP as usual (4 cycles),
but an edge during REQ / WAIT sets `pkill` (l.4424) and CAP then files nothing (l.3269); an
edge in CAP's own cycle is written after the capture in the same `always` block, so the slot
ends empty. Agent 1's fix for the hole they found: the scan never selects a lane whose edge
fires that cycle.

`stepF` is the V4b step with a flush input `fl` (the lanes whose FALLTHROUGH edge fires this
cycle) and the kill register:
* `stepF_noflush` — with no flush and no kill it **is** the V4b step: the existing library
  applies unchanged on flush-free stretches;
* `stepF_flush_empty` — a flushed lane has both slots empty after the cycle;
* `stepF_fill` — a slot of lane `l` is filled only by a capture for `l` with no kill and no
  flush that cycle; and `stepF_kill_set` — an edge on the lane in flight (REQ / WAIT) sets the
  kill, which holds until its CAP: **a refill selected or in flight at a flush is never
  filed**, while the port still spends its normal 4 cycles (port-occupancy facts unchanged).
-/
namespace JLane

/-- The engine with the port's kill register (`pkill`). -/
structure EngineF where
  e     : Engine
  pkill : Bool

/-- One cycle with flushes `fl`: the V4b step, the scan skipping flushed lanes (agent 1's fix),
the flushed lanes emptied, and a killed capture filing nothing. -/
def stepF (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool) (X : EngineF) :
    EngineF :=
  let e := X.e
  let p := portNextW P (fun l => e.wantFetch l && !fl l) e
  let d := dispNext win e
  { e := { now := e.now + 1
           actv := fun l s =>
             if fl l = true then false
             else if e.pst = .cap ∧ l = e.pl ∧ s = e.pslot ∧ X.pkill = true then e.actv l s
             else actvNext P e l s
           sel := selNext P e
           ts := tsNext P e
           pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot
           winq := win e
           st := d.st, cur := d.cur
           npf := npfNext P e }
    pkill := if e.pst = .cap then false
             else X.pkill || (fl e.pl && (decide (e.pst = .req) || decide (e.pst = .wait))) }

/-- **No flush, no kill: the V4b step.** -/
theorem stepF_noflush (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (hfl : ∀ l, fl l = false) (hk : X.pkill = false) :
    (stepF P win fl X).e = step P win X.e ∧ (stepF P win fl X).pkill = false := by
  have hw : (fun l => X.e.wantFetch l && !fl l) = X.e.wantFetch := by
    funext l
    rw [hfl l]
    simp
  constructor
  · show ({ now := X.e.now + 1
            actv := fun l s =>
              if fl l = true then false
              else if X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true then X.e.actv l s
              else actvNext P X.e l s
            sel := selNext P X.e
            ts := tsNext P X.e
            pst := (portNextW P (fun l => X.e.wantFetch l && !fl l) X.e).pst
            pl := (portNextW P (fun l => X.e.wantFetch l && !fl l) X.e).pl
            prr := (portNextW P (fun l => X.e.wantFetch l && !fl l) X.e).prr
            pbr1 := (portNextW P (fun l => X.e.wantFetch l && !fl l) X.e).pbr1
            pslot := (portNextW P (fun l => X.e.wantFetch l && !fl l) X.e).pslot
            winq := win X.e
            st := (dispNext win X.e).st, cur := (dispNext win X.e).cur
            npf := npfNext P X.e } : Engine) = step P win X.e
    have ha : (fun l s =>
        if fl l = true then false
        else if X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true then X.e.actv l s
        else actvNext P X.e l s) = actvNext P X.e := by
      funext l s
      rw [hfl l, hk]
      simp
    rw [hw, ha]
    rfl
  · show (if X.e.pst = .cap then false
          else X.pkill || (fl X.e.pl && (decide (X.e.pst = .req) || decide (X.e.pst = .wait))))
        = false
    rw [hk, hfl X.e.pl]
    split <;> simp

/-- **A flushed lane is emptied.** -/
theorem stepF_flush_empty (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (l : Lane) (h : fl l = true) (s : Slot) : (stepF P win fl X).e.actv l s = false := by
  show (if fl l = true then false
    else if X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true then X.e.actv l s
    else actvNext P X.e l s) = false
  rw [if_pos h]

/-- **Only a live capture fills.** A slot of lane `l` empty before and valid after was filled
by a capture for `l`, with no kill and no flush of `l` that cycle. -/
theorem stepF_fill (P : Program) (win : Engine → Option Lane) (fl : Lane → Bool)
    (X : EngineF) (l : Lane) (s : Slot) (h0 : X.e.actv l s = false)
    (h1 : (stepF P win fl X).e.actv l s = true) :
    X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = false ∧ fl l = false := by
  change (if fl l = true then false
    else if X.e.pst = .cap ∧ l = X.e.pl ∧ s = X.e.pslot ∧ X.pkill = true then X.e.actv l s
    else actvNext P X.e l s) = true at h1
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

#print axioms stepF_noflush
#print axioms stepF_fill
#print axioms stepF_kill_set

end JLane

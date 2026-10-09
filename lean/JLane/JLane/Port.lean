import JLane.Inv
/-!
# Brick 3 — the port wait bound
A ranking function `phi y` on the prefetch registers bounds the cycles until lane
`y`'s refill reaches `P_CAP`. Every cycle lowers it by ≥ 1, except a branch-1 issue
for another lane, which is charged `L_REFILL`. Holds for any winner function.
-/
namespace JLane

/-- Lane `y`'s refill is at `P_CAP` this cycle (its slot is valid next cycle). -/
def Hit (y : Lane) (e : Engine) : Prop := e.pst = .cap ∧ e.pl = y

/-- Cycles until the FSM is back in `P_SCAN`. -/
def rem : PState → Nat
  | .scan => 0
  | .req  => 3
  | .wait => 2
  | .cap  => 1

/-- Round-robin distance from pointer `a` to lane `y`. -/
def dist (a y : Lane) : Nat := (y.val + K - a.val) % K

/-- Where the pointer will be once the in-flight refill completes (§1: a branch-2
capture sets `prr <= pl + 1`; a branch-1 capture leaves it). -/
def ptr (p : Port) : Lane :=
  if p.pst ≠ .scan ∧ p.pbr1 = false then nextLane p.pl else p.prr

/-- The ranking function. -/
def phi (y : Lane) (p : Port) : Nat :=
  if p.pst ≠ .scan ∧ p.pl = y then rem p.pst - 1
  else rem p.pst + L_REFILL * dist (ptr p) y + 3

def portOf (e : Engine) : Port := ⟨e.pst, e.pl, e.prr, e.pbr1, e.pslot⟩

/-- `L_REFILL` if this cycle issues a branch-1 refill for a lane other than `y`. -/
def charge (P : Program) (y : Lane) (e : Engine) : Nat :=
  match br1 P e with
  | some w => if e.pst = .scan ∧ w ≠ y then L_REFILL else 0
  | none   => 0

/-- Total charge over `n` cycles. -/
def chargeSum (P : Program) (win : Engine → Option Lane) (y : Lane) : Nat → Engine → Nat
  | 0, _ => 0
  | n + 1, e => charge P y e + chargeSum P win y n (step P win e)

/-! ### Arithmetic of the pointer -/

theorem dist_self (y : Lane) : dist y y = 0 := by
  show (y.val + 5 - y.val) % 5 = 0
  omega

theorem dist_le (a y : Lane) : dist a y ≤ 4 := by
  show (y.val + 5 - a.val) % 5 ≤ 4
  omega

theorem dist_next (a y : Lane) (h : a ≠ y) : dist (nextLane a) y + 1 = dist a y := by
  have ha : a.val < 5 := a.isLt
  have hy : y.val < 5 := y.isLt
  have hne : a.val ≠ y.val := fun h' => h (Fin.eq_of_val_eq h')
  show (y.val + 5 - (a.val + 1) % 5) % 5 + 1 = (y.val + 5 - a.val) % 5
  omega

theorem rem_le (s : PState) : rem s ≤ 3 := by
  cases s <;> decide

theorem phi_le (y : Lane) (p : Port) : phi y p ≤ 22 := by
  have h1 := rem_le p.pst
  have h3 : L_REFILL * dist (ptr p) y ≤ 16 := by
    have := dist_le (ptr p) y
    show 4 * dist (ptr p) y ≤ 16
    omega
  unfold phi
  split <;> omega

theorem twentytwo : (K + 1) * L_REFILL - 2 = 22 := rfl

/-! ### The port FSM, case by case -/

theorem portOf_step (P : Program) (win : Engine → Option Lane) (e : Engine) :
    portOf (step P win e) = portNext P e := rfl

theorem portNext_req (P : Program) (e : Engine) (hp : e.pst = .req) :
    portNext P e = ⟨.wait, e.pl, e.prr, e.pbr1, e.pslot⟩ := by
  simp [portNext, hp]

theorem portNext_wait (P : Program) (e : Engine) (hp : e.pst = .wait) :
    portNext P e = ⟨.cap, e.pl, e.prr, e.pbr1, e.pslot⟩ := by
  simp [portNext, hp]

theorem portNext_cap (P : Program) (e : Engine) (hp : e.pst = .cap) :
    portNext P e =
      ⟨.scan, e.pl, if e.pbr1 then e.prr else nextLane e.pl, e.pbr1, e.pslot⟩ := by
  simp [portNext, hp]

theorem portNext_br1 (P : Program) (e : Engine) {w : Lane} (hp : e.pst = .scan)
    (hb : br1 P e = some w) :
    portNext P e = ⟨.req, w, e.prr, true, e.sel w⟩ := by
  simp [portNext, hp, hb]

theorem portNext_br2 (P : Program) (e : Engine) (hp : e.pst = .scan) (hb : br1 P e = none)
    (hc : (P.live e.prr && e.wantFetch e.prr) = true) :
    portNext P e = ⟨.req, e.prr, e.prr, false, e.fetchSlot e.prr⟩ := by
  unfold portNext
  rw [hp]
  dsimp only
  rw [hb]
  dsimp only
  rw [if_pos hc] <;> rfl

theorem portNext_skip (P : Program) (e : Engine) (hp : e.pst = .scan) (hb : br1 P e = none)
    (hc : ¬(P.live e.prr && e.wantFetch e.prr) = true) :
    portNext P e = ⟨.scan, e.pl, nextLane e.prr, e.pbr1, e.pslot⟩ := by
  unfold portNext
  rw [hp]
  dsimp only
  rw [hb]
  dsimp only
  rw [if_neg hc] <;> rfl

theorem charge_br1 (P : Program) (y : Lane) (e : Engine) {w : Lane} (hp : e.pst = .scan)
    (hb : br1 P e = some w) (hwy : w ≠ y) : charge P y e = L_REFILL := by
  simp [charge, hb, hp, hwy]

/-! ### One cycle -/

theorem phi_step (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (hy : P.live y = true) (hw : e.wantFetch y = true) (hn : ¬Hit y e) :
    phi y (portOf (step P win e)) + 1 ≤ phi y (portOf e) + charge P y e := by
  unfold Hit at hn
  rw [portOf_step]
  cases hp : e.pst with
  | req =>
    rw [portNext_req P e hp]
    by_cases hl : e.pl = y
    · simp [phi, portOf, rem, hp, hl] <;> omega
    · cases hb : e.pbr1 <;> simp [phi, ptr, portOf, rem, L_REFILL, hp, hl, hb] <;> omega
  | wait =>
    rw [portNext_wait P e hp]
    by_cases hl : e.pl = y
    · simp [phi, portOf, rem, hp, hl] <;> omega
    · cases hb : e.pbr1 <;> simp [phi, ptr, portOf, rem, L_REFILL, hp, hl, hb] <;> omega
  | cap =>
    have hl : e.pl ≠ y := fun h => hn ⟨hp, h⟩
    rw [portNext_cap P e hp]
    cases hb : e.pbr1 <;> simp [phi, ptr, portOf, rem, L_REFILL, hp, hl, hb] <;> omega
  | scan =>
    cases hb : br1 P e with
    | some w =>
      rw [portNext_br1 P e hp hb]
      by_cases hwy : w = y
      · simp [phi, ptr, portOf, rem, L_REFILL, hp, hwy] <;> omega
      · have hch : charge P y e = L_REFILL := charge_br1 P y e hp hb hwy
        simp [phi, ptr, portOf, rem, L_REFILL, hp, hwy, hch] <;> omega
    | none =>
      by_cases hc : (P.live e.prr && e.wantFetch e.prr) = true
      · rw [portNext_br2 P e hp hb hc]
        by_cases hpy : e.prr = y
        · simp [phi, ptr, portOf, rem, L_REFILL, hp, hpy, dist_self] <;> omega
        · have hd := dist_next e.prr y hpy
          simp [phi, ptr, portOf, rem, L_REFILL, hp, hpy] <;> omega
      · have hpy : e.prr ≠ y := fun h => hc (by simp [h, hy, hw])
        have hd := dist_next e.prr y hpy
        rw [portNext_skip P e hp hb hc]
        simp [phi, ptr, portOf, rem, L_REFILL, hp] <;> omega

/-! ### The owed slot stays owed until it is served -/

theorem owed_pos_of (e : Engine) (l : Lane) (s : Slot) (h : e.actv l s = false) :
    1 ≤ e.owed l := by
  unfold Engine.owed
  cases s with
  | false => rw [h]; cases e.actv l true <;> decide
  | true  => rw [h]; cases e.actv l false <;> decide

theorem actvNext_false_of (e : Engine) (l : Lane) (s : Slot)
    (hn : ¬(e.pst = .cap ∧ l = e.pl)) (h : e.actv l s = false) : actvNext e l s = false := by
  unfold actvNext
  by_cases hw : e.st = .wb ∧ l = e.cur ∧ s = e.sel e.cur
  · rw [if_pos hw]
  · rw [if_neg hw, if_neg (fun h' => hn ⟨h'.1, h'.2.1⟩), h]

theorem want_step (P : Program) (win : Engine → Option Lane) (y : Lane) (e : Engine)
    (hw : e.wantFetch y = true) (hn : ¬Hit y e) : (step P win e).wantFetch y = true := by
  unfold Hit at hn
  rw [Engine.wantFetch_iff] at hw ⊢
  have hn' : ¬(e.pst = .cap ∧ y = e.pl) := fun h => hn ⟨h.1, h.2.symm⟩
  obtain ⟨s, hs⟩ : ∃ s, e.actv y s = false := by
    unfold Engine.owed at hw
    cases h0 : e.actv y false
    · exact ⟨false, h0⟩
    · cases h1 : e.actv y true
      · exact ⟨true, h1⟩
      · rw [h0, h1] at hw
        exact absurd hw (by decide)
  exact owed_pos_of (step P win e) y s (actvNext_false_of e y s hn' hs)

/-! ### The bound -/

theorem port_wait (P : Program) (win : Engine → Option Lane) (y : Lane)
    (hy : P.live y = true) :
    ∀ (n : Nat) (e : Engine), e.wantFetch y = true →
      (∀ i, i < n → ¬Hit y (run P win i e)) →
      phi y (portOf (run P win n e)) + n ≤ phi y (portOf e) + chargeSum P win y n e
  | 0, e, _, _ => by simp [run, chargeSum]
  | n + 1, e, hw, hnh => by
    have h0 : ¬Hit y e := hnh 0 (Nat.succ_pos n)
    have hstep := phi_step P win y e hy hw h0
    have ih := port_wait P win y hy n (step P win e) (want_step P win y e hw h0)
      (fun i hi => hnh (i + 1) (Nat.succ_lt_succ hi))
    show phi y (portOf (run P win n (step P win e))) + (n + 1)
      ≤ phi y (portOf e) + (charge P y e + chargeSum P win y n (step P win e))
    omega

/-- **Port wait bound.** A live lane that owes a slot reaches `P_CAP` within
`(K+1)·L_REFILL − 2 = 22` cycles plus `L_REFILL` per branch-1 refill issued for
another lane in the window. -/
theorem port_wait_bound (P : Program) (win : Engine → Option Lane) (y : Lane)
    (hy : P.live y = true) (n : Nat) (e : Engine) (hw : e.wantFetch y = true)
    (hnh : ∀ i, i < n → ¬Hit y (run P win i e)) :
    n ≤ 22 + chargeSum P win y n e := by
  have h := port_wait P win y hy n e hw hnh
  have h2 := phi_le y (portOf e)
  omega

end JLane

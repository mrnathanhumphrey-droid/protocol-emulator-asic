import JLane.NpfB
/-!
# Brick C3d — the buffered engine as lane `y` sees it, along any trajectory
(`slot_on_composition`, step 3a: the foundation for the flush as a restart)

A FALLTHROUGH flush replaces the flushed lane's state (Wilson 11-18, the restart shape), and other
lanes' flushes move the port and the charges `y` sees; so the per-retirement certificate is
proved along an **abstract trajectory** `τ : Nat → EngB` whose every cycle agrees with `stepB` on
what lane `y`'s proofs read (`AgreeY`): the port registers (captures, `phi`, the charges are read
off `τ` itself), the clock and the dispatch FSM, and `y`'s own timestamp, select, slots,
no-prefetch flags and buffer. `runB` is one such trajectory; `runBK` between `y`'s flushes, with
no killed capture landing on `y`, is another (step 3c).

Here: counts and charges along `τ`, the clock, timestamps, the port wait bound (`phi_stepB`,
`want_stepB` transferred), conservation and the head bridge (`held_step`, `head_of_held`), and the
no-prefetch hold and unlock (`want_frozenB`, `npf_unlockB`) -- each one BufEng's / NpfB's lemma on
`stepB (τ n)`, carried to `τ (n + 1)` by `AgreeY`.
-/
namespace JLane

/-- `a` agrees with `b` on everything lane `y`'s certificate reads. -/
def AgreeY (y : Lane) (a b : EngB) : Prop :=
  portOf a.e = portOf b.e ∧ a.e.now = b.e.now ∧ a.e.st = b.e.st ∧ a.e.cur = b.e.cur ∧
    a.e.ts y = b.e.ts y ∧ a.e.sel y = b.e.sel y ∧ (∀ s, a.e.actv y s = b.e.actv y s) ∧
    (∀ s, a.e.npf y s = b.e.npf y s) ∧ a.buf y = b.buf y

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (y : Lane) (τ : Nat → EngB)

/-- `τ` steps as `stepB` does, for `y`, on every cycle before `T`. -/
def TrajY (T : Nat) : Prop := ∀ n, n < T → AgreeY y (τ (n + 1)) (stepB P win usb sreq (τ n))

/-! ### Reading `AgreeY` -/

theorem agree_pst {a b : EngB} (h : AgreeY y a b) : a.e.pst = b.e.pst := by
  have := congrArg Port.pst h.1; exact this
theorem agree_pl {a b : EngB} (h : AgreeY y a b) : a.e.pl = b.e.pl := by
  have := congrArg Port.pl h.1; exact this
theorem agree_pbr1 {a b : EngB} (h : AgreeY y a b) : a.e.pbr1 = b.e.pbr1 := by
  have := congrArg Port.pbr1 h.1; exact this

theorem agree_hit {a b : EngB} (h : AgreeY y a b) : Hit y a.e ↔ Hit y b.e := by
  unfold Hit; rw [agree_pst y h, agree_pl y h]

theorem agree_ret {a b : EngB} (h : AgreeY y a b) : IsRet P y a.e ↔ IsRet P y b.e := by
  unfold IsRet; rw [h.2.2.1, h.2.2.2.1, h.2.1]

theorem agree_wb {a b : EngB} (h : AgreeY y a b) : IsWB y a.e ↔ IsWB y b.e := by
  unfold IsWB; rw [h.2.2.1, h.2.2.2.1]

theorem agree_held {a b : EngB} (h : AgreeY y a b) : a.held y = b.held y := by
  rw [held_def, held_def, h.2.2.2.2.2.2.1 false, h.2.2.2.2.2.2.1 true, h.2.2.2.2.2.2.2.2]

theorem agree_owed {a b : EngB} (h : AgreeY y a b) : a.e.owed y = b.e.owed y := by
  unfold Engine.owed; rw [h.2.2.2.2.2.2.1 false, h.2.2.2.2.2.2.1 true]

theorem agree_want {a b : EngB} (h : AgreeY y a b) : a.e.wantFetch y = b.e.wantFetch y := by
  unfold Engine.wantFetch Engine.headValid Engine.spareValid
  rw [h.2.2.2.2.2.1, h.2.2.2.2.2.2.1, h.2.2.2.2.2.2.1, h.2.2.2.2.2.2.2.1]

theorem agree_head {a b : EngB} (h : AgreeY y a b) : a.e.headValid y = b.e.headValid y := by
  unfold Engine.headValid; rw [h.2.2.2.2.2.1, h.2.2.2.2.2.2.1]

theorem agree_npfAt {a b : EngB} (h : AgreeY y a b) : NpfAt y a.e ↔ NpfAt y b.e := by
  unfold NpfAt; rw [h.2.2.2.2.2.1, h.2.2.2.2.2.2.2.1]

/-! ### Counts and charges along `τ` -/

/-- How many of the cycles `0 … n-1` of `τ` satisfy `Q`. -/
def cntT (Q : EngB → Prop) [DecidablePred Q] : Nat → Nat
  | 0 => 0
  | n + 1 => cntT Q n + (if Q (τ n) then 1 else 0)

/-- The charge to `y` over the `m` cycles of `τ` from `a`. -/
def chargeSumT : Nat → Nat → Nat
  | _, 0 => 0
  | a, m + 1 => chargeB P usb sreq y (τ a) + chargeSumT (a + 1) m

theorem cntT_mono (Q : EngB → Prop) [DecidablePred Q] (a : Nat) :
    ∀ b, a ≤ b → cntT τ Q a ≤ cntT τ Q b
  | 0, h => by have : a = 0 := by omega
               subst this; exact Nat.le_refl _
  | b + 1, h => by
    rcases Nat.lt_or_ge a (b + 1) with hlt | hge
    · have := cntT_mono Q a b (by omega)
      show cntT τ Q a ≤ cntT τ Q b + _
      omega
    · have : a = b + 1 := by omega
      subst this; exact Nat.le_refl _

theorem no_event_betweenT (Q : EngB → Prop) [DecidablePred Q] (a b i : Nat) (hai : a ≤ i)
    (hib : i < b) (heq : cntT τ Q a = cntT τ Q b) : ¬Q (τ i) := by
  intro hq
  have h1 := cntT_mono τ Q a i hai
  have h2 := cntT_mono τ Q (i + 1) b (by omega)
  have h3 : cntT τ Q (i + 1) = cntT τ Q i + 1 := by
    show cntT τ Q i + (if Q (τ i) then 1 else 0) = _
    rw [if_pos hq]
  omega

theorem cntT_reach (Q : EngB → Prop) [DecidablePred Q] :
    ∀ (n k : Nat), k < cntT τ Q n → ∃ t, t < n ∧ cntT τ Q t = k ∧ Q (τ t)
  | 0, k, h => by simp [cntT] at h
  | n + 1, k, h => by
    by_cases hk : k < cntT τ Q n
    · obtain ⟨t, ht, hc, hq⟩ := cntT_reach Q n k hk
      exact ⟨t, by omega, hc, hq⟩
    · have e : cntT τ Q (n + 1) = cntT τ Q n + (if Q (τ n) then 1 else 0) := rfl
      by_cases hq : Q (τ n)
      · rw [if_pos hq] at e
        exact ⟨n, by omega, by omega, hq⟩
      · rw [if_neg hq] at e
        omega

theorem cntT_succ (Q : EngB → Prop) [DecidablePred Q] (n : Nat) :
    cntT τ Q (n + 1) = cntT τ Q n + (if Q (τ n) then 1 else 0) := rfl

/-! ### The clock and timestamps -/

theorem now_T (T : Nat) (hT : TrajY P win usb sreq y τ T) :
    ∀ n, n ≤ T → (τ n).e.now = (τ 0).e.now + n
  | 0, _ => rfl
  | n + 1, h => by
    have ih := now_T T hT n (by omega)
    have ha := (hT n (by omega)).2.1
    rw [ha]
    show (stepB P win usb sreq (τ n)).e.now = _
    rw [stepB_e_now, ih]
    omega

theorem ts_stepT (T : Nat) (hT : TrajY P win usb sreq y τ T) (n : Nat) (hn : n < T) :
    (τ (n + 1)).e.ts y = (τ n).e.ts y + (if IsWB y (τ n).e then P.dly y + P.ext (τ n).e.now y else 0) := by
  rw [(hT n hn).2.2.2.2.1]
  exact ts_step P win (τ n).e y

theorem ts_monoT (T : Nat) (hT : TrajY P win usb sreq y τ T) (m : Nat) :
    ∀ j, m + j ≤ T → (τ m).e.ts y ≤ (τ (m + j)).e.ts y
  | 0, _ => Nat.le_refl _
  | j + 1, h => by
    have ih := ts_monoT T hT m j (by omega)
    have hs := ts_stepT P win usb sreq y τ T hT (m + j) (by omega)
    rw [← Nat.add_assoc, hs]
    split <;> omega

theorem ts_after_wbT (T : Nat) (hT : TrajY P win usb sreq y τ T) (t : Nat) (ht : t < T)
    (h : IsWB y (τ t).e) :
    (τ (t + 1)).e.ts y = (τ t).e.ts y + P.dly y + P.ext (τ t).e.now y := by
  rw [ts_stepT P win usb sreq y τ T hT t ht, if_pos h, Nat.add_assoc]

/-! ### The port wait along `τ` -/

theorem port_waitT (hok : SReqB P sreq) (hy : P.live y = true) (T : Nat)
    (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n)) :
    ∀ (n a : Nat), a + n ≤ T → (τ a).e.wantFetch y = true → (τ a).buf y = false →
      (∀ i, i < n → ¬Hit y (τ (a + i)).e) →
      phi y (portOf (τ (a + n)).e) + n ≤ phi y (portOf (τ a).e) + chargeSumT P usb sreq y τ a n
  | 0, a, _, _, _, _ => by simp [chargeSumT]
  | n + 1, a, han, hw, hb, hnh => by
    have h0 : ¬Hit y (τ a).e := by have := hnh 0 (Nat.succ_pos n); simpa using this
    have hag := hT a (by omega)
    have hstep := phi_stepB P win usb sreq y (τ a) hy hw hb h0
    have hws := want_stepB P win usb sreq y (τ a) (hWf a (by omega)) hw hb h0
    have hw1 : (τ (a + 1)).e.wantFetch y = true := by rw [agree_want y hag]; exact hws.1
    have hb1 : (τ (a + 1)).buf y = false := by rw [hag.2.2.2.2.2.2.2.2]; exact hws.2
    have ih := port_waitT hok hy T hT hWf n (a + 1) (by omega) hw1 hb1
      (fun i hi => by have := hnh (i + 1) (by omega); rwa [show a + (i + 1) = a + 1 + i by omega] at this)
    have hp : phi y (portOf (τ (a + 1)).e) = phi y (portOf (stepB P win usb sreq (τ a)).e) := by
      rw [hag.1]
    rw [show a + (n + 1) = a + 1 + n by omega]
    show _ ≤ phi y (portOf (τ a).e) + (chargeB P usb sreq y (τ a) + chargeSumT P usb sreq y τ (a + 1) n)
    omega

theorem window_leT (hok : SReqB P sreq) (hy : P.live y = true) (T : Nat)
    (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n)) (a B n : Nat)
    (han : a + n ≤ T) (hw : (τ a).e.wantFetch y = true) (hb : (τ a).buf y = false)
    (hB : ∀ m, m ≤ n → m ≤ 23 + B → chargeSumT P usb sreq y τ a m ≤ B)
    (hnh : ∀ i, i < n → ¬Hit y (τ (a + i)).e) : n ≤ 22 + B := by
  by_cases hn : n ≤ 23 + B
  · have h := port_waitT P win usb sreq y τ hok hy T hT hWf n a han hw hb hnh
    have h2 := phi_le y (portOf (τ a).e)
    have := hB n (Nat.le_refl n) hn
    omega
  · have h := port_waitT P win usb sreq y τ hok hy T hT hWf (23 + B) a (by omega) hw hb
      (fun i hi => hnh i (by omega))
    have h2 := phi_le y (portOf (τ a).e)
    have := hB (23 + B) (by omega) (Nat.le_refl _)
    omega

theorem window_le_19T (hok : SReqB P sreq) (hy : P.live y = true) (T : Nat)
    (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n)) (a B n : Nat)
    (han : a + n ≤ T) (hw : (τ a).e.wantFetch y = true) (hb : (τ a).buf y = false)
    (hq : (τ a).e.pst = .scan ∨ (τ a).e.pbr1 = false)
    (hB : ∀ m, m ≤ n → m ≤ 23 + B → chargeSumT P usb sreq y τ a m ≤ B)
    (hnh : ∀ i, i < n → ¬Hit y (τ (a + i)).e) : n ≤ 19 + B := by
  have hq' : phi y (portOf (τ a).e) ≤ 19 := phi_le_19 y (portOf (τ a).e) hq
  by_cases hn : n ≤ 23 + B
  · have h := port_waitT P win usb sreq y τ hok hy T hT hWf n a han hw hb hnh
    have := hB n (Nat.le_refl n) hn
    omega
  · have h := port_waitT P win usb sreq y τ hok hy T hT hWf (23 + B) a (by omega) hw hb
      (fun i hi => hnh i (by omega))
    have := hB (23 + B) (by omega) (Nat.le_refl _)
    omega

theorem hit_then_scanT (T : Nat) (hT : TrajY P win usb sreq y τ T) (n : Nat) (hn : n < T)
    (hh : Hit y (τ n).e) : (τ (n + 1)).e.pst = .scan := by
  rw [agree_pst y (hT n hn)]
  exact hit_then_scanB P win usb sreq y (τ n) hh

/-! ### Conservation and the head bridge along `τ` -/

theorem held_runT (T : Nat) (hT : TrajY P win usb sreq y τ T) (hWf : ∀ n, n ≤ T → WfB (τ n)) :
    ∀ n, n ≤ T → (τ n).held y + cntT τ (fun z => IsRet P y z.e) n
      = (τ 0).held y + cntT τ (fun z => Hit y z.e) n
  | 0, _ => by simp [cntT]
  | n + 1, h => by
    have ih := held_runT T hT hWf n (by omega)
    have hag := hT n (by omega)
    have hs := held_step P win usb sreq (τ n) (hWf n (by omega)) y
    rw [← agree_held y hag] at hs
    have e1 : cntT τ (fun z => IsRet P y z.e) (n + 1)
        = cntT τ (fun z => IsRet P y z.e) n + (if IsRet P y (τ n).e then 1 else 0) := rfl
    have e2 : cntT τ (fun z => Hit y z.e) (n + 1)
        = cntT τ (fun z => Hit y z.e) n + (if Hit y (τ n).e then 1 else 0) := rfl
    rw [e1, e2]
    omega

theorem head_valid_of_countsT (T : Nat) (hT : TrajY P win usb sreq y τ T)
    (hWf : ∀ n, n ≤ T → WfB (τ n)) (n : Nat) (hn : n ≤ T)
    (h : cntT τ (fun z => IsRet P y z.e) n + 1 ≤ cntT τ (fun z => Hit y z.e) n + (τ 0).held y) :
    (τ n).e.headValid y = true := by
  have hr := held_runT P win usb sreq y τ T hT hWf n hn
  exact head_of_held _ (hWf n hn) y (by omega)

/-! ### The no-prefetch hold along `τ` -/

theorem npf_holdT (T : Nat) (hT : TrajY P win usb sreq y τ T) (s : Nat)
    (ho : 1 ≤ (τ s).e.owed y) (hw : (τ s).e.wantFetch y = false) (hb : (τ s).buf y = false) :
    ∀ k, s + k ≤ T → (∀ i, i < k → ¬Hit y (τ (s + i)).e ∧ ¬IsRet P y (τ (s + i)).e) →
      1 ≤ (τ (s + k)).e.owed y ∧ (τ (s + k)).e.wantFetch y = false ∧ (τ (s + k)).buf y = false
  | 0, _, _ => ⟨ho, hw, hb⟩
  | k + 1, hk, h => by
    obtain ⟨ihk, ihw, ihb⟩ := npf_holdT T hT s ho hw hb k (by omega) (fun i hi => h i (by omega))
    obtain ⟨hnh, hnr⟩ := h k (Nat.lt_succ_self k)
    obtain ⟨hw', _hsel, hact, _hnpf, hb'⟩ :=
      want_frozenB P win usb sreq _ y hnh (not_ret_form P y _ hnr) ihb
    have hag := hT (s + k) (by omega)
    rw [← Nat.add_assoc]
    refine ⟨?_, ?_, ?_⟩
    · rw [agree_owed y hag]
      unfold Engine.owed at ihk ⊢
      rw [hact, hact]
      exact ihk
    · rw [agree_want y hag, hw']; exact ihw
    · rw [hag.2.2.2.2.2.2.2.2]; exact hb'

theorem npf_unlockT (T : Nat) (hT : TrajY P win usb sreq y τ T) (n : Nat) (hn : n < T)
    (ho : 1 ≤ (τ n).e.owed y) (hw : (τ n).e.wantFetch y = false) (hnh : ¬Hit y (τ n).e)
    (hb : (τ n).buf y = false) (hr : IsRet P y (τ n).e) :
    (τ (n + 1)).e.wantFetch y = true ∧ (τ (n + 1)).buf y = false ∧ NpfAt y (τ n).e := by
  obtain ⟨hw', hb', hnpf⟩ := npf_unlockB P win usb sreq (τ n) y ho hw hnh hb (ret_form P y _ hr)
  have hag := hT n hn
  exact ⟨by rw [agree_want y hag]; exact hw', by rw [hag.2.2.2.2.2.2.2.2]; exact hb', hnpf⟩

end

#print axioms port_waitT
#print axioms window_leT
#print axioms held_runT
#print axioms head_valid_of_countsT
#print axioms npf_holdT
#print axioms npf_unlockT

end JLane

import JLane.UsbLane
/-!
# Brick P — retirement spacing per pair (Wilson 11-13)

The proof only ever needed this of a lane whose retirements drive branch 1: **consecutive
retirements release at least `R + 25` apart** (`RetSpaced`). "d ≥ 42" was a per-lane shortcut
for it. Wilson 11-13 replaces it by the **pair condition**: for every two consecutive
retirements on the lane, the earlier word's last writeback delay plus the next word's held
bits, each at its delay, is at least `R + 25`.

Here `RetSpaced` is **derived** from the pair condition on the v2 engine with self-timed
bytes (`retSpaced_of_pairs`), and `dstar_usb_pairs` is `dstar_usb_st` with the USB lane's
`RetSpaced` hypothesis replaced by it. What it rests on:
* `StlCounter`: the free input `Program2.stl` is tied to the bit counter. The RTL has
  `st_last_b = (l_ckbit[cur] == st_lastix)` (`pe_engine.v` l.2040), so a self-timed word ends
  on a non-stuff dispatch only once `ckbit ≥ lx`. The buffer send's `st_last` is the buffer
  length (l.2093); its word carries `lx = 0`, for which the tie says nothing.
* the counter itself is the model's (`Engine2.ckbitNext`, l.3678–3680): reset when a
  self-timed word retires, `+1` on each held non-stuff bit. `ck_inv` proves it is `0` after
  every retirement of the lane, with **no stall hypothesis**: `Struct` (dispatch only on a
  valid head; a capture only into an empty slot) keeps the head word fixed while bits are held.
* `PairCond`: stated over the run's consecutive retirements. `proof_constants.retire_pairs`
  computes it over the lane's program order. The two agree when the lane's words reach the
  head in program order: the port's addressing, abstracted in v1 (`State.lean`: addresses
  decide what, never when). A **read** premise, named here.

Outside the fragment, and so outside this brick: branch opcodes and ARM (the branch-semantics
brick, Wilson 11-13 Question A), clocked actions, chaining re-arms.
-/
namespace JLane

/-- The held bits a word claims: its `lx` if it is self-timed, else none. -/
def lxOf (w : Word) : Nat := if w.op = .st then w.lx else 0

/-- Lane `u` retires an action on this v2 cycle. -/
abbrev Ret2 (P2 : Program2) (u : Lane) (x : Engine2) : Prop :=
  x.e.st = .wb ∧ x.e.cur = u ∧ x.retire P2 = true

/-- **The bit-counter tie** (`st_last_b = (l_ckbit == st_lastix)`). Whenever lane `u` writes
back a self-timed word on its last, non-stuff dispatch, its bit counter has reached the word's
`lx`. -/
def StlCounter (P2 : Program2) (fw : Engine2 → Word) (sched : Engine2 → Option Lane)
    (x0 : Engine2) (u : Lane) : Prop :=
  ∀ n, (run2 P2 fw sched n x0).e.st = .wb → (run2 P2 fw sched n x0).e.cur = u →
    ((run2 P2 fw sched n x0).head u).op = .st →
    P2.stl (run2 P2 fw sched n x0).e.now u = true →
    P2.stuff (run2 P2 fw sched n x0).e.now u = false →
    ((run2 P2 fw sched n x0).head u).lx ≤ (run2 P2 fw sched n x0).ckbit u

/-- **The pair condition** (Wilson 11-13), over consecutive retirements `a < c` of lane `u`:
the word retiring at `a` (its last writeback delay) plus the held bits of the word retiring at
`c`, each at its delay, is at least `D`. -/
def PairCond (P2 : Program2) (fw : Engine2 → Word) (sched : Engine2 → Option Lane)
    (x0 : Engine2) (u : Lane) (D : Nat) : Prop :=
  ∀ a c, a < c → Ret2 P2 u (run2 P2 fw sched a x0) → Ret2 P2 u (run2 P2 fw sched c x0) →
    (∀ m, a < m → m < c → ¬Ret2 P2 u (run2 P2 fw sched m x0)) →
    D ≤ ((run2 P2 fw sched a x0).head u).dly +
      lxOf ((run2 P2 fw sched c x0).head u) * ((run2 P2 fw sched c x0).head u).dly

/-! ### One cycle -/

/-- In the fragment, a word that is not self-timed retires on its writeback. -/
theorem retire_frag (P2 : Program2) (dly : Lane → Nat) (x : Engine2) (h : StFrag dly x)
    (hne : (x.head x.e.cur).op ≠ .st) : x.retire P2 = true := by
  have hw : (x.head x.e.cur).op = .ord ∨ (x.head x.e.cur).op = .loopRe ∨
      (x.head x.e.cur).op = .st := (h x.e.cur (x.e.sel x.e.cur)).1
  unfold Engine2.retire Engine2.hold
  rcases hw with h1 | h1 | h1
  · rw [h1]
    rfl
  · rw [h1]
    rfl
  · exact absurd h1 hne

/-- A self-timed word that retires does so on its last bit, not on a stuff slot. -/
theorem st_ret_last (P2 : Program2) (x : Engine2) (hc : (x.head x.e.cur).op = .st)
    (hr : x.retire P2 = true) :
    P2.stl x.e.now x.e.cur = true ∧ P2.stuff x.e.now x.e.cur = false := by
  unfold Engine2.retire Engine2.hold at hr
  rw [hc] at hr
  cases h1 : P2.stl x.e.now x.e.cur <;> cases h2 : P2.stuff x.e.now x.e.cur <;> simp_all

/-- The bit counter, one cycle (`ckbitNext` with no clocked action in the fragment). -/
theorem ck_step (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word) (w : Option Lane)
    (x : Engine2) (h : StFrag dly x) (u : Lane) :
    (step2 P2 fw w x).ckbit u =
      if x.e.st = .wb ∧ u = x.e.cur ∧ (x.head x.e.cur).op = .st then
        (if x.retire P2 = true then 0
         else if P2.stuff x.e.now x.e.cur = true then x.ckbit u else x.ckbit u + 1)
      else x.ckbit u := by
  show x.ckbitNext P2 u = _
  unfold Engine2.ckbitNext
  have hk : ¬(x.e.st = .wb ∧ u = x.e.cur ∧ x.isClk = true) := fun h' => by
    rw [Engine2.isClk_frag dly x h] at h'
    exact Bool.noConfusion h'.2.2
  rw [if_neg hk]

/-- The timestamp, one cycle: a writeback adds the head word's delay. -/
theorem ts_step2 (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word) (w : Option Lane)
    (x : Engine2) (h : StFrag dly x) (u : Lane) :
    (step2 P2 fw w x).e.ts u =
      if x.e.st = .wb ∧ u = x.e.cur then x.e.ts u + (x.head x.e.cur).dly else x.e.ts u := by
  show x.tsNext P2 u = _
  unfold Engine2.tsNext
  rw [Engine2.wbDly_frag P2 dly x h]

theorem ts_mono2 (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word) (w : Option Lane)
    (x : Engine2) (h : StFrag dly x) (u : Lane) :
    x.e.ts u ≤ (step2 P2 fw w x).e.ts u := by
  rw [ts_step2 P2 dly fw w x h u]
  split <;> omega

/-- A valid head that does not retire keeps its word and stays valid: only a retirement
invalidates or moves it, and a capture only fills an empty slot (`InFlightEmpty`). -/
theorem head_keep2 (P2 : Program2) (fw : Engine2 → Word) (w : Option Lane) (x : Engine2)
    (u : Lane) (hS : Struct x.e) (hv : x.e.headValid u = true)
    (hn : ¬(x.e.st = .wb ∧ x.e.cur = u ∧ x.retire P2 = true)) :
    (step2 P2 fw w x).head u = x.head u ∧ (step2 P2 fw w x).e.headValid u = true := by
  obtain ⟨hI, _⟩ := hS
  have hs1 : ¬(x.e.st = .wb ∧ x.retire P2 = true ∧ u = x.e.cur) :=
    fun h' => hn ⟨h'.1, h'.2.2.symm, h'.2.1⟩
  have hsel : x.selNext P2 u = x.e.sel u := by
    unfold Engine2.selNext
    rw [if_neg hs1]
  have hcap : ¬(x.e.pst = .cap ∧ u = x.e.pl ∧ x.e.sel u = x.e.pslot) := by
    rintro ⟨hc, hl, hs⟩
    have h0 : x.e.actv x.e.pl x.e.pslot = false := hI (by rw [hc]; decide)
    rw [← hl, ← hs] at h0
    unfold Engine.headValid at hv
    rw [hv] at h0
    cases h0
  constructor
  · show x.wordNext fw u (x.selNext P2 u) = x.word u (x.e.sel u)
    rw [hsel]
    unfold Engine2.wordNext
    rw [if_neg hcap]
  · show x.actvNext P2 u (x.selNext P2 u) = true
    rw [hsel]
    have ha1 : ¬(x.e.st = .wb ∧ x.retire P2 = true ∧ u = x.e.cur ∧
        x.e.sel u = x.e.sel x.e.cur) := fun h' => hn ⟨h'.1, h'.2.2.1.symm, h'.2.1⟩
    unfold Engine2.actvNext
    rw [if_neg ha1]
    by_cases hc : x.e.pst = .cap ∧ u = x.e.pl ∧ x.e.sel u = x.e.pslot
    · rw [if_pos hc]
    · rw [if_neg hc]
      exact hv

/-- During a writeback the dispatched lane's head is valid (`DispHeadValid`). -/
theorem wb_head_valid (x : Engine2) (u : Lane) (hS : Struct x.e) (hw : x.e.st = .wb)
    (hc : x.e.cur = u) : x.e.headValid u = true := by
  obtain ⟨_, hD⟩ := hS
  have := hD (by rw [hw]; decide)
  rw [hc] at this
  exact this

/-- The counter invariant, one cycle: the counter is zero, or the head is a valid
self-timed word. -/
theorem ck_inv_step (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word) (w : Option Lane)
    (x : Engine2) (u : Lane) (hf : StFrag dly x) (hS : Struct x.e)
    (ih : x.ckbit u = 0 ∨ ((x.head u).op = .st ∧ x.e.headValid u = true)) :
    (step2 P2 fw w x).ckbit u = 0 ∨
      (((step2 P2 fw w x).head u).op = .st ∧ (step2 P2 fw w x).e.headValid u = true) := by
  rw [ck_step P2 dly fw w x hf u]
  by_cases hc : x.e.st = .wb ∧ u = x.e.cur ∧ (x.head x.e.cur).op = .st
  · rw [if_pos hc]
    by_cases hr : x.retire P2 = true
    · rw [if_pos hr]
      exact Or.inl rfl
    · right
      have hcu : x.e.cur = u := hc.2.1.symm
      obtain ⟨hh, hv'⟩ := head_keep2 P2 fw w x u hS (wb_head_valid x u hS hc.1 hcu)
        (fun h' => hr h'.2.2)
      rw [hh, hv']
      refine ⟨?_, rfl⟩
      have := hc.2.2
      rw [hcu] at this
      exact this
  · rw [if_neg hc]
    rcases ih with h0 | ⟨hst, hv⟩
    · exact Or.inl h0
    · right
      have hn : ¬(x.e.st = .wb ∧ x.e.cur = u ∧ x.retire P2 = true) := by
        rintro ⟨h1, h2, _⟩
        exact hc ⟨h1, h2.symm, by rw [h2]; exact hst⟩
      obtain ⟨hh, hv'⟩ := head_keep2 P2 fw w x u hS hv hn
      rw [hh, hv']
      exact ⟨hst, rfl⟩

/-- At a retirement that ends a pair, the tie and the pair condition give the spacing. -/
theorem at_ret (P2 : Program2) (u : Lane) (D A H : Nat) (x : Engine2) (hR : Ret2 P2 u x)
    (htie : (x.head u).op = .st → P2.stl x.e.now u = true → P2.stuff x.e.now u = false →
      (x.head u).lx ≤ x.ckbit u)
    (hts : A + H + x.ckbit u * (x.head u).dly ≤ x.e.ts u)
    (hp : D ≤ H + lxOf (x.head u) * (x.head u).dly) : A + D ≤ x.e.ts u := by
  obtain ⟨_, hcu, hr⟩ := hR
  by_cases hop : (x.head u).op = .st
  · have hlx : lxOf (x.head u) = (x.head u).lx := by
      unfold lxOf
      rw [if_pos hop]
    have hop' : (x.head x.e.cur).op = .st := by
      rw [hcu]
      exact hop
    obtain ⟨hl, hs⟩ := st_ret_last P2 x hop' hr
    rw [hcu] at hl hs
    have hle := htie hop hl hs
    have hm := Nat.mul_le_mul_right ((x.head u).dly) hle
    rw [hlx] at hp
    omega
  · have hlx : lxOf (x.head u) = 0 := by
      unfold lxOf
      rw [if_neg hop]
    rw [hlx, Nat.zero_mul] at hp
    omega

/-- One cycle inside a pair: while lane `u` does not retire, the timestamp keeps pace with
the counter at the head word's delay. -/
theorem pair_step (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word) (u : Lane)
    (A H : Nat) (w : Option Lane) (x : Engine2) (hf : StFrag dly x)
    (hS : Struct x.e) (hz : x.ckbit u = 0 ∨ ((x.head u).op = .st ∧ x.e.headValid u = true))
    (hnR : ¬Ret2 P2 u x) (hts : A + H + x.ckbit u * (x.head u).dly ≤ x.e.ts u) :
    A + H + (step2 P2 fw w x).ckbit u * ((step2 P2 fw w x).head u).dly ≤
      (step2 P2 fw w x).e.ts u := by
  rw [ck_step P2 dly fw w x hf u, ts_step2 P2 dly fw w x hf u]
  by_cases hwb : x.e.st = .wb ∧ x.e.cur = u
  · have hop : (x.head x.e.cur).op = .st := by
      by_cases h' : (x.head x.e.cur).op = .st
      · exact h'
      · exact absurd ⟨hwb.1, hwb.2, retire_frag P2 dly x hf h'⟩ hnR
    have hr : ¬(x.retire P2 = true) := fun h' => hnR ⟨hwb.1, hwb.2, h'⟩
    have hc1 : x.e.st = .wb ∧ u = x.e.cur ∧ (x.head x.e.cur).op = .st :=
      ⟨hwb.1, hwb.2.symm, hop⟩
    have hc2 : x.e.st = .wb ∧ u = x.e.cur := ⟨hwb.1, hwb.2.symm⟩
    rw [if_pos hc1, if_pos hc2, if_neg hr]
    obtain ⟨hh, -⟩ := head_keep2 P2 fw w x u hS (wb_head_valid x u hS hwb.1 hwb.2) hnR
    rw [hh]
    have hd : (x.head x.e.cur).dly = (x.head u).dly := by rw [hwb.2]
    rw [hd]
    have hck : (if P2.stuff x.e.now x.e.cur = true then x.ckbit u else x.ckbit u + 1) ≤
        x.ckbit u + 1 := by
      split <;> omega
    have hm := Nat.mul_le_mul_right ((x.head u).dly) hck
    rw [Nat.add_mul, Nat.one_mul] at hm
    omega
  · have hc1 : ¬(x.e.st = .wb ∧ u = x.e.cur ∧ (x.head x.e.cur).op = .st) :=
      fun h' => hwb ⟨h'.1, h'.2.1.symm⟩
    have hc2 : ¬(x.e.st = .wb ∧ u = x.e.cur) := fun h' => hwb ⟨h'.1, h'.2.symm⟩
    rw [if_neg hc1, if_neg hc2]
    rcases hz with h0 | ⟨_, hv⟩
    · rw [h0, Nat.zero_mul]
      rw [h0, Nat.zero_mul] at hts
      exact hts
    · obtain ⟨hh, -⟩ := head_keep2 P2 fw w x u hS hv
        (fun h' => hwb ⟨h'.1, h'.2.1⟩)
      rw [hh]
      exact hts

/-! ### Along the run -/

/-- **The counter invariant.** From a zero counter, lane `u`'s bit counter is zero whenever
its head is not a valid self-timed word: in particular, right after every retirement. -/
theorem ck_inv (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) (u : Lane)
    (hfr : ∀ n, StFrag dly (run2 P2 fw sched n x0))
    (hst : ∀ n, Struct (run2 P2 fw sched n x0).e) (hck0 : x0.ckbit u = 0) :
    ∀ n, (run2 P2 fw sched n x0).ckbit u = 0 ∨
      (((run2 P2 fw sched n x0).head u).op = .st ∧
        (run2 P2 fw sched n x0).e.headValid u = true) := by
  intro n
  induction n with
  | zero => exact Or.inl hck0
  | succ n ih =>
    rw [run2_succ']
    exact ck_inv_step P2 dly fw _ _ u (hfr n) (hst n) ih

/-- **Retirement spacing from the pair condition, on the v2 run.** -/
theorem retSpaced2 (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) (u : Lane) (D : Nat)
    (hfr : ∀ n, StFrag dly (run2 P2 fw sched n x0))
    (hst : ∀ n, Struct (run2 P2 fw sched n x0).e) (hck0 : x0.ckbit u = 0)
    (htie : StlCounter P2 fw sched x0 u) (hpair : PairCond P2 fw sched x0 u D) :
    ∀ a b, a < b → Ret2 P2 u (run2 P2 fw sched a x0) → Ret2 P2 u (run2 P2 fw sched b x0) →
      (run2 P2 fw sched a x0).e.ts u + D ≤ (run2 P2 fw sched b x0).e.ts u := by
  intro a b hab ha hb
  have hz := ck_inv P2 dly fw sched x0 u hfr hst hck0
  have hA : ∀ k, (run2 P2 fw sched a x0).e.ts u + D ≤ (run2 P2 fw sched (a + 1 + k) x0).e.ts u ∨
      ((∀ j, a < j → j < a + 1 + k → ¬Ret2 P2 u (run2 P2 fw sched j x0)) ∧
       (run2 P2 fw sched a x0).e.ts u + ((run2 P2 fw sched a x0).head u).dly +
         (run2 P2 fw sched (a + 1 + k) x0).ckbit u *
           ((run2 P2 fw sched (a + 1 + k) x0).head u).dly
         ≤ (run2 P2 fw sched (a + 1 + k) x0).e.ts u) := by
    intro k
    induction k with
    | zero =>
      right
      refine ⟨fun j h1 h2 => absurd h2 (by omega), ?_⟩
      rw [Nat.add_zero, run2_succ']
      obtain ⟨hw, hcu, hr⟩ := ha
      have hf := hfr a
      -- the counter is zero right after the retirement at a
      have hck : (step2 P2 fw (sched (run2 P2 fw sched a x0)) (run2 P2 fw sched a x0)).ckbit u
          = 0 := by
        rw [ck_step P2 dly fw _ _ hf u]
        by_cases hop : ((run2 P2 fw sched a x0).head (run2 P2 fw sched a x0).e.cur).op = .st
        · rw [if_pos ⟨hw, hcu.symm, hop⟩, if_pos hr]
        · have hc : ¬((run2 P2 fw sched a x0).e.st = .wb ∧ u = (run2 P2 fw sched a x0).e.cur ∧
              ((run2 P2 fw sched a x0).head (run2 P2 fw sched a x0).e.cur).op = .st) :=
            fun h' => hop h'.2.2
          rw [if_neg hc]
          rcases hz a with h0 | ⟨hst', _⟩
          · exact h0
          · rw [hcu] at hop
            exact absurd hst' hop
      rw [hck, Nat.zero_mul, ts_step2 P2 dly fw _ _ hf u, if_pos ⟨hw, hcu.symm⟩, hcu]
      omega
    | succ k ih =>
      have hk : a + 1 + (k + 1) = (a + 1 + k) + 1 := by omega
      rw [hk, run2_succ']
      have hf := hfr (a + 1 + k)
      have hs := hst (a + 1 + k)
      rcases ih with h1 | ⟨hno, hts⟩
      · left
        exact Nat.le_trans h1 (ts_mono2 P2 dly fw _ _ hf u)
      · by_cases hR : Ret2 P2 u (run2 P2 fw sched (a + 1 + k) x0)
        · left
          have hp := hpair a (a + 1 + k) (by omega) ha hR hno
          have h2 := at_ret P2 u D _ _ _ hR
            (fun hop hl hs' => htie (a + 1 + k) hR.1 hR.2.1 hop hl hs') hts hp
          exact Nat.le_trans h2 (ts_mono2 P2 dly fw _ _ hf u)
        · right
          refine ⟨fun j h1 h2 => ?_, pair_step P2 dly fw u _ _ _ _ hf hs (hz _) hR hts⟩
          rcases Nat.lt_or_ge j (a + 1 + k) with hj | hj
          · exact hno j h1 hj
          · have hj' : j = a + 1 + k := by omega
            rw [hj']
            exact hR
  have hm : a + 1 + (b - a - 1) = b := by omega
  rcases hA (b - a - 1) with h1 | ⟨hno, hts⟩
  · rw [hm] at h1
    exact h1
  · rw [hm] at hno hts
    exact at_ret P2 u D _ _ _ hb (fun hop hl hs => htie b hb.1 hb.2.1 hop hl hs) hts
      (hpair a b hab ha hb hno)

/-- **`RetSpaced` from the pair condition**, for the V4b program of a v2 run (`stP`, as
`dstar_usb_st` uses it). -/
theorem retSpaced_of_pairs (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) (u : Lane) (D : Nat)
    (hx0 : StFrag dly x0) (hf : ∀ y, StFragW dly y.e.pl (fw y)) (hW : Wf x0.e)
    (hsw : ∀ x w, sched x = some w → P2.live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (P2.toP dly) y x.e → sched x ≠ none)
    (hck0 : x0.ckbit u = 0) (htie : StlCounter P2 fw sched x0 u)
    (hpair : PairCond P2 fw sched x0 u D) :
    RetSpaced (stP P2 dly fw sched x0) (win1 (stP P2 dly fw sched x0) P2 fw sched x0)
      x0.e u D := by
  have hsw' : ∀ x w, sched x = some w →
      (stP P2 dly fw sched x0).live w = true ∧ x.e.ts w ≤ x.e.now := hsw
  have hss' : ∀ y x, Ready (stP P2 dly fw sched x0) y x.e → sched x ≠ none :=
    fun y x h => hss y x h
  have hr := run2_proj_st P2 dly fw sched x0 hx0 hf hsw' hss'
  have hS0 : Struct x0.e := by
    have hw := hW
    unfold Wf at hw
    exact hw.1
  have hst : ∀ n, Struct (run2 P2 fw sched n x0).e := fun n => by
    rw [hr n]
    exact struct_run _ _ n _ hS0
  have hfr : ∀ n, StFrag dly (run2 P2 fw sched n x0) :=
    fun n => frag_run2 P2 dly fw sched hf n x0 hx0
  have toR : ∀ n, IsRet (stP P2 dly fw sched x0) u
      (run (stP P2 dly fw sched x0) (win1 (stP P2 dly fw sched x0) P2 fw sched x0) n x0.e) →
      Ret2 P2 u (run2 P2 fw sched n x0) := by
    intro n h
    rw [← hr n] at h
    obtain ⟨h1, h2, h3⟩ := h
    refine ⟨h1, h2, ?_⟩
    have h3' : (run2 P2 fw sched ((run2 P2 fw sched n x0).e.now - x0.e.now) x0).retire P2
        = true := h3
    rw [now_run2, Nat.add_sub_cancel_left] at h3'
    exact h3'
  intro a b hab ha hb
  have core := retSpaced2 P2 dly fw sched x0 u D hfr hst hck0 htie hpair a b hab
    (toR a ha) (toR b hb)
  rw [← hr a, ← hr b]
  exact core

/-- **D\* for the v2 engine with self-timed bytes and a re-anchoring USB lane, per pair
(Wilson 11-13).** `dstar_usb_st` with the USB lane's retirement spacing no longer assumed:
it follows from the bit-counter tie (`StlCounter`) and the pair condition at
`DSTAR_RETIRE_USB = R_USB + 25 = 42` (`PairCond`, checked on the image by
`proof_constants.retire_pairs`). -/
theorem dstar_usb_pairs (P2 : Program2) (dly : Lane → Nat) (fw : Engine2 → Word)
    (sched : Engine2 → Option Lane) (x0 : Engine2) (u : Lane) (dbit : Nat)
    (hx0 : StFrag dly x0) (hf : ∀ y, StFragW dly y.e.pl (fw y))
    (hW : Wf x0.e) (hfull : ∀ l s, P2.live l = true → x0.e.actv l s = true)
    (h0 : x0.e.st = .idle) (h0ts : ∀ l, x0.e.now ≤ x0.e.ts l)
    (hsw : ∀ x w, sched x = some w → P2.live w = true ∧ x.e.ts w ≤ x.e.now)
    (hss : ∀ y x, Ready (P2.toP dly) y x.e → sched x ≠ none)
    (hfl : reanFloor dbit ≤ dly u) (hrow1 : NOWB_MIN ≤ reanFloor dbit)
    (hck0 : x0.ckbit u = 0) (htie : StlCounter P2 fw sched x0 u)
    (hpair : PairCond P2 fw sched x0 u DSTAR_RETIRE_USB)
    (hd : ∀ l, P2.live l = true → l ≠ u → DSTAR_RETIRE_USB ≤ dly l) :
    ∀ T, ((run2 P2 fw sched T x0).e.st = .idle →
            ∀ w, sched (run2 P2 fw sched T x0) = some w →
              (run2 P2 fw sched T x0).e.headValid w = true) ∧
         NoBr1 (stP P2 dly fw sched x0) (run2 P2 fw sched T x0).e :=
  dstar_usb_st P2 dly fw sched x0 u dbit hx0 hf hW hfull h0 h0ts hsw hss hfl hrow1
    (retSpaced_of_pairs P2 dly fw sched x0 u DSTAR_RETIRE_USB hx0 hf hW hsw hss hck0 htie hpair)
    hd

#print axioms retSpaced2
#print axioms retSpaced_of_pairs
#print axioms dstar_usb_pairs

end JLane

import JLane.GapRunT
import JLane.RespWinB
/-!
# Brick C3f — the buffered engine with flushes, between a lane's flushes, is a trajectory
(`slot_on_composition`, step 3c)

`FlushKill.runBK` (the slot, the buffer, the FALLTHROUGH keep-flush K1–K4 and the kill K5), read
through `EngBK.base` -- the engine each cycle runs on -- agrees with `stepB` for lane `y` on every
cycle where `y` is not flushed and no killed capture lands on `y` (`agree_stepBKK`): the flush
rewrites only flushed lanes' slots, select, timestamp and buffer, and the kill only the lane the
killed capture was for. So a stretch of `runBK` between `y`'s flushes is a `TrajY` trajectory
(`trajY_runBK`), well formed by `FlushKill.wfBK_run`, and `GapRunT`'s certificate holds along it.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **One cycle of `runBK`, as lane `y` sees it, is `stepB`'s**, when `y` is not flushed and the
cycle is not a killed capture for `y`. -/
theorem agree_stepBKK (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) (y : Lane)
    (hf : fl y = false) (hk : ¬(X.kc = true ∧ X.x.e.pl = y)) :
    AgreeY y (stepBKK P win usb sreq fl k X).base (stepB P win usb sreq X.base) := by
  have hpl : X.base.e.pl = X.x.e.pl := by rw [base_e]
  have hnk : (X.kc && decide (y = X.base.e.pl)) = false := by
    cases hkc : X.kc
    · rfl
    · have hne : ¬y = X.base.e.pl := fun h => hk ⟨hkc, by rw [h, hpl]⟩
      simp [hne]
  unfold AgreeY
  rw [base_e (stepBKK P win usb sreq fl k X), base_buf (stepBKK P win usb sreq fl k X)]
  refine ⟨rfl, rfl, rfl, rfl, ?_, ?_, ?_, fun _ => rfl, ?_⟩
  · show (if fl y = true then X.base.e.now else (stepB P win usb sreq X.base).e.ts y) = _
    rw [if_neg (by simp [hf])]
  · rw [selK]; simp [hf]
  · intro s
    rw [actvK]
    have : (X.kc && decide (y = X.base.e.pl) && capTo X.base y s) = false := by
      rw [hnk]; rfl
    simp [hf, this]
  · rw [bufK]; simp [hf, hnk]

/-- **A stretch of `runBK` is a trajectory.** From cycle `s`, over `T` cycles in which `y` is
never flushed and no killed capture lands on `y`, `runBK` read through `base` steps as `stepB`
for `y`. -/
theorem trajY_runBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane)
    (s T : Nat)
    (hseg : ∀ n, n < T →
      fl (runBK P win usb sreq fl k (s + n) X0).x.e.now y = false ∧
      ¬((runBK P win usb sreq fl k (s + n) X0).kc = true ∧
        (runBK P win usb sreq fl k (s + n) X0).x.e.pl = y)) :
    TrajY P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) T := by
  intro n hn
  obtain ⟨hf, hk⟩ := hseg n hn
  show AgreeY y (runBK P win usb sreq fl k (s + (n + 1)) X0).base
    (stepB P win usb sreq (runBK P win usb sreq fl k (s + n) X0).base)
  rw [show s + (n + 1) = (s + n) + 1 by omega, runBK_succ']
  exact agree_stepBKK P win usb sreq _ _ _ y hf hk

/-- **Well formed along the stretch**: BufEng's invariant on every cycle's engine, given the
flush conditions (`FlushKill.wfBK_run`). -/
theorem wfB_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (s T : Nat)
    (hF : ∀ j, j < s + T → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0)) :
    ∀ n, n ≤ T → WfB ((fun n => (runBK P win usb sreq fl k (s + n) X0).base) n) := fun n hn =>
  (wfBK_run P win usb sreq hok fl k (s + n) X0 hI (fun j hj => hF j (by omega))).wf

/-! ### The restart (3c part 2): at `f + 3` the lane holds exactly its edge word

A flush of `y` at cycle `f` with its edge word present (K1–K4, `hasEdge`) leaves `y` holding that
one word in its head, buffer empty, released at `f + 1` (`edge_survives_flushK`). The next two
cycles change nothing of `y`'s:
* **no retirement** -- the flush condition keeps `y` out of the dispatcher at `f + 1`
  (`FlushOk`), and the dispatcher needs DRIVE before WB, so `y`'s first writeback is at `f + 3`;
* **no capture files a word** -- the port enters CAP only from WAIT and WAIT only from REQ, so a
  capture for `y` at `f + 1` or `f + 2` is the fetch in flight at the flush, which the flush
  killed (K5: `stepBKK`'s `pkill`), and a killed capture files nothing (`kill_files_nothing`);
* **no load** -- the buffer is empty and only a capture writes it.
So the trajectory restarts at `f + 3` with one word held and the release at `f + 1`: its start's
virtual retirement (`now₀ - 3`) is the flush cycle, and `hZS0` / `hHS0` read as the refill timed
from the flush. -/

theorem base_held (X : EngBK) (l : Lane) : X.base.held l = X.x.held l := by
  unfold EngB.held nslots
  rw [base_e, base_buf]

theorem base_sq (X : EngBK) : X.base.sq = X.x.sq := by
  unfold EngBK.base; split <;> rfl

/-- The port enters CAP only from WAIT, keeping the lane. -/
theorem portNextB_cap_from (x : EngB) (h : (portNextB P usb sreq x).pst = .cap) :
    x.e.pst = .wait ∧ (portNextB P usb sreq x).pl = x.e.pl := by
  by_cases hs : x.e.pst = .scan
  · have := scan_next_req P usb sreq x hs (by rw [h]; decide)
    rw [h] at this
    cases this
  · rw [(portNextB_of_ne P usb sreq x hs).1] at h ⊢
    cases hp : x.e.pst with
    | scan => exact absurd hp hs
    | req => simp [portNext, hp] at h
    | wait => simp [portNext, hp]
    | cap => simp [portNext, hp] at h

/-- The port enters WAIT only from REQ, keeping the lane. -/
theorem portNextB_wait_from (x : EngB) (h : (portNextB P usb sreq x).pst = .wait) :
    x.e.pst = .req ∧ (portNextB P usb sreq x).pl = x.e.pl := by
  by_cases hs : x.e.pst = .scan
  · have := scan_next_req P usb sreq x hs (by rw [h]; decide)
    rw [h] at this
    cases this
  · rw [(portNextB_of_ne P usb sreq x hs).1] at h ⊢
    cases hp : x.e.pst with
    | scan => exact absurd hp hs
    | req => simp [portNext, hp]
    | wait => simp [portNext, hp] at h
    | cap => simp [portNext, hp] at h

/-- The flush cycle: the flushed lane holds exactly one word. -/
theorem held_flushK (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) (y : Lane)
    (hf : fl y = true) (hk : X.base.hasEdge y (k y) = true) :
    (stepBKK P win usb sreq fl k X).x.held y = 1 := by
  unfold EngB.held nslots
  rw [flushK_buf_empty P win usb sreq fl k X y hf, actvK, actvK]
  simp only [hf, ↓reduceIte, hk, Bool.true_and]
  generalize keepSlot X.base y (k y) = s
  cases s <;> rfl

/-- **A frozen cycle for `y`.** Not flushed, not retiring, buffer empty, and any capture for it
killed: `y`'s slots, buffer, select and timestamp are unchanged, and so is the word in its head. -/
theorem frozen_stepBKK (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) (y : Lane)
    (hW : WfB X.base) (hf : fl y = false)
    (hnw : ¬(X.x.e.st = .wb ∧ X.x.e.cur = y)) (hb : X.x.buf y = false)
    (hcap : X.x.e.pst = .cap → X.x.e.pl = y → X.pkill = true) :
    (∀ s, (stepBKK P win usb sreq fl k X).x.e.actv y s = X.x.e.actv y s) ∧
    (stepBKK P win usb sreq fl k X).x.buf y = false ∧
    (stepBKK P win usb sreq fl k X).x.e.sel y = X.x.e.sel y ∧
    (stepBKK P win usb sreq fl k X).x.e.ts y = X.x.e.ts y ∧
    (X.x.e.headValid y = true →
      (stepBKK P win usb sreq fl k X).x.sq y (X.x.e.sel y) = X.x.sq y (X.x.e.sel y)) := by
  have hbe := base_e X
  have hbb := base_buf X
  have hkill : X.x.e.pst = .cap → y = X.x.e.pl → (X.kc && decide (y = X.base.e.pl)) = true := by
    intro hpc hpl
    have hk := hcap hpc hpl.symm
    unfold EngBK.kc
    rw [hbe]
    simp [hpc, hk, hpl]
  have hcapK : ∀ s, capTo X.base y s = true → (X.kc && decide (y = X.base.e.pl)) = true := by
    intro s hc
    obtain ⟨hpc, hpl⟩ := capTo_cap X.base y s hc
    rw [hbe] at hpc hpl
    exact hkill hpc hpl
  have hnr : ¬(X.base.e.st = .wb ∧ y = X.base.e.cur ∧ P.ret X.base.e.now X.base.e.cur = true) := by
    rw [hbe]
    exact fun h => hnw ⟨h.1, h.2.1.symm⟩
  have hld : ∀ s, loadTo X.base y s = false := fun s =>
    loadTo_off X.base y s (by rw [hbb]; exact hb)
  refine ⟨fun s => ?_, ?_, ?_, ?_, fun hv => ?_⟩
  · rw [actvK, hf]
    simp only [Bool.false_eq_true, ↓reduceIte]
    by_cases hK : (X.kc && decide (y = X.base.e.pl) && capTo X.base y s) = true
    · rw [if_pos hK]
      have hc : capTo X.base y s = true := by
        simp only [Bool.and_eq_true] at hK
        exact hK.2
      have := fill_empty X.base hW y s (by rw [hc]; rfl)
      rw [hbe] at this
      exact this.symm
    · rw [if_neg hK, stepB_e_actv, actvB_noret P X.base y s hnr]
      have hc : capTo X.base y s = false := by
        cases hc : capTo X.base y s
        · rfl
        · exfalso
          apply hK
          rw [hcapK s hc, hc]
          rfl
      rw [hc, hld s, hbe]
      simp
  · rw [bufK, hf]
    simp only [Bool.false_eq_true, ↓reduceIte]
    split
    · rfl
    · rename_i hK
      rw [stepB_buf]
      unfold bufB
      have hcb : capBuf X.base y = false := by
        cases hc : capBuf X.base y
        · rfl
        · exfalso
          apply hK
          obtain ⟨hpc, hpl, -, -⟩ := capBuf_spec X.base y hc
          rw [hbe] at hpc hpl
          exact hkill hpc hpl
      rw [hcb, hbb, hb]
      simp
  · rw [selK, hf]
    simp only [Bool.false_eq_true, ↓reduceIte]
    rw [stepB_e_sel]
    unfold selNext
    rw [if_neg (fun h => hnr ⟨h.1, h.2.1, h.2.2⟩), hbe]
  · rw [stepBKK_ts_y P win usb sreq fl k X y hf]
    unfold tsNext
    rw [if_neg (fun h => hnw ⟨h.1, h.2.symm⟩)]
  · show (if fl y = true ∧ X.x.e.sel y = keepSlot X.base y (k y) then nrB P X.base y
      else sqB X.base y (X.x.e.sel y)) = _
    rw [if_neg (fun h => by rw [hf] at h; cases h.1)]
    unfold sqB
    have hc : capTo X.base y (X.x.e.sel y) = false := by
      cases hc : capTo X.base y (X.x.e.sel y)
      · rfl
      · exfalso
        have := fill_empty X.base hW y _ (by rw [hc]; rfl)
        rw [hbe] at this
        unfold Engine.headValid at hv
        rw [this] at hv
        cases hv
    rw [hc, hld]
    simp only [Bool.false_eq_true, ↓reduceIte]
    rw [base_sq]

/-- After the flush cycle, `y` is not the lane writing back. -/
theorem no_wb_after_flush (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) (y : Lane)
    (hF : FlushOk P win usb sreq fl X) (hf : fl y = true) :
    ¬((stepBKK P win usb sreq fl k X).x.e.st = .wb ∧ (stepBKK P win usb sreq fl k X).x.e.cur = y)
    := by
  rintro ⟨hw, hc⟩
  rw [stK] at hw
  rw [curK] at hc
  exact hF.1 y hf (by rw [hw]; decide) hc

/-- Two cycles after the flush, `y` is not the lane writing back: it was not in the dispatcher
the cycle after the flush, and WB follows DRIVE. -/
theorem no_wb_after_flush2 (fl fl1 : Lane → Bool) (k k1 : Lane → Nat) (X : EngBK) (y : Lane)
    (hF : FlushOk P win usb sreq fl X) (hf : fl y = true) :
    ¬((stepBKK P win usb sreq fl1 k1 (stepBKK P win usb sreq fl k X)).x.e.st = .wb ∧
      (stepBKK P win usb sreq fl1 k1 (stepBKK P win usb sreq fl k X)).x.e.cur = y) := by
  rintro ⟨hw, hc⟩
  rw [stepBKK_st] at hw
  rw [stepBKK_cur] at hc
  change (dispNext win (stepBKK P win usb sreq fl k X).x.e).st = .wb at hw
  change (dispNext win (stepBKK P win usb sreq fl k X).x.e).cur = y at hc
  have hd : (stepBKK P win usb sreq fl k X).x.e.st = .drive := by
    revert hw
    unfold dispNext
    cases (stepBKK P win usb sreq fl k X).x.e.st with
    | idle =>
      dsimp only
      cases win (stepBKK P win usb sreq fl k X).x.e with
      | none => intro h; cases h
      | some w =>
        dsimp only
        split <;> intro h <;> cases h
    | drive => intro _; rfl
    | wb => intro h; cases h
  have hc' : (stepBKK P win usb sreq fl k X).x.e.cur = y := by
    revert hc
    unfold dispNext
    rw [hd]
    exact id
  rw [stK] at hd
  rw [curK] at hc'
  exact hF.1 y hf (by rw [hd]; decide) hc'

/-- **The restart, three cycles.** `y` flushed at `X` with its edge word present (K1–K4), the
flush conditions at the flush and the cycle after, `y` not flushed again in the next two cycles.
Then three cycles on, `y` holds exactly one word -- its edge word, in its head -- with the buffer
empty, released at the cycle after the flush. The in-flight fetch's kill (K5) is `stepBKK`'s
`pkill`: a capture for `y` in the two cycles is that fetch and files nothing. -/
theorem restart_three (hok : SReqB P sreq) (fl0 fl1 fl2 : Lane → Bool) (k0 k1 k2 : Lane → Nat)
    (X X1 X2 X3 : EngBK) (y : Lane)
    (hX1 : X1 = stepBKK P win usb sreq fl0 k0 X) (hX2 : X2 = stepBKK P win usb sreq fl1 k1 X1)
    (hX3 : X3 = stepBKK P win usb sreq fl2 k2 X2)
    (hI : WfBK X) (hF0 : FlushOk P win usb sreq fl0 X) (hF1 : FlushOk P win usb sreq fl1 X1)
    (hf0 : fl0 y = true) (hk : X.base.hasEdge y (k0 y) = true)
    (hf1 : fl1 y = false) (hf2 : fl2 y = false) :
    X3.base.held y = 1 ∧ X3.base.e.headValid y = true ∧ X3.x.sq y (X3.x.e.sel y) = X1.x.nr y ∧
      X3.base.e.ts y = X.x.e.now ∧ X3.base.e.now = X.x.e.now + 3 := by
  have hI1 : WfBK X1 := hX1 ▸ wfBK_step P win usb sreq fl0 k0 hok X hI hF0
  have hI2 : WfBK X2 := hX2 ▸ wfBK_step P win usb sreq fl1 k1 hok X1 hI1 hF1
  -- the flush cycle
  have hn1 : X1.x.e.now = X.x.e.now + 1 := by rw [hX1]; exact stepBKK_now P win usb sreq fl0 k0 X
  obtain ⟨hv1, hsq1, hts1⟩ := edge_survives_flushK P win usb sreq fl0 k0 X y hf0 hk
  rw [← hX1] at hv1 hsq1 hts1
  have hb1 : X1.x.buf y = false := by rw [hX1]; exact flushK_buf_empty P win usb sreq fl0 k0 X y hf0
  have hh1 : X1.x.held y = 1 := by rw [hX1]; exact held_flushK P win usb sreq fl0 k0 X y hf0 hk
  -- no retirement of y at f+1, f+2
  have hnw1 : ¬(X1.x.e.st = .wb ∧ X1.x.e.cur = y) := by
    rw [hX1]; exact no_wb_after_flush P win usb sreq fl0 k0 X y hF0 hf0
  have hnw2 : ¬(X2.x.e.st = .wb ∧ X2.x.e.cur = y) := by
    rw [hX2, hX1]; exact no_wb_after_flush2 P win usb sreq fl0 fl1 k0 k1 X y hF0 hf0
  -- a capture for y at f+1 or f+2 is the killed in-flight fetch
  have hcap1 : X1.x.e.pst = .cap → X1.x.e.pl = y → X1.pkill = true := by
    intro hc hp
    rw [hX1, pstK, stepB_pst] at hc
    rw [hX1, plK, stepB_pl] at hp
    obtain ⟨hwt, hpl⟩ := portNextB_cap_from P usb sreq X.base hc
    rw [base_e] at hwt hpl
    rw [hpl] at hp
    rw [hX1, pkillK, if_neg (by rw [hwt]; decide)]
    simp [hwt, hp, hf0]
  have hcap2 : X2.x.e.pst = .cap → X2.x.e.pl = y → X2.pkill = true := by
    intro hc hp
    rw [hX2, pstK, stepB_pst] at hc
    rw [hX2, plK, stepB_pl] at hp
    obtain ⟨hwt, hpl⟩ := portNextB_cap_from P usb sreq X1.base hc
    rw [base_e] at hwt hpl
    rw [hpl] at hp
    -- X1 is in WAIT for y: X was in REQ for y
    have hwt' := hwt
    rw [hX1, pstK, stepB_pst] at hwt'
    have hp' := hp
    rw [hX1, plK, stepB_pl] at hp'
    obtain ⟨hrq, hpl0⟩ := portNextB_wait_from P usb sreq X.base hwt'
    rw [base_e] at hrq hpl0
    rw [hpl0] at hp'
    have hk1 : X1.pkill = true := by
      rw [hX1, pkillK, if_neg (by rw [hrq]; decide)]
      simp [hrq, hp', hf0]
    rw [hX2, pkillK, if_neg (by rw [hwt]; decide), hk1]
    rfl
  -- the two frozen cycles
  obtain ⟨ha2, hb2, hs2, ht2, hq2⟩ :=
    frozen_stepBKK P win usb sreq fl1 k1 X1 y hI1.wf hf1 hnw1 hb1 hcap1
  rw [← hX2] at ha2 hb2 hs2 ht2 hq2
  obtain ⟨ha3, hb3, hs3, ht3, hq3⟩ :=
    frozen_stepBKK P win usb sreq fl2 k2 X2 y hI2.wf hf2 hnw2 hb2 hcap2
  rw [← hX3] at ha3 hb3 hs3 ht3 hq3
  have hv2 : X2.x.e.headValid y = true := by
    unfold Engine.headValid at hv1 ⊢
    rw [hs2, ha2]
    exact hv1
  refine ⟨?_, ?_, ?_, ?_, ?_⟩
  · rw [base_held]
    unfold EngB.held nslots at hh1 ⊢
    rw [ha3, ha3, hb3, ha2, ha2]
    rw [hb1] at hh1
    exact hh1
  · rw [base_e]
    unfold Engine.headValid at hv2 ⊢
    rw [hs3, ha3]
    exact hv2
  · rw [hs3, hq3 hv2, hs2, hq2 hv1]
    exact hsq1
  · rw [base_e, ht3, ht2]; omega
  · rw [base_e, hX3, stepBKK_now, hX2, stepBKK_now, hn1]

/-- **The restart on a run.** `y` flushed at cycle `f` of `runBK` with its edge word present
(K1–K4), the flush conditions on the cycles before `f + 2`, and `y` not flushed at `f + 1` or
`f + 2`: at `f + 3`, `y` holds exactly its edge word in its head with the buffer empty, released
at `f + 1`. -/
theorem restart_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (f : Nat) (y : Lane)
    (hF : ∀ j, j < f + 2 → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hedge : (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true)
    (h1 : fl (runBK P win usb sreq fl k (f + 1) X0).x.e.now y = false)
    (h2 : fl (runBK P win usb sreq fl k (f + 2) X0).x.e.now y = false) :
    (runBK P win usb sreq fl k (f + 3) X0).base.held y = 1 ∧
    (runBK P win usb sreq fl k (f + 3) X0).base.e.headValid y = true ∧
    (runBK P win usb sreq fl k (f + 3) X0).x.sq y ((runBK P win usb sreq fl k (f + 3) X0).x.e.sel y)
      = (runBK P win usb sreq fl k (f + 1) X0).x.nr y ∧
    (runBK P win usb sreq fl k (f + 3) X0).base.e.ts y
      = (runBK P win usb sreq fl k f X0).x.e.now ∧
    (runBK P win usb sreq fl k (f + 3) X0).base.e.now
      = (runBK P win usb sreq fl k f X0).x.e.now + 3 :=
  restart_three P win usb sreq hok _ _ _ _ _ _ (runBK P win usb sreq fl k f X0)
    (runBK P win usb sreq fl k (f + 1) X0) (runBK P win usb sreq fl k (f + 2) X0)
    (runBK P win usb sreq fl k (f + 3) X0) y
    (runBK_succ' P win usb sreq fl k f X0) (runBK_succ' P win usb sreq fl k (f + 1) X0)
    (runBK_succ' P win usb sreq fl k (f + 2) X0)
    (wfBK_run P win usb sreq hok fl k f X0 hI (fun j hj => hF j (by omega)))
    (hF f (by omega)) (hF (f + 1) (by omega)) hfl hedge h1 h2


/-- **The restart's release** (K4): after a flush of `y` at `f`, unflushed at `f + 1`, `f + 2`,
`y`'s release at `f + 3` is `now f + 1` -- `ts` is the edge cycle and `reb` is still set (no
writeback of `y` at `f + 1`, `f + 2`). -/
theorem restart_rel_runBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (f : Nat)
    (y : Lane)
    (hF0 : FlushOk P win usb sreq (fl (runBK P win usb sreq fl k f X0).x.e.now)
      (runBK P win usb sreq fl k f X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (h1 : fl (runBK P win usb sreq fl k (f + 1) X0).x.e.now y = false)
    (h2 : fl (runBK P win usb sreq fl k (f + 2) X0).x.e.now y = false) :
    (runBK P win usb sreq fl k (f + 3) X0).rel y = (runBK P win usb sreq fl k f X0).x.e.now + 1 := by
  have e1 := runBK_succ' P win usb sreq fl k f X0
  have e2 := runBK_succ' P win usb sreq fl k (f + 1) X0
  have e3 := runBK_succ' P win usb sreq fl k (f + 2) X0
  have nw1 := no_wb_after_flush P win usb sreq _ (k (runBK P win usb sreq fl k f X0).x.e.now)
    (runBK P win usb sreq fl k f X0) y hF0 hfl
  rw [← e1] at nw1
  have nw2 := no_wb_after_flush2 P win usb sreq (fl (runBK P win usb sreq fl k f X0).x.e.now)
    (fl (runBK P win usb sreq fl k (f + 1) X0).x.e.now) (k (runBK P win usb sreq fl k f X0).x.e.now)
    (k (runBK P win usb sreq fl k (f + 1) X0).x.e.now) (runBK P win usb sreq fl k f X0) y hF0 hfl
  rw [← e1, ← e2] at nw2
  rw [show f + 3 = f + 2 + 1 from rfl, e3, rel_flat_stepBK P win usb sreq _ _ _ y h2 nw2,
    show f + 2 = f + 1 + 1 from rfl, e2, rel_flat_stepBK P win usb sreq _ _ _ y h1 nw1, e1,
    rel_flush_stepBK P win usb sreq _ _ _ y hfl]

/-! ### Kill provenance: a killed capture for `y` needs a flush of `y` one or two cycles before

A killed capture is in CAP, so the port was in WAIT for the same lane the cycle before and in
REQ the cycle before that. The kill register at the capture was set by a flush of that lane in
WAIT, or was already pending in WAIT -- and then set by a flush in REQ: it cannot have been
pending in REQ, since a pending kill sits only in WAIT or CAP (`WfBK.ki`). So `trajY_runBK`'s
second condition follows from "`y` is not flushed", two cycles back. -/

theorem kill_prov (fl0 fl1 : Lane → Bool) (k0 k1 : Lane → Nat) (X X1 X2 : EngBK) (y : Lane)
    (hX1 : X1 = stepBKK P win usb sreq fl0 k0 X) (hX2 : X2 = stepBKK P win usb sreq fl1 k1 X1)
    (hki : X.pkill = true → X.x.e.pst = .wait ∨ X.x.e.pst = .cap)
    (hkc : X2.kc = true) (hp : X2.x.e.pl = y) : fl1 y = true ∨ fl0 y = true := by
  obtain ⟨hc, hk2⟩ := kc_spec X2 hkc
  rw [hX2, pstK, stepB_pst] at hc
  have hp2 := hp
  rw [hX2, plK, stepB_pl] at hp2
  obtain ⟨hwt, hpl⟩ := portNextB_cap_from P usb sreq X1.base hc
  rw [base_e] at hwt hpl
  rw [hpl] at hp2
  -- X1 in WAIT for y: X in REQ for y
  have hwt' := hwt
  rw [hX1, pstK, stepB_pst] at hwt'
  have hp1 := hp2
  rw [hX1, plK, stepB_pl] at hp1
  obtain ⟨hrq, hpl0⟩ := portNextB_wait_from P usb sreq X.base hwt'
  rw [base_e] at hrq hpl0
  rw [hpl0] at hp1
  rw [hX2, pkillK, if_neg (by rw [hwt]; decide)] at hk2
  cases hf1 : fl1 y
  · right
    have hk1 : X1.pkill = true := by
      rw [hp2, hf1] at hk2
      simpa using hk2
    rw [hX1, pkillK, if_neg (by rw [hrq]; decide)] at hk1
    cases hk0 : X.pkill
    · rw [hk0, hp1] at hk1
      simpa [hrq] using hk1
    · rcases hki hk0 with h | h <;> rw [hrq] at h <;> cases h
  · left; rfl

/-- **Kill provenance on a run**: a killed capture for `y` at cycle `m + 2` needs a flush of `y`
at `m` or `m + 1`. -/
theorem kill_prov_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (m : Nat) (y : Lane)
    (hF : ∀ j, j < m → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hkc : (runBK P win usb sreq fl k (m + 2) X0).kc = true)
    (hp : (runBK P win usb sreq fl k (m + 2) X0).x.e.pl = y) :
    fl (runBK P win usb sreq fl k (m + 1) X0).x.e.now y = true ∨
      fl (runBK P win usb sreq fl k m X0).x.e.now y = true :=
  kill_prov P win usb sreq _ _ _ _ (runBK P win usb sreq fl k m X0)
    (runBK P win usb sreq fl k (m + 1) X0) (runBK P win usb sreq fl k (m + 2) X0) y
    (runBK_succ' P win usb sreq fl k m X0) (runBK_succ' P win usb sreq fl k (m + 1) X0)
    (wfBK_run P win usb sreq hok fl k m X0 hI hF).ki hkc hp

/-- **A stretch of `runBK` with `y` unflushed is a trajectory.** From cycle `s ≥ 2`, if `y` is
not flushed on any cycle from `s - 2` to `s + T - 1`, the stretch is a `TrajY` trajectory: no
killed capture can land on `y` in it (`kill_prov_runBK`). After a flush at `f`, `s = f + 3` is
the restart (`restart_runBK`). -/
theorem trajY_runBK_noflush (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (y : Lane) (s T : Nat) (hs : 2 ≤ s)
    (hF : ∀ j, j < s + T → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hnf : ∀ j, s ≤ j + 2 → j < s + T → fl (runBK P win usb sreq fl k j X0).x.e.now y = false) :
    TrajY P win usb sreq y (fun n => (runBK P win usb sreq fl k (s + n) X0).base) T := by
  apply trajY_runBK P win usb sreq fl k X0 y s T
  intro n hn
  refine ⟨hnf (s + n) (by omega) (by omega), ?_⟩
  rintro ⟨hkc, hp⟩
  obtain ⟨m, hm⟩ : ∃ m, s + n = m + 2 := ⟨s + n - 2, by omega⟩
  rw [hm] at hkc hp
  rcases kill_prov_runBK P win usb sreq hok fl k X0 hI m y
      (fun j hj => hF j (by omega)) hkc hp with h | h
  · rw [hnf (m + 1) (by omega) (by omega)] at h; cases h
  · rw [hnf m (by omega) (by omega)] at h; cases h

end

#print axioms agree_stepBKK
#print axioms trajY_runBK
#print axioms wfB_runBK
#print axioms frozen_stepBKK
#print axioms restart_three
#print axioms restart_runBK
#print axioms kill_prov
#print axioms kill_prov_runBK
#print axioms trajY_runBK_noflush

end JLane

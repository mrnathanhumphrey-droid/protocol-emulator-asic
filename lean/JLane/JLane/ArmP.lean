import JLane.RtlRun
/-!
# Brick R6 — the plain ARM end and HALF on the RTL-side armed run (agent 1's replay, 11-23)

Agent 1's replay at dd04588 (corpus_all5) met ARM ends the armed run did not cover: every
arming ended in a keep-flush. The RTL (pe_engine.v, the `arm_hit` block and `ck_rebase`):
* an ARM latches, at its writeback, FALLTHROUGH (`l_armft`, `mod[1]`), HALF (`l_armhalf`,
  `count[0]`) and no-timeout (`notmo`, `delay = 0`);
* at the edge every armed lane disarms and its `ts` is rebased to `now + off` (`ck_rebase`:
  `off = l_t/2` for HALF, `0` for a plain ARM); only a FALLTHROUGH lane also flushes (PC+2, both
  slots emptied -- the K1–K5 keep-flush, `stepBKKR` with `fl`);
* at a timeout (the pick, ruling 1b) a FALLTHROUGH ARM falls through to PC+1 (`ArmT`); any other
  ARM HALTS the lane (`live_n := 0`, the sticky timeout flag); a no-timeout ARM never times out
  (its release is masked, `~(armed & notmo)`).

`stepBPR` is `RtlRun.stepBTR` with those latches (`ft`, `off`, `nt`, abstract word fields of the
ARM retiring, as `isArm`) and a `halt` set: the flush set is the FALLTHROUGH ends only; a plain
edge rebases without a flush (`EngBK.rebase`, the K4 rebase bit set only when `off = 0`: a
rebase to the edge cycle releases the cycle after, as `rel_q` was decided while the lane was
still armed; a rebase to `now + off`, `off ≥ 1`, releases at `ts`); a plain timeout halts (the
lane leaves `P.live` and the dispatcher's choice from the next cycle).

* `stepBPR_A_eq` -- with every latch FALLTHROUGH, no no-timeout ARM and no halt, the step IS
  `stepBTR`: every earlier replay result stands;
* `stepBPR_pe_ts`, `stepBPR_pe_reb`, `stepBPR_pe_rel` -- **a plain edge releases at
  `now + max 1 off`** (HALF's `edge + l_t/2`, `ArmHalf.arm_release_half`'s release on the
  buffered engine); `pe_not_fl` -- and does not flush;
* `stepBPR_ph_halt`, `stepBPR_halt_mono`, `winA_halt` -- **a plain timeout halts**, for good,
  and a halted lane is never dispatched; `stepBPR_nt_no_tmo` -- a no-timeout ARM never times out.

The clocked park (an arming with no ARM, released at `now + hdly`) is not in this step: its
FALLTHROUGH latch is a question to agent 1 (the park leaves `l_armft` as the lane's last ARM
set it).
-/
namespace JLane

/-- The RTL-side armed run with the ARM's latches: FALLTHROUGH, the release offset, no-timeout,
and the halted lanes. -/
structure EngBP where
  A    : EngBA
  ft   : Lane → Bool
  off  : Lane → Nat
  nt   : Lane → Bool
  halt : Lane → Bool

/-- The timeout (`ArmT.EngBA.tmo`), never for a no-timeout ARM. -/
def EngBP.tmo (B : EngBP) (win : Engine → Option Lane) (l : Lane) : Bool :=
  B.A.tmo win l && !B.nt l

/-- The arming ends: its edge or its timeout. -/
def EngBP.ends (B : EngBP) (win : Engine → Option Lane) (l : Lane) : Bool :=
  B.A.hit l || B.tmo win l

/-- The flush set: a FALLTHROUGH arming's end (edge: PC+2; timeout: PC+1). -/
def EngBP.fl (B : EngBP) (win : Engine → Option Lane) (l : Lane) : Bool :=
  B.ends win l && B.ft l

/-- A plain edge: rebase, no flush. -/
def EngBP.pe (B : EngBP) (l : Lane) : Bool := B.A.hit l && !B.ft l

/-- A plain timeout: the lane halts. -/
def EngBP.ph (B : EngBP) (win : Engine → Option Lane) (l : Lane) : Bool :=
  B.tmo win l && !B.ft l

/-- The dispatcher's mask: armed or halted. -/
def EngBP.mask (B : EngBP) (l : Lane) : Bool := B.A.armed l || B.halt l

/-- The program with the halted lanes no longer live (`live_n := 0`). -/
def Program.haltP (P : Program) (halt : Lane → Bool) : Program :=
  { P with live := fun l => P.live l && !halt l }

/-- The plain edge's rebase: `ts := now + off`; the rebase bit only when `off = 0`. -/
def EngBK.rebase (pe : Lane → Bool) (now : Nat) (off : Lane → Nat) (X : EngBK) : EngBK where
  x := { X.x with e := { X.x.e with
    ts := fun l => if pe l = true then now + off l else X.x.e.ts l } }
  pkill := X.pkill
  reb := fun l => if pe l = true then decide (off l = 0) else X.reb l

theorem rebase_none (pe : Lane → Bool) (now : Nat) (off : Lane → Nat) (X : EngBK)
    (h : ∀ l, pe l = false) : EngBK.rebase pe now off X = X := by
  have hf : (fun l => if pe l = true then now + off l else X.x.e.ts l) = X.x.e.ts := by
    funext l; simp [h l]
  have hr : (fun l => if pe l = true then decide (off l = 0) else X.reb l) = X.reb := by
    funext l; simp [h l]
  unfold EngBK.rebase
  rw [hf, hr]

theorem haltP_none (P : Program) (halt : Lane → Bool) (h : ∀ l, halt l = false) :
    P.haltP halt = P := by
  have hf : (fun l => P.live l && !halt l) = P.live := by
    funext l; simp [h l]
  unfold Program.haltP
  rw [hf]

/-- A plain edge does not flush. -/
theorem pe_not_fl (B : EngBP) (win : Engine → Option Lane) (l : Lane) (h : B.pe l = true) :
    B.fl win l = false := by
  unfold EngBP.pe at h
  unfold EngBP.fl
  simp only [Bool.and_eq_true, Bool.not_eq_true'] at h
  rw [h.2]
  simp

/-- A no-timeout ARM never times out. -/
theorem stepBPR_nt_no_tmo (B : EngBP) (win : Engine → Option Lane) (l : Lane)
    (h : B.nt l = true) : B.tmo win l = false := by
  unfold EngBP.tmo
  rw [h]
  simp

/-- A halted lane is never dispatched. -/
theorem winA_halt (win : Engine → Option Lane) (B : EngBP) (l : Lane) (h : B.halt l = true)
    (e : Engine) : winA win B.mask e ≠ some l := by
  unfold winA
  cases hw : win e with
  | none => simp
  | some v =>
    simp only
    by_cases hv : v = l
    · subst hv
      have hm : B.mask v = true := by unfold EngBP.mask; rw [h]; simp
      rw [if_pos hm]
      simp
    · split
      · simp
      · intro hc
        exact hv (Option.some.inj hc)

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (isFT : EngB → Bool) (offW : EngB → Nat) (ntW : EngB → Bool)

/-- **One cycle of the RTL-side armed run with the plain end.** -/
def stepBPR (nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) : EngBP where
  A :=
    { X := EngBK.rebase B.pe B.A.X.x.e.now B.off
        (EngBK.keepTs (B.tmo win) B.A.X
          (stepBKKR (P.haltP B.halt) (winA win B.mask) usb sreq nw (B.fl win) k B.A.X))
      armed := fun l => if B.ends win l = true then false
        else if B.A.arms P isArm l = true then true else B.A.armed l
      armE := fun l => if B.A.arms P isArm l = true then edge B.A.X.x.e.now l else B.A.armE l }
  ft := fun l => if B.A.arms P isArm l = true then isFT B.A.X.base else B.ft l
  off := fun l => if B.A.arms P isArm l = true then offW B.A.X.base else B.off l
  nt := fun l => if B.A.arms P isArm l = true then ntW B.A.X.base else B.nt l
  halt := fun l => B.halt l || B.ph win l

/-- `n` cycles; the no-swap decisions and the kept indices read by time. -/
def runBPR (nwt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) : Nat → EngBP → EngBP
  | 0, B => B
  | n + 1, B => stepBPR P win usb sreq isArm edge isFT offW ntW
      (nwt (runBPR nwt kt n B).A.X.x.e.now) (kt (runBPR nwt kt n B).A.X.x.e.now)
      (runBPR nwt kt n B)

/-- **With every latch FALLTHROUGH, no no-timeout ARM and no halt, the step is `stepBTR`.** -/
theorem stepBPR_A_eq (nw : Lane → Bool) (k : Lane → Nat) (B : EngBP)
    (hft : ∀ l, B.ft l = true) (hnt : ∀ l, B.nt l = false) (hh : ∀ l, B.halt l = false) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW nw k B).A
      = stepBTR P win usb sreq isArm edge nw k B.A := by
  have htmo : B.tmo win = B.A.tmo win := by
    funext l; unfold EngBP.tmo; rw [hnt l]; simp
  have hends : B.ends win = B.A.ends win := by
    funext l; unfold EngBP.ends EngBA.ends; rw [htmo]
  have hfl : B.fl win = B.A.ends win := by
    funext l; unfold EngBP.fl; rw [hends, hft l]; simp
  have hmask : B.mask = B.A.armed := by
    funext l; unfold EngBP.mask; rw [hh l]; simp
  have hpe : ∀ l, B.pe l = false := by
    intro l; unfold EngBP.pe; rw [hft l]; simp
  have hP : P.haltP B.halt = P := haltP_none P B.halt hh
  unfold stepBPR stepBTR
  dsimp only
  rw [rebase_none _ _ _ _ hpe, htmo, hends, hfl, hmask, hP]

/-- **A plain edge rebases `ts` to `now + off`.** -/
theorem stepBPR_pe_ts (nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane)
    (h : B.pe l = true) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW nw k B).A.X.x.e.ts l
      = B.A.X.x.e.now + B.off l := by
  show (if B.pe l = true then B.A.X.x.e.now + B.off l else _) = _
  rw [if_pos h]

/-- A plain edge sets the rebase bit exactly when `off = 0`. -/
theorem stepBPR_pe_reb (nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane)
    (h : B.pe l = true) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW nw k B).A.X.reb l = decide (B.off l = 0) := by
  show (if B.pe l = true then decide (B.off l = 0) else _) = _
  rw [if_pos h]

/-- **A plain edge releases at `now + max 1 off`**: the cycle after for a plain ARM, the edge
plus half a period for HALF (`l_t/2 ≥ 1`). -/
theorem stepBPR_pe_rel (nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane)
    (h : B.pe l = true) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW nw k B).A.X.rel l
      = B.A.X.x.e.now + max 1 (B.off l) := by
  unfold EngBK.rel
  rw [stepBPR_pe_ts P win usb sreq isArm edge isFT offW ntW nw k B l h,
    stepBPR_pe_reb P win usb sreq isArm edge isFT offW ntW nw k B l h]
  by_cases h0 : B.off l = 0
  · simp [h0]
  · simp [h0]
    omega

/-- **A plain timeout halts the lane and disarms it.** -/
theorem stepBPR_ph_halt (nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane)
    (h : B.ph win l = true) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW nw k B).halt l = true ∧
      (stepBPR P win usb sreq isArm edge isFT offW ntW nw k B).A.armed l = false := by
  have he : B.ends win l = true := by
    unfold EngBP.ph at h
    unfold EngBP.ends
    simp only [Bool.and_eq_true] at h
    rw [h.1]
    simp
  constructor
  · show (B.halt l || B.ph win l) = true
    rw [h]
    simp
  · show (if B.ends win l = true then false else _) = false
    rw [if_pos he]

/-- A halted lane stays halted. -/
theorem stepBPR_halt_mono (nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) (l : Lane)
    (h : B.halt l = true) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW nw k B).halt l = true := by
  show (B.halt l || B.ph win l) = true
  rw [h]
  simp

theorem stepBPR_now (nw : Lane → Bool) (k : Lane → Nat) (B : EngBP) :
    (stepBPR P win usb sreq isArm edge isFT offW ntW nw k B).A.X.x.e.now
      = B.A.X.x.e.now + 1 := by
  show (stepBR (P.haltP B.halt) (winA win B.mask) usb sreq nw B.A.X.base).e.now = _
  have hn : (stepBR (P.haltP B.halt) (winA win B.mask) usb sreq nw B.A.X.base).e.now
      = B.A.X.base.e.now + 1 := rfl
  rw [hn, base_e]

end

end JLane

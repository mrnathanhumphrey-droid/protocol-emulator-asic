import JLane.ComposeB
/-!
# Brick K6a — fetch order on the flushed run (Wilson's K6, the order-invariant build, step 1)

BufEng's order invariant `OrdB` (head = `nr`, spare = `nr + 1`, buffer = `nr + nslots`, the
word in flight = `nr + nslots` of its lane) is preserved by every buffered cycle
(`BufEng.ordB_step`). On the flushed run (`FlushKill.stepBKK`) it breaks in two places only:

* **the flush**: the lane keeps one word, selected by its fetch index `k l`, in its head, and the
  flush writes its index as the lane's next retirement position after the cycle (FlushKill,
  Wilson 11-20 K6). So the head rule survives every flush, edge or timeout, with no premise. At
  an edge the kept word is the lane's oldest unretired word anyway (`KeepOk`, K3(a)), so the
  write changes nothing there; at a timeout swap the kept PC+1 takes the dropped PC+2's
  position. `KeepOk` remains what identifies the kept word as the edge word
  (`hasEdge_of_head`, `ready_ft_edge_K`).
* **the kill**: a killed in-flight fetch keeps its stale index after the flush shrank the lane.
  So `OrdBK` asks the in-flight rule only while no kill is pending. The killed capture files
  nothing (`FlushKill.kill_files_nothing`), so nothing reads its index.

Proved:
* `ordBK_step` -- `OrdBK` survives a cycle, given `WfBK` and `FlushOk`;
* `ordBK_run` -- along a run, given `FlushOk` at every cycle (edge and timeout flushes alike);
* `ordBK_init` -- a run starts from BufEng's `OrdB` with no kill pending.

Method: where the kill is pending, the cycle's slot and buffer writes that survive are not the
killed capture, so BufEng's per-field lemmas apply to the engine with the in-flight index reset
(`fixB`), which agrees with the real one on every surviving write (`sqB_fix`, `bsqB_fix`).
-/
namespace JLane

/-- The engine with the in-flight index set to its lane's next index. Used where the in-flight
fetch is killed: its index is never filed, so the value is free. -/
def fixB (x : EngB) : EngB := { x with psq := x.nr x.e.pl + nslots x.e x.e.pl }

theorem wfB_fixB (x : EngB) (hW : WfB x) : WfB (fixB x) :=
  ⟨hW.disp, hW.hf, hW.fe, hW.fnb, hW.bh, hW.sf⟩

/-- A slot write agrees with the reset engine's, unless it is a capture with another index. -/
theorem sqB_fix (x : EngB) (l : Lane) (s : Slot)
    (h : capTo x l s = true → x.psq = x.nr x.e.pl + nslots x.e x.e.pl) :
    sqB x l s = sqB (fixB x) l s := by
  have hc' : capTo (fixB x) l s = capTo x l s := rfl
  have hl' : loadTo (fixB x) l s = loadTo x l s := rfl
  unfold sqB
  rw [hc', hl']
  cases hc : capTo x l s
  · simp only [Bool.false_eq_true, if_false]
    rfl
  · simp only [if_true]
    exact h hc

theorem bsqB_fix (x : EngB) (l : Lane)
    (h : capBuf x l = true → x.psq = x.nr x.e.pl + nslots x.e x.e.pl) :
    bsqB x l = bsqB (fixB x) l := by
  have hc' : capBuf (fixB x) l = capBuf x l := rfl
  unfold bsqB
  rw [hc']
  cases hc : capBuf x l
  · simp only [Bool.false_eq_true, if_false]
    rfl
  · simp only [if_true]
    exact h hc

/-- **Fetch order on the flushed run.** BufEng's `OrdB`, with the in-flight rule asked only
while no kill is pending. -/
structure OrdBK (X : EngBK) : Prop where
  o1 : ∀ l, X.x.e.headValid l = true → X.x.sq l (X.x.e.sel l) = X.x.nr l
  o2 : ∀ l, X.x.e.spareValid l = true → X.x.sq l (!X.x.e.sel l) = X.x.nr l + 1
  o3 : ∀ l, X.x.buf l = true → X.x.bsq l = X.x.nr l + nslots X.x.e l
  o4 : X.pkill = false → X.x.e.pst ≠ .scan →
    X.x.psq = X.x.nr X.x.e.pl + nslots X.x.e X.x.e.pl

/-- **The keep premise** (K3(a)): at a flush on lane `l`, the kept word's index is the lane's
next retirement index after the cycle -- the kept word is the lane's oldest unretired word. -/
def KeepOk (P : Program) (fl : Lane → Bool) (k : Lane → Nat) (X : EngBK) : Prop :=
  ∀ l, fl l = true → k l = nrB P X.x l

theorem ordBK_init (x : EngB) (hO : OrdB x) : OrdBK ⟨x, false⟩ :=
  ⟨hO.o1, hO.o2, hO.o3, fun _ => hO.o4⟩

theorem ordBK_ordB (X : EngBK) (hO : OrdBK X) (hk : X.pkill = false) : OrdB X.x :=
  ⟨hO.o1, hO.o2, hO.o3, hO.o4 hk⟩

theorem ordB_fixK (X : EngBK) (hO : OrdBK X) : OrdB (fixB X.base) := by
  unfold EngBK.base
  split
  · exact ⟨hO.o1, hO.o2, hO.o3, fun _ => rfl⟩
  · exact ⟨hO.o1, hO.o2, hO.o3, fun _ => rfl⟩

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (fl : Lane → Bool) (k : Lane → Nat)

theorem nrB_base (X : EngBK) : nrB P X.base = nrB P X.x := by
  unfold EngBK.base
  split <;> rfl

theorem nrK (X : EngBK) : (stepBKK P win usb sreq fl k X).x.nr = nrB P X.base := rfl

theorem psqK (X : EngBK) :
    (stepBKK P win usb sreq fl k X).x.psq = psqB P usb sreq X.base := rfl

/-- On an unflushed lane, a slot valid after the cycle was valid in `stepB`'s (the kill only
clears). -/
theorem actv_srcK (X : EngBK) (l : Lane) (s : Slot) (hfl : fl l = false)
    (hv : (stepBKK P win usb sreq fl k X).x.e.actv l s = true) :
    (stepB P win usb sreq X.base).e.actv l s = true := by
  rw [actvK, hfl] at hv
  simp only [Bool.false_eq_true, ↓reduceIte] at hv
  split at hv
  · cases hv
  · exact hv

/-- On an unflushed lane that is not the killed capture's, the slots are `stepB`'s. -/
theorem actv_plainK (X : EngBK) (l : Lane) (hfl : fl l = false)
    (hno : (X.kc && decide (l = X.base.e.pl)) = false) (s : Slot) :
    (stepBKK P win usb sreq fl k X).x.e.actv l s = (stepB P win usb sreq X.base).e.actv l s := by
  rw [actvK, hfl]
  simp only [Bool.false_eq_true, ↓reduceIte, hno, Bool.false_and]

/-- A capture whose slot holds after the cycle is not killed: its index is its lane's next. -/
theorem cap_okK (X : EngBK) (hO : OrdBK X) (l : Lane) (s : Slot) (hfl : fl l = false)
    (hv : (stepBKK P win usb sreq fl k X).x.e.actv l s = true)
    (hc : capTo X.base l s = true) :
    X.base.psq = X.base.nr X.base.e.pl + nslots X.base.e X.base.e.pl := by
  obtain ⟨hpc, hlp⟩ := capTo_cap _ _ _ hc
  cases hk : X.pkill
  · rw [base_nokill X hk] at hpc ⊢
    exact hO.o4 hk (by rw [hpc]; decide)
  · exfalso
    have hkc : X.kc = true := by
      rw [base_e X] at hpc
      unfold EngBK.kc
      simp [hpc, hk]
    have hcond : (X.kc && decide (l = X.base.e.pl) && capTo X.base l s) = true := by
      rw [hkc, hc]
      simp [hlp]
    rw [actvK, hfl] at hv
    simp [hcond] at hv

/-- A capture into a buffer that holds after the cycle is not killed. -/
theorem capBuf_okK (X : EngBK) (hO : OrdBK X) (l : Lane) (hfl : fl l = false)
    (hb : (stepBKK P win usb sreq fl k X).x.buf l = true)
    (hc : capBuf X.base l = true) :
    X.base.psq = X.base.nr X.base.e.pl + nslots X.base.e X.base.e.pl := by
  obtain ⟨hpc, hlp, -, -⟩ := capBuf_spec _ _ hc
  cases hk : X.pkill
  · rw [base_nokill X hk] at hpc ⊢
    exact hO.o4 hk (by rw [hpc]; decide)
  · exfalso
    have hkc : X.kc = true := by
      rw [base_e X] at hpc
      unfold EngBK.kc
      simp [hpc, hk]
    have hcond : (X.kc && decide (l = X.base.e.pl)) = true := by
      simp [hkc, hlp]
    rw [bufK, hfl] at hb
    simp [hcond] at hb

theorem ordK_o1 (X : EngBK) (hI : WfBK X) (hO : OrdBK X) (l : Lane)
    (hv : (stepBKK P win usb sreq fl k X).x.e.headValid l = true) :
    (stepBKK P win usb sreq fl k X).x.sq l ((stepBKK P win usb sreq fl k X).x.e.sel l)
      = (stepBKK P win usb sreq fl k X).x.nr l := by
  rw [nrK]
  cases hfl : fl l
  · have hnf : ¬fl l = true := by rw [hfl]; decide
    have hnc : ∀ s, ¬(fl l = true ∧ s = keepSlot X.base l (k l)) := fun _ h => hnf h.1
    have hsel : (stepBKK P win usb sreq fl k X).x.e.sel l = selNext P X.base.e l := by
      rw [selK, if_neg hnf]
      rfl
    have hvY : (stepBKK P win usb sreq fl k X).x.e.actv l (selNext P X.base.e l) = true := by
      have := hv
      unfold Engine.headValid at this
      rw [hsel] at this
      exact this
    have hv' := actv_srcK P win usb sreq fl k X l _ hfl hvY
    rw [hsel, sqK, if_neg (hnc _),
      sqB_fix X.base l _ (fun hc => cap_okK P win usb sreq fl k X hO l _ hfl hvY hc)]
    exact ordB_o1 P (fixB X.base) (wfB_fixB _ hI.wf) (ordB_fixK X hO) l hv'
  · have hsel : (stepBKK P win usb sreq fl k X).x.e.sel l = keepSlot X.base l (k l) := by
      rw [selK, if_pos hfl]
    -- the flush writes the kept word's index as the lane's count after the cycle (FlushKill,
    -- Wilson 11-20 K6): the head rule holds at every flush, edge or timeout, without KeepOk
    rw [hsel, sqK, if_pos ⟨hfl, rfl⟩]

theorem ordK_o2 (X : EngBK) (hI : WfBK X) (hO : OrdBK X) (l : Lane)
    (hv : (stepBKK P win usb sreq fl k X).x.e.spareValid l = true) :
    (stepBKK P win usb sreq fl k X).x.sq l (!(stepBKK P win usb sreq fl k X).x.e.sel l)
      = (stepBKK P win usb sreq fl k X).x.nr l + 1 := by
  rw [nrK]
  cases hfl : fl l
  · have hnf : ¬fl l = true := by rw [hfl]; decide
    have hnc : ∀ s, ¬(fl l = true ∧ s = keepSlot X.base l (k l)) := fun _ h => hnf h.1
    have hsel : (stepBKK P win usb sreq fl k X).x.e.sel l = selNext P X.base.e l := by
      rw [selK, if_neg hnf]
      rfl
    have hvY : (stepBKK P win usb sreq fl k X).x.e.actv l (!selNext P X.base.e l) = true := by
      have := hv
      unfold Engine.spareValid at this
      rw [hsel] at this
      exact this
    have hv' := actv_srcK P win usb sreq fl k X l _ hfl hvY
    rw [hsel, sqK, if_neg (hnc _),
      sqB_fix X.base l _ (fun hc => cap_okK P win usb sreq fl k X hO l _ hfl hvY hc)]
    exact ordB_o2 P (fixB X.base) (wfB_fixB _ hI.wf) (ordB_fixK X hO) l hv'
  · exfalso
    unfold Engine.spareValid at hv
    rw [selK, if_pos hfl, actvK, if_pos hfl] at hv
    revert hv
    cases keepSlot X.base l (k l) <;> simp

theorem ordK_o3 (X : EngBK) (hI : WfBK X) (hO : OrdBK X) (l : Lane) (hb : (stepBKK P win usb sreq fl k X).x.buf l = true) :
    (stepBKK P win usb sreq fl k X).x.bsq l
      = (stepBKK P win usb sreq fl k X).x.nr l
        + nslots (stepBKK P win usb sreq fl k X).x.e l := by
  rw [nrK, bsqK]
  cases hfl : fl l
  · have hnf : ¬fl l = true := by rw [hfl]; decide
    have hno : (X.kc && decide (l = X.base.e.pl)) = false := by
      cases h : (X.kc && decide (l = X.base.e.pl))
      · rfl
      · exfalso
        rw [bufK, if_neg hnf, if_pos h] at hb
        cases hb
    have hno' : ¬(X.kc && decide (l = X.base.e.pl)) = true := by rw [hno]; decide
    have hb' : bufB X.base l = true := by
      have := hb
      rw [bufK, if_neg hnf, if_neg hno'] at this
      exact this
    have hns : nslots (stepBKK P win usb sreq fl k X).x.e l
        = nslots (stepB P win usb sreq X.base).e l := by
      unfold nslots
      rw [actv_plainK P win usb sreq fl k X l hfl hno false,
        actv_plainK P win usb sreq fl k X l hfl hno true]
    have hE : nslots (stepB P win usb sreq (fixB X.base)).e l
        = nslots (stepB P win usb sreq X.base).e l := rfl
    rw [hns, bsqB_fix X.base l (fun hc => capBuf_okK P win usb sreq fl k X hO l hfl hb hc), ← hE]
    exact ordB_o3 P win usb sreq (fixB X.base) (wfB_fixB _ hI.wf) (ordB_fixK X hO) l hb'
  · exfalso
    rw [bufK, if_pos hfl] at hb
    cases hb

theorem ordK_o4 (hok : SReqB P sreq) (X : EngBK) (hI : WfBK X) (hO : OrdBK X)
    (hF : FlushOk P win usb sreq fl X)
    (hk0 : (stepBKK P win usb sreq fl k X).pkill = false)
    (hne : (stepBKK P win usb sreq fl k X).x.e.pst ≠ .scan) :
    (stepBKK P win usb sreq fl k X).x.psq
      = (stepBKK P win usb sreq fl k X).x.nr (stepBKK P win usb sreq fl k X).x.e.pl
        + nslots (stepBKK P win usb sreq fl k X).x.e (stepBKK P win usb sreq fl k X).x.e.pl := by
  have hne' : (stepB P win usb sreq X.base).e.pst ≠ .scan := hne
  obtain ⟨hfl, hkc⟩ := flight_clean P win usb sreq fl k hok X hI hF hk0 hne'
  have hk : X.pkill = false := by
    have hc : ¬X.x.e.pst = .cap := fun hc =>
      hne' (cap_to_scan P usb sreq X.base (by rw [base_e]; exact hc))
    cases hp : X.pkill
    · rfl
    · exfalso
      rw [pkillK, if_neg hc, hp] at hk0
      simp at hk0
  have hOb : OrdB X.base := by
    rw [base_nokill X hk]
    exact ordBK_ordB X hO hk
  have hno : (X.kc && decide ((stepB P win usb sreq X.base).e.pl = X.base.e.pl)) = false := by
    rw [hkc]
    rfl
  have hns : nslots (stepBKK P win usb sreq fl k X).x.e (stepBKK P win usb sreq fl k X).x.e.pl
      = nslots (stepB P win usb sreq X.base).e (stepB P win usb sreq X.base).e.pl := by
    rw [plK]
    unfold nslots
    rw [actv_plainK P win usb sreq fl k X _ hfl hno false,
      actv_plainK P win usb sreq fl k X _ hfl hno true]
  rw [hns]
  exact ordB_o4 P win usb sreq hok X.base hI.wf hOb hne'

/-- **Fetch order survives a flushed cycle**, given the flush conditions -- any flush, edge or
timeout: the kept word takes the lane's next retirement position (Wilson 11-20 K6). -/
theorem ordBK_step (hok : SReqB P sreq) (X : EngBK) (hI : WfBK X) (hO : OrdBK X)
    (hF : FlushOk P win usb sreq fl X) :
    OrdBK (stepBKK P win usb sreq fl k X) :=
  ⟨fun l hv => ordK_o1 P win usb sreq fl k X hI hO l hv,
   fun l hv => ordK_o2 P win usb sreq fl k X hI hO l hv,
   fun l hb => ordK_o3 P win usb sreq fl k X hI hO l hb,
   fun hk0 hne => ordK_o4 P win usb sreq fl k hok X hI hO hF hk0 hne⟩

/-- **Fetch order along a flushed run**, given the flush conditions at every cycle of it --
edge and timeout flushes alike (Wilson 11-20 K6). -/
theorem ordBK_run (hok : SReqB P sreq) (flt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) :
    ∀ (n : Nat) (X : EngBK), WfBK X → OrdBK X →
      (∀ j, j < n → FlushOk P win usb sreq (flt (runBK P win usb sreq flt kt j X).x.e.now)
        (runBK P win usb sreq flt kt j X)) →
      OrdBK (runBK P win usb sreq flt kt n X)
  | 0, _, _, h, _ => h
  | n + 1, X, hI, hO, hF => by
    have h1 := wfBK_step P win usb sreq (flt X.x.e.now) (kt X.x.e.now) hok X hI
      (hF 0 (Nat.succ_pos n))
    have h2 := ordBK_step P win usb sreq (flt X.x.e.now) (kt X.x.e.now) hok X hI hO
      (hF 0 (Nat.succ_pos n))
    exact ordBK_run hok flt kt n _ h1 h2 (fun j hj => hF (j + 1) (Nat.succ_lt_succ hj))

end

/-! ### Step 2: the edge word at the edge, and `hord`, from the order

With `OrdBK` on the run, the head's index is `nr`. So at an edge where the kept index is the
lane's retirement count (`hkeep`: K3(a)), a valid head IS the edge word: `ComposeB`'s `hidx`
(which slot fetch brings it) is not needed, and neither is the persistence argument behind
`hord`. `hord` itself also follows: a retirement at an earlier cycle consumes the head, whose
index is the retirement count then, strictly below the count at the edge. -/

/-- A valid head with index `kk = nr` means the lane holds the edge word `kk`. -/
theorem hasEdge_of_head (X : EngBK) (hO : OrdBK X) (y : Lane) (kk : Nat)
    (hv : X.x.e.headValid y = true) (hk : kk = X.x.nr y) : X.base.hasEdge y kk = true := by
  have h1 := hO.o1 y hv
  have hv' : X.x.e.actv y (X.x.e.sel y) = true := hv
  have hs : X.base.inSlot y kk (X.base.e.sel y) = true := by
    unfold EngB.inSlot
    rw [base_e, base_sq, h1, ← hk, hv']
    simp
  unfold EngB.hasEdge
  cases hsel : X.base.e.sel y
  · rw [hsel] at hs
    simp [hs]
  · rw [hsel] at hs
    simp [hs]

theorem nrB_ge (P : Program) (x : EngB) (l : Lane) : x.nr l ≤ nrB P x l := by
  unfold nrB
  split <;> omega

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

theorem nr_runBK_succ (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (m : Nat) :
    (runBK P win usb sreq fl k (m + 1) X0).x.nr = nrB P (runBK P win usb sreq fl k m X0).base := by
  rw [runBK_succ']
  rfl

/-- The retirement count never decreases along the run. -/
theorem nr_le_runBK (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat) (X0 : EngBK) (y : Lane) :
    ∀ d i, (runBK P win usb sreq fl k i X0).x.nr y ≤ (runBK P win usb sreq fl k (i + d) X0).x.nr y
  | 0, _ => Nat.le_refl _
  | d + 1, i => by
    have ih := nr_le_runBK fl k X0 y d i
    have hs := nrB_ge P (runBK P win usb sreq fl k (i + d) X0).x y
    rw [show i + (d + 1) = (i + d) + 1 by omega, nr_runBK_succ, nrB_base]
    omega

/-- **`hord` from the order** (the premise of `ComposeB.ready_ft_edge_T`): a retirement of `y`
at a cycle `i` before the edge `f` never consumes the edge word `k = nr` (at `f`). -/
theorem hord_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (hO : OrdBK X0) (y : Lane) (i f : Nat) (hif : i < f)
    (hF : ∀ j, j < f → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hK : ∀ j, j < f → KeepOk P (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (k (runBK P win usb sreq fl k j X0).x.e.now) (runBK P win usb sreq fl k j X0))
    (hkeep : k (runBK P win usb sreq fl k f X0).x.e.now y
      = (runBK P win usb sreq fl k f X0).x.nr y) :
    (runBK P win usb sreq fl k i X0).base.e.st = .wb →
      y = (runBK P win usb sreq fl k i X0).base.e.cur →
      P.ret (runBK P win usb sreq fl k i X0).base.e.now
        (runBK P win usb sreq fl k i X0).base.e.cur = true →
      (runBK P win usb sreq fl k i X0).base.inSlot y
        (k (runBK P win usb sreq fl k f X0).x.e.now y)
        ((runBK P win usb sreq fl k i X0).base.e.sel y) = false := by
  intro hst hy hret
  have hWi := wfBK_run P win usb sreq hok fl k i X0 hI (fun j hj => hF j (by omega))
  have hOi := ordBK_run P win usb sreq hok fl k i X0 hI hO (fun j hj => hF j (by omega))
  have hvb := hWi.wf.disp (by rw [hst]; decide)
  have hbe := base_e (runBK P win usb sreq fl k i X0)
  rw [← hy, hbe] at hvb
  rw [hbe] at hst hy hret
  have hR : IsRet P y (runBK P win usb sreq fl k i X0).x.e :=
    ⟨hst, hy.symm, by rw [hy]; exact hret⟩
  have h1 : (runBK P win usb sreq fl k (i + 1) X0).x.nr y
      = (runBK P win usb sreq fl k i X0).x.nr y + 1 := by
    rw [nr_runBK_succ, nrB_base, nrB_eq, if_pos hR]
  have h2 := nr_le_runBK P win usb sreq fl k X0 y (f - (i + 1)) (i + 1)
  rw [show i + 1 + (f - (i + 1)) = f by omega] at h2
  have hne : (runBK P win usb sreq fl k i X0).x.nr y
      ≠ k (runBK P win usb sreq fl k f X0).x.e.now y := by omega
  unfold EngB.inSlot
  rw [hbe, base_sq, hOi.o1 y hvb]
  simp [hne]

/-- **`ready_ft_edge_T` from the order** (K6 step 2). On a run with fetch order (`OrdBK`, kept
by `KeepOk` at every earlier cycle), at a flush `f` of `y` whose kept index is `y`'s retirement
count (`hkeep`, K3(a)), a valid head at `f` (`ComposeB.head_valid_runBK`, L3) is the edge word:
the edge word is present, and the cycle after the edge it is `y`'s valid head, released that
cycle. No slot-wait premises, no `hidx`, no `hord`. -/
theorem ready_ft_edge_K (hok : SReqB P sreq) (fl : Nat → Lane → Bool) (k : Nat → Lane → Nat)
    (X0 : EngBK) (hI : WfBK X0) (hO : OrdBK X0) (y : Lane) (f : Nat)
    (hF : ∀ j, j < f → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hK : ∀ j, j < f → KeepOk P (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (k (runBK P win usb sreq fl k j X0).x.e.now) (runBK P win usb sreq fl k j X0))
    (hfl : fl (runBK P win usb sreq fl k f X0).x.e.now y = true)
    (hkeep : k (runBK P win usb sreq fl k f X0).x.e.now y
      = (runBK P win usb sreq fl k f X0).x.nr y)
    (hv : (runBK P win usb sreq fl k f X0).x.e.headValid y = true) :
    (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true ∧
    (runBK P win usb sreq fl k (f + 1) X0).x.e.headValid y = true ∧
    (runBK P win usb sreq fl k (f + 1) X0).x.sq y
      ((runBK P win usb sreq fl k (f + 1) X0).x.e.sel y)
      = (runBK P win usb sreq fl k (f + 1) X0).x.nr y ∧
    (runBK P win usb sreq fl k (f + 1) X0).x.e.ts y
      = (runBK P win usb sreq fl k (f + 1) X0).x.e.now := by
  have hOf := ordBK_run P win usb sreq hok fl k f X0 hI hO hF
  have hE := hasEdge_of_head _ hOf y _ hv hkeep
  refine ⟨hE, ?_⟩
  have := edge_survives_flushK P win usb sreq _ _ (runBK P win usb sreq fl k f X0) y hfl hE
  rw [← runBK_succ'] at this
  exact this

end

/-! ### The keep premise from the arming chain (K6 build, option 1)

`kt` (the edge word's index by time) is an input of the run, so "the kept index is the lane's
retirement count" is not a fact of the engine alone. It reduces to one local premise at each
arming (`hidxA`): the edge word is the next word in fetch order after the ARM (index = the ARM's
index + 1, the edge-first order of K7). The arming chain carries it to the edge: the ARM retires
at its arming writeback (`nrB_arms`), and an armed lane is never dispatched (`ArmInvB`), so it
retires nothing until its edge, the edge cycle included (`nrB_armed`, `nr_frozen`). -/

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (kt : Nat → Lane → Nat) (A0 : EngBA)

/-- An armed lane does not retire this cycle (it is not dispatched). -/
theorem nrB_armed (A : EngBA) (hA : ArmInvB A) (y : Lane) (ha : A.armed y = true) :
    nrB P A.X.x y = A.X.x.nr y := by
  have hc : ¬(A.X.x.e.st = .wb ∧ y = A.X.x.e.cur ∧ P.ret A.X.x.e.now A.X.x.e.cur = true) := by
    rintro ⟨hst, hy, -⟩
    exact hA.1 y ha ⟨by rw [hst]; decide, hy.symm⟩
  unfold nrB
  rw [if_neg hc]

/-- The arming writeback retires the ARM. -/
theorem nrB_arms (A : EngBA) (y : Lane) (har : A.arms P isArm y = true) :
    nrB P A.X.x y = A.X.x.nr y + 1 := by
  unfold EngBA.arms at har
  simp only [Bool.and_eq_true, decide_eq_true_eq] at har
  unfold nrB
  rw [if_pos ⟨har.1.1.1, har.1.1.2, har.1.2⟩]

theorem nr_runBA_succ (n : Nat) :
    (runBA P win usb sreq isArm edge kt (n + 1) A0).X.x.nr
      = nrB P (runBA P win usb sreq isArm edge kt n A0).X.base := rfl

/-- While armed, the lane's retirement count is frozen. -/
theorem nr_frozen (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0) (y : Lane) (t0 : Nat) :
    ∀ d, (∀ i, t0 < i → i ≤ t0 + 1 + d → (runBA P win usb sreq isArm edge kt i A0).armed y = true) →
      (runBA P win usb sreq isArm edge kt (t0 + 1 + d) A0).X.x.nr y
        = (runBA P win usb sreq isArm edge kt (t0 + 1) A0).X.x.nr y
  | 0, _ => rfl
  | d + 1, ha => by
    have ih := nr_frozen hedge hA y t0 d (fun i h1 h2 => ha i h1 (by omega))
    rw [show t0 + 1 + (d + 1) = (t0 + 1 + d) + 1 by omega, nr_runBA_succ, nrB_base,
      nrB_armed P _ (armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA _) y
        (ha _ (by omega) (by omega)), ih]

/-- **At a hit, the edge word's index is the lane's retirement count**, and the lane does not
retire in the edge cycle -- given `hidxA` at each arming. -/
theorem keep_at_hit (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : ∀ l, A0.armed l = false)
    (hidxA : ∀ t0 y, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1)
    (n : Nat) (y : Lane) (hh : (runBA P win usb sreq isArm edge kt n A0).hit y = true) :
    kt (runBA P win usb sreq isArm edge kt n A0).X.x.e.now y
        = (runBA P win usb sreq isArm edge kt n A0).X.x.nr y ∧
      nrB P (runBA P win usb sreq isArm edge kt n A0).X.x y
        = (runBA P win usb sreq isArm edge kt n A0).X.x.nr y := by
  have hh' := hh
  unfold EngBA.hit at hh'
  simp only [Bool.and_eq_true, decide_eq_true_eq] at hh'
  obtain ⟨ha, hnow⟩ := hh'
  obtain ⟨t0, ht0, harm, hae, hall⟩ := armed_origin P win usb sreq isArm edge kt A0 h0 y n ha
  have hAn := armInvB_runBA P win usb sreq isArm edge hedge kt A0 hA n
  refine ⟨?_, nrB_armed P _ hAn y ha⟩
  have h1 : (runBA P win usb sreq isArm edge kt (t0 + 1) A0).X.x.nr y
      = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1 := by
    rw [nr_runBA_succ, nrB_base, nrB_arms P isArm _ y harm]
  have h2 := nr_frozen P win usb sreq isArm edge kt A0 hedge hA y t0 (n - (t0 + 1))
    (fun i h1 h2 => (hall i h1 (by omega)).1)
  rw [show t0 + 1 + (n - (t0 + 1)) = n by omega] at h2
  rw [hnow, hae, hidxA t0 y harm, h2, h1]

/-- **`KeepOk` at every cycle of the armed run.** -/
theorem keepOk_runBA (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : ∀ l, A0.armed l = false)
    (hidxA : ∀ t0 y, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1)
    (n : Nat) :
    KeepOk P (runBA P win usb sreq isArm edge kt n A0).hit
      (kt (runBA P win usb sreq isArm edge kt n A0).X.x.e.now)
      (runBA P win usb sreq isArm edge kt n A0).X := fun y hh => by
  obtain ⟨hk, hn⟩ := keep_at_hit P win usb sreq isArm edge kt A0 hedge hA h0 hidxA n y hh
  rw [hn]
  exact hk

/-- **`KeepOk` on the bridged run** (`runBK P winS usb sreq flS kt`). -/
theorem keepOk_runBK (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : ∀ l, A0.armed l = false)
    (hidxA : ∀ t0 y, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1)
    (n : Nat) :
    KeepOk P (flS P win usb sreq isArm edge kt A0
        (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt n A0.X).x.e.now)
      (kt (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt n A0.X).x.e.now)
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt n A0.X) := by
  rw [← runBA_proj P win usb sreq isArm edge kt A0 n]
  have hn := now_runBA P win usb sreq isArm edge kt A0 n
  have hfl : flS P win usb sreq isArm edge kt A0
      (runBA P win usb sreq isArm edge kt n A0).X.x.e.now
      = (runBA P win usb sreq isArm edge kt n A0).hit := by
    funext l
    simp only [flS, hn, Nat.add_sub_cancel_left]
  rw [hfl]
  exact keepOk_runBA P win usb sreq isArm edge kt A0 hedge hA h0 hidxA n

/-- **`hkeep` at a flush of the bridged run.** -/
theorem hkeep_runBK (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : ∀ l, A0.armed l = false)
    (hidxA : ∀ t0 y, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1)
    (f : Nat) (y : Lane)
    (hfl : flS P win usb sreq isArm edge kt A0
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).x.e.now y = true) :
    kt (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).x.e.now y
      = (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).x.nr y := by
  rw [← runBA_proj P win usb sreq isArm edge kt A0 f] at hfl ⊢
  have hn := now_runBA P win usb sreq isArm edge kt A0 f
  simp only [flS, hn, Nat.add_sub_cancel_left] at hfl
  exact (keep_at_hit P win usb sreq isArm edge kt A0 hedge hA h0 hidxA f y hfl).1

/-- **`ready_ft_edge_K` on the armed run.** The FT edge path's head at release, with the keep
premise discharged by the arming chain: what remains is `hidxA` (per arming, K7 + edge-first),
the scan fix, the edge timing, an ordered unarmed start, and L3's head at the edge. -/
theorem ready_ft_edge_armed (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (hI : WfBK A0.X) (hO : OrdBK A0.X) (hA : ArmInvB A0) (h0 : ∀ l, A0.armed l = false)
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0))
    (hidxA : ∀ t0 y, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1)
    (y : Lane) (f : Nat)
    (hfl : flS P win usb sreq isArm edge kt A0
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).x.e.now y = true)
    (hv : (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt f A0.X).x.e.headValid y = true) :
    (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (f + 1) A0.X).x.e.headValid y = true ∧
    (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (f + 1) A0.X).x.sq y
      ((runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (f + 1) A0.X).x.e.sel y)
      = (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (f + 1) A0.X).x.nr y ∧
    (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (f + 1) A0.X).x.e.ts y
      = (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
        (flS P win usb sreq isArm edge kt A0) kt (f + 1) A0.X).x.e.now :=
  (ready_ft_edge_K P (winS P win usb sreq isArm edge kt A0) usb sreq hok
    (flS P win usb sreq isArm edge kt A0) kt A0.X hI hO y f
    (fun j _ => flushOk_runBA P win usb sreq isArm edge kt A0 hedge hA j (hscan j))
    (fun j _ => keepOk_runBK P win usb sreq isArm edge kt A0 hedge hA h0 hidxA j)
    hfl (hkeep_runBK P win usb sreq isArm edge kt A0 hedge hA h0 hidxA f y hfl) hv).2

end

#print axioms ordBK_step
#print axioms ordBK_run
#print axioms keep_at_hit
#print axioms keepOk_runBK
#print axioms hkeep_runBK
#print axioms ready_ft_edge_armed
#print axioms ordBK_init
#print axioms hasEdge_of_head
#print axioms nr_le_runBK
#print axioms hord_runBK
#print axioms ready_ft_edge_K

end JLane

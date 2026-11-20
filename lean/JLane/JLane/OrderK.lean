import JLane.FlushHeld
/-!
# Brick K6a — fetch order on the flushed run (Wilson's K6, the order-invariant build, step 1)

BufEng's order invariant `OrdB` (head = `nr`, spare = `nr + 1`, buffer = `nr + nslots`, the
word in flight = `nr + nslots` of its lane) is preserved by every buffered cycle
(`BufEng.ordB_step`). On the flushed run (`FlushKill.stepBKK`) it breaks in two places only:

* **the flush**: the lane keeps one word, with fetch index `k l`, in its head. The head rule
  survives exactly when `k l` is the lane's next retirement index after the cycle (`KeepOk`):
  the kept word is the lane's oldest unretired word. In the edge-first order this is K3(a): the
  ARM has retired before it is armed, and nothing after the edge word retires before the edge.
* **the kill**: a killed in-flight fetch keeps its stale index after the flush shrank the lane.
  So `OrdBK` asks the in-flight rule only while no kill is pending. The killed capture files
  nothing (`FlushKill.kill_files_nothing`), so nothing reads its index.

Proved:
* `ordBK_step` -- `OrdBK` survives a cycle, given `WfBK`, `FlushOk` and `KeepOk`;
* `ordBK_run` -- along a run, given `FlushOk` and `KeepOk` at every cycle;
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

theorem ordK_o1 (X : EngBK) (hI : WfBK X) (hO : OrdBK X) (hK : KeepOk P fl k X) (l : Lane)
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
    rw [hsel, sqK, if_pos ⟨hfl, rfl⟩, nrB_base]
    exact hK l hfl

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

/-- **Fetch order survives a flushed cycle**, given the flush conditions and the keep premise. -/
theorem ordBK_step (hok : SReqB P sreq) (X : EngBK) (hI : WfBK X) (hO : OrdBK X)
    (hF : FlushOk P win usb sreq fl X) (hK : KeepOk P fl k X) :
    OrdBK (stepBKK P win usb sreq fl k X) :=
  ⟨fun l hv => ordK_o1 P win usb sreq fl k X hI hO hK l hv,
   fun l hv => ordK_o2 P win usb sreq fl k X hI hO l hv,
   fun l hb => ordK_o3 P win usb sreq fl k X hI hO l hb,
   fun hk0 hne => ordK_o4 P win usb sreq fl k hok X hI hO hF hk0 hne⟩

/-- **Fetch order along a flushed run**, given the flush conditions and the keep premise at
every cycle of it. -/
theorem ordBK_run (hok : SReqB P sreq) (flt : Nat → Lane → Bool) (kt : Nat → Lane → Nat) :
    ∀ (n : Nat) (X : EngBK), WfBK X → OrdBK X →
      (∀ j, j < n → FlushOk P win usb sreq (flt (runBK P win usb sreq flt kt j X).x.e.now)
        (runBK P win usb sreq flt kt j X)) →
      (∀ j, j < n → KeepOk P (flt (runBK P win usb sreq flt kt j X).x.e.now)
        (kt (runBK P win usb sreq flt kt j X).x.e.now) (runBK P win usb sreq flt kt j X)) →
      OrdBK (runBK P win usb sreq flt kt n X)
  | 0, _, _, h, _, _ => h
  | n + 1, X, hI, hO, hF, hK => by
    have h1 := wfBK_step P win usb sreq (flt X.x.e.now) (kt X.x.e.now) hok X hI
      (hF 0 (Nat.succ_pos n))
    have h2 := ordBK_step P win usb sreq (flt X.x.e.now) (kt X.x.e.now) hok X hI hO
      (hF 0 (Nat.succ_pos n)) (hK 0 (Nat.succ_pos n))
    exact ordBK_run hok flt kt n _ h1 h2 (fun j hj => hF (j + 1) (Nat.succ_lt_succ hj))
      (fun j hj => hK (j + 1) (Nat.succ_lt_succ hj))

end

#print axioms ordBK_step
#print axioms ordBK_run
#print axioms ordBK_init

end JLane

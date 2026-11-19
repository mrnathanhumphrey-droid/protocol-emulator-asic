import JLane.BufEng
import JLane.OptRun
/-!
# Brick C3b — a refill deferred past a no-prefetch head, on the buffered engine
(`slot_on_composition`, step 1)

`OptA`'s hold and unlock (`want_frozen`, `npf_hold`, `npf_unlock`) restated on `BufEng.runB`, so
the buffered pending bound no longer needs `NoNpf` (`BufEng.want_of_held` does). `npf_state` and
`OptRun.owed_one` are facts about one engine state; they apply to `(runB …).e` as they stand.

What the buffer adds: a buffered word loads into a freed spare the cycle after a retirement
(`loadTo`), so "frozen" also needs the lane's buffer empty; and a lane holding at most one word
has an empty buffer (`held_le_one`: a buffered word sits behind a valid head, `WfB.bh`), which is
where the pending bound enters the hold. The slot never fetches past a no-prefetch word
(`SReqB`), and a held lane has no empty head for branch 1, so in the hold the lane is captured for
only by what the hypotheses name.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **The bridge into the hold.** A lane holding at most one word has an empty buffer and owes a
slot -- with no `NoNpf` (`want_of_held` also concluded the want, which a no-prefetch head
withholds). -/
theorem held_le_one (x : EngB) (hW : WfB x) (y : Lane) (h : x.held y ≤ 1) :
    x.buf y = false ∧ 1 ≤ x.e.owed y := by
  have hb : x.buf y = false := by
    cases hb : x.buf y
    · rfl
    · exfalso
      have hv := hW.bh y hb
      rw [held_def, hb] at h
      unfold Engine.headValid at hv
      cases hs : x.e.sel y <;> rw [hs] at hv <;> rw [hv] at h <;> simp [bnum] at h
  refine ⟨hb, ?_⟩
  rw [held_def, hb] at h
  unfold Engine.owed
  cases h0 : x.e.actv y false <;> cases h1 : x.e.actv y true <;> simp [h0, h1, bnum] at h ⊢

theorem capTo_of_noHit (x : EngB) (y : Lane) (hn : ¬Hit y x.e) (s : Slot) : capTo x y s = false := by
  unfold capTo
  unfold Hit at hn
  by_cases hp : x.e.pst = .cap
  · have hne : ¬y = x.e.pl := fun h => hn ⟨hp, h.symm⟩
    simp [hp, hne]
  · simp [hp]

theorem capBuf_of_noHit (x : EngB) (y : Lane) (hn : ¬Hit y x.e) : capBuf x y = false := by
  unfold capBuf
  unfold Hit at hn
  by_cases hp : x.e.pst = .cap
  · have hne : ¬y = x.e.pl := fun h => hn ⟨hp, h.symm⟩
    simp [hp, hne]
  · simp [hp]

/-- **Frozen, with the buffer.** With no capture for `y`, no retirement of `y` and an empty
buffer, `y`'s slots, select, flags and want are unchanged and its buffer stays empty. -/
theorem want_frozenB (x : EngB) (y : Lane) (hn : ¬Hit y x.e)
    (hr : ¬(x.e.st = .wb ∧ y = x.e.cur ∧ P.ret x.e.now x.e.cur = true)) (hb : x.buf y = false) :
    (stepB P win usb sreq x).e.wantFetch y = x.e.wantFetch y ∧
      (stepB P win usb sreq x).e.sel y = x.e.sel y ∧
      (∀ s, (stepB P win usb sreq x).e.actv y s = x.e.actv y s) ∧
      (∀ s, (stepB P win usb sreq x).e.npf y s = x.e.npf y s) ∧
      (stepB P win usb sreq x).buf y = false := by
  have hcap := capTo_of_noHit x y hn
  have hcb := capBuf_of_noHit x y hn
  have hload : ∀ s, loadTo x y s = false := fun s => by
    unfold loadTo
    simp [hb]
  have hact : ∀ s, actvB P x y s = x.e.actv y s := fun s => by
    unfold actvB
    rw [if_neg (fun h' => hr ⟨h'.1, h'.2.1, h'.2.2.2⟩)]
    simp [hcap s, hload s]
  have hnpf : ∀ s, npfB P x y s = x.e.npf y s := fun s => by
    unfold npfB
    simp [hcap s, hload s]
  have hsel : selNext P x.e y = x.e.sel y := by
    unfold selNext
    rw [if_neg hr]
  have hbuf : bufB x y = false := by
    unfold bufB
    simp [hcb, hb]
  refine ⟨?_, hsel, hact, hnpf, hbuf⟩
  show (!actvB P x y (selNext P x.e y) ||
        (!actvB P x y (!selNext P x.e y) && !npfB P x y (selNext P x.e y))) = x.e.wantFetch y
  rw [hsel, hact, hact, hnpf]
  rfl

theorem runB_succ'' : ∀ (n : Nat) (x : EngB),
    runB P win usb sreq (n + 1) x = stepB P win usb sreq (runB P win usb sreq n x)
  | 0, _ => rfl
  | n + 1, x => runB_succ'' n (stepB P win usb sreq x)

/-- **The hold on the buffered run.** From a cycle where `y` owes, does not want and has an empty
buffer, with no capture for `y` and no retirement of `y`, it keeps owing, not wanting, with an
empty buffer. -/
theorem npf_holdB (y : Lane) (x0 : EngB) (s : Nat)
    (ho : 1 ≤ (runB P win usb sreq s x0).e.owed y)
    (hw : (runB P win usb sreq s x0).e.wantFetch y = false)
    (hb : (runB P win usb sreq s x0).buf y = false) :
    ∀ k, (∀ i, i < k → ¬Hit y (runB P win usb sreq (s + i) x0).e ∧
        ¬((runB P win usb sreq (s + i) x0).e.st = .wb ∧ y = (runB P win usb sreq (s + i) x0).e.cur ∧
          P.ret (runB P win usb sreq (s + i) x0).e.now (runB P win usb sreq (s + i) x0).e.cur = true)) →
      1 ≤ (runB P win usb sreq (s + k) x0).e.owed y ∧
        (runB P win usb sreq (s + k) x0).e.wantFetch y = false ∧
        (runB P win usb sreq (s + k) x0).buf y = false
  | 0, _ => ⟨ho, hw, hb⟩
  | k + 1, h => by
    obtain ⟨ihk, ihw, ihb⟩ := npf_holdB y x0 s ho hw hb k (fun i hi => h i (by omega))
    obtain ⟨hnh, hnr⟩ := h k (Nat.lt_succ_self k)
    obtain ⟨hw', _hsel, hact, _hnpf, hb'⟩ := want_frozenB P win usb sreq _ y hnh hnr ihb
    have hrun : runB P win usb sreq (s + (k + 1)) x0
        = stepB P win usb sreq (runB P win usb sreq (s + k) x0) := by
      show runB P win usb sreq ((s + k) + 1) x0 = _
      exact runB_succ'' P win usb sreq (s + k) x0
    rw [hrun]
    refine ⟨?_, by rw [hw']; exact ihw, hb'⟩
    unfold Engine.owed at ihk ⊢
    rw [hact, hact]
    exact ihk

/-- **The unlock on the buffered run.** A retirement of `y` from the hold, with no capture for
`y` and an empty buffer, empties its head: the lane wants from the next cycle, its buffer still
empty (so the masked port, `wantM`, wants it too), and the word that retired was the no-prefetch
head. -/
theorem npf_unlockB (x : EngB) (y : Lane) (ho : 1 ≤ x.e.owed y) (hw : x.e.wantFetch y = false)
    (hn : ¬Hit y x.e) (hb : x.buf y = false)
    (hr : x.e.st = .wb ∧ y = x.e.cur ∧ P.ret x.e.now x.e.cur = true) :
    (stepB P win usb sreq x).e.wantFetch y = true ∧ (stepB P win usb sreq x).buf y = false ∧
      x.e.npf y (x.e.sel y) = true := by
  obtain ⟨_hv, hsp, hnpf⟩ := npf_state x.e y ho hw
  have hcap := capTo_of_noHit x y hn
  have hcb := capBuf_of_noHit x y hn
  have hload : ∀ s, loadTo x y s = false := fun s => by
    unfold loadTo
    simp [hb]
  have hbuf : bufB x y = false := by
    unfold bufB
    simp [hcb, hb]
  refine ⟨?_, hbuf, hnpf⟩
  have hsel : selNext P x.e y = !x.e.sel y := by
    unfold selNext
    rw [if_pos hr]
  have hhead : actvB P x y (selNext P x.e y) = false := by
    rw [hsel]
    unfold actvB
    rw [if_neg (fun h' => by
      have := h'.2.2.1
      rw [← hr.2.1] at this
      cases hs : x.e.sel y <;> rw [hs] at this <;> cases this)]
    simp [hcap, hload]
    unfold Engine.spareValid at hsp
    exact hsp
  show (!actvB P x y (selNext P x.e y) ||
        (!actvB P x y (!selNext P x.e y) && !npfB P x y (selNext P x.e y))) = true
  rw [hhead]
  rfl

end

#print axioms held_le_one
#print axioms want_frozenB
#print axioms npf_holdB
#print axioms npf_unlockB

end JLane

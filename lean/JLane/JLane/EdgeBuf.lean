import JLane.OrderK
/-!
# Brick K3b — the edge word is never in the buffer at an edge (Wilson 11-22, K3's buffer clause)

At a FALLTHROUGH edge on lane `y` whose kept word is the lane's oldest unretired word (K3(a),
`KeepOk` / `hkeep`: the kept index is the retirement count `nr`), the edge word is **never in the
buffer**: a buffered word sits behind a valid head (`WfB.bh`), and its fetch index is
`nr + nslots` (`OrdBK.o3`), so at least `nr + 1`. With the edge word present (`hasEdge`, K1's
premise) it is therefore **held in a slot or arriving in this cycle's capture** -- never absent,
never buffered.

* `oldest_not_buffered` -- on any well-formed, ordered state: the word with index `nr` is not in
  the buffer;
* `edge_word_not_buffered_runBK` -- at a cycle `f` of the flush run with `hkeep`;
* `edge_word_held_runBK` -- with the edge word present at `f`: in the head or spare, or arriving.

**Scope (stated exactly).** The premises are the run's from a primed start (`WfBK X0`, `OrdBK X0`,
the flush conditions before `f`) and K3(a)'s `hkeep` at `f`. Pre-prime captures are **not** covered:
the model starts primed (`State.lean`). The order is BufEng's: the edge word is the ARM's FIRST
slot fetch (`Buf.lean`), so it is the oldest unretired word at the edge. K12's order (the timeout
word first, then the edge word, and the RTL's no-swap / filing / load rules) is NOT this model: it
is owed as its own step (11-22).

**Measured, not proved (agent 1, 11-22).** The two cases outside the proof -- pre-prime captures
and K12's timeout-first order -- were measured on the RTL: 2,461 runs (a 1,570-run sweep over 10
images, idle / busy ports, two FT lanes; and an 891-run start-up probe over 11 images, the FT ARM
captured before priming, the edge swept from first arming -40 to +40). The edge word was in the
buffer at the edge 0 times and absent 0 times (kept in a slot 1,326, arriving in the edge's own
capture 18). Under the start-up order the edge word WAS buffered first (330 tag moves) and always
loaded into the spare before the lane armed, so before any edge. That is evidence for those cases,
not this lemma: their proof waits on the K12 model.

Must-fire `M_LEAN_EDGE_BUFFERED` (gate_lean_build): a planted step that leaves the edge word in the
buffer (the load never happens, the buffer never clears) -- the invariants this lemma rests on no
longer build, so the Lean gate goes red.
-/
namespace JLane

theorem base_bsq (X : EngBK) : X.base.bsq = X.x.bsq := by
  unfold EngBK.base; split <;> rfl

/-- **The oldest unretired word is never buffered**: on a well-formed, ordered state, the word
with fetch index `nr` is not in `y`'s buffer. -/
theorem oldest_not_buffered (X : EngBK) (hW : WfBK X) (hO : OrdBK X) (y : Lane) (kk : Nat)
    (hk : kk = X.x.nr y) : X.base.inBuf y kk = false := by
  unfold EngB.inBuf
  rw [base_buf, base_bsq]
  cases hb : X.x.buf y with
  | false => rfl
  | true =>
    have hbase : X.base.buf y = true := by rw [base_buf]; exact hb
    have hv := hW.wf.bh y hbase
    rw [base_e] at hv
    have h3 := hO.o3 y hb
    have hn : 1 ≤ nslots X.x.e y := by
      rw [nslots_hs, hv]
      exact Nat.le_add_right _ _
    have hne : X.x.bsq y ≠ kk := by
      rw [h3, hk]
      omega
    simp [hne]

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- **The edge word is not in the buffer at an edge** of the flush run, the kept word being the
lane's oldest unretired word (K3(a)). -/
theorem edge_word_not_buffered_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool)
    (k : Nat → Lane → Nat) (X0 : EngBK) (hI : WfBK X0) (hO : OrdBK X0) (y : Lane) (f : Nat)
    (hF : ∀ j, j < f → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hkeep : k (runBK P win usb sreq fl k f X0).x.e.now y = (runBK P win usb sreq fl k f X0).x.nr y) :
    (runBK P win usb sreq fl k f X0).base.inBuf y (k (runBK P win usb sreq fl k f X0).x.e.now y)
      = false :=
  oldest_not_buffered _ (wfBK_run P win usb sreq hok fl k f X0 hI hF)
    (ordBK_run P win usb sreq hok fl k f X0 hI hO hF) y _ hkeep

/-- **K3's buffer clause**: at an edge `f`, the edge word present, it is held in the head or the
spare, or arriving in this cycle's capture -- never in the buffer. (No premise that `y` is flushed
at `f`: it holds at every cycle with `hkeep`, the edge in particular.) -/
theorem edge_word_held_runBK (hok : SReqB P sreq) (fl : Nat → Lane → Bool)
    (k : Nat → Lane → Nat) (X0 : EngBK) (hI : WfBK X0) (hO : OrdBK X0) (y : Lane) (f : Nat)
    (hF : ∀ j, j < f → FlushOk P win usb sreq (fl (runBK P win usb sreq fl k j X0).x.e.now)
      (runBK P win usb sreq fl k j X0))
    (hkeep : k (runBK P win usb sreq fl k f X0).x.e.now y = (runBK P win usb sreq fl k f X0).x.nr y)
    (hE : (runBK P win usb sreq fl k f X0).base.hasEdge y
      (k (runBK P win usb sreq fl k f X0).x.e.now y) = true) :
    (runBK P win usb sreq fl k f X0).base.inSlot y
        (k (runBK P win usb sreq fl k f X0).x.e.now y) true = true ∨
      (runBK P win usb sreq fl k f X0).base.inSlot y
        (k (runBK P win usb sreq fl k f X0).x.e.now y) false = true ∨
      (runBK P win usb sreq fl k f X0).base.inCap y
        (k (runBK P win usb sreq fl k f X0).x.e.now y) = true := by
  have hnb := edge_word_not_buffered_runBK P win usb sreq hok fl k X0 hI hO y f hF hkeep
  unfold EngB.hasEdge at hE
  rw [hnb, Bool.or_false] at hE
  simpa [Bool.or_eq_true, or_assoc] using hE

end

end JLane

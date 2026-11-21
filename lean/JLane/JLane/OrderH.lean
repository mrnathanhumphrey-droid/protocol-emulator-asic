import JLane.OrderK
/-!
# Brick K6c — the keep premise from the head (Nate 11-20, option 1: order and keep together)

`OrderK.keep_at_hit` reduces the keep premise to one premise per arming, `hidxA`: the kept
index is the lane's retirement count at the arming plus one. Stated so, it is a fact about the
run's input `kt` and the retirement count. Here it is proved from a premise on the engine's own
state at the arming, `hidxH`: **the kept index is the head's fetch index plus one** -- the word
fetched immediately after the ARM (K7: one fetch pointer per lane, consecutive indices; the
edge-first order: the edge word is that word). This is the hardware's part: the flush keeps the
word fetched right after the ARM.

The head's index is `nr` by fetch order (`OrdBK.o1`), so at an arming `t₀` the ARM's head index
is `nr` and `hidxH` gives `hidxA`. (First built as a strong induction because fetch order once
needed the keep premise at every earlier cycle; since the flush writes the kept word's index as
the lane's next position (FlushKill, Wilson 11-20 K6), `ordBK_run` needs only `FlushOk`, and the
induction in `hidxA_of_head` no longer uses its hypothesis.)

Proved:
* `keep_at_hit_lt` / `keepOk_runBK_lt` -- `keep_at_hit` / `keepOk_runBK` with `hidxA` asked only
  at armings before the cycle;
* `hidxA_of_head` / `hidxA_runBA` -- `hidxA` from `hidxH` (with fetch order at the start);
* `ready_ft_edge_head` -- `OrderK.ready_ft_edge_armed` on `hidxH` instead of `hidxA`.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane) (isArm : EngB → Bool) (edge : Nat → Lane → Nat)
  (kt : Nat → Lane → Nat) (A0 : EngBA)

/-- `keep_at_hit` with `hidxA` asked only at armings before the hit. -/
theorem keep_at_hit_lt (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : ∀ l, A0.armed l = false) (n : Nat) (y : Lane)
    (hidxA : ∀ t0, t0 < n → (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1)
    (hh : (runBA P win usb sreq isArm edge kt n A0).hit y = true) :
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
  rw [hnow, hae, hidxA t0 ht0 harm, h2, h1]

/-- `keepOk_runBK` at cycle `j`, with `hidxA` asked only at armings before `j`. -/
theorem keepOk_runBK_lt (hedge : ∀ t l, t + 1 ≤ edge t l) (hA : ArmInvB A0)
    (h0 : ∀ l, A0.armed l = false) (j : Nat)
    (hidxA : ∀ t0 y, t0 < j → (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1) :
    KeepOk P (flS P win usb sreq isArm edge kt A0
        (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt j A0.X).x.e.now)
      (kt (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt j A0.X).x.e.now)
      (runBK P (winS P win usb sreq isArm edge kt A0) usb sreq
          (flS P win usb sreq isArm edge kt A0) kt j A0.X) := by
  rw [← runBA_proj P win usb sreq isArm edge kt A0 j]
  have hn := now_runBA P win usb sreq isArm edge kt A0 j
  have hfl : flS P win usb sreq isArm edge kt A0
      (runBA P win usb sreq isArm edge kt j A0).X.x.e.now
      = (runBA P win usb sreq isArm edge kt j A0).hit := by
    funext l
    simp only [flS, hn, Nat.add_sub_cancel_left]
  rw [hfl]
  intro y hh
  obtain ⟨hk, hnr⟩ := keep_at_hit_lt P win usb sreq isArm edge kt A0 hedge hA h0 j y
    (fun t0 ht harm => hidxA t0 y ht harm) hh
  rw [hnr]
  exact hk

/-- **`hidxA` from the head** (order and keep together, by strong induction on the arming
time). `hidxH`: at each arming the kept index is the ARM's (the head's) fetch index plus one. -/
theorem hidxA_of_head (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (hI : WfBK A0.X) (hO : OrdBK A0.X) (hA : ArmInvB A0) (h0 : ∀ l, A0.armed l = false)
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0))
    (hidxH : ∀ t0 y, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.sq y
            ((runBA P win usb sreq isArm edge kt t0 A0).X.x.e.sel y) + 1) :
    ∀ n t0 y, t0 < n → (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1
  | 0, _, _, ht, _ => absurd ht (Nat.not_lt_zero _)
  | n + 1, t0, y, ht, harm => by
    rcases Nat.lt_or_ge t0 n with hlt | hge
    · exact hidxA_of_head hok hedge hI hO hA h0 hscan hidxH n t0 y hlt harm
    · have e : t0 = n := by omega
      -- fetch order at t0: the keep premise at every earlier cycle, from hidxA before n
      have hO' : OrdBK (runBA P win usb sreq isArm edge kt t0 A0).X := by
        rw [runBA_proj P win usb sreq isArm edge kt A0 t0]
        exact ordBK_run P (winS P win usb sreq isArm edge kt A0) usb sreq hok
          (flS P win usb sreq isArm edge kt A0) kt t0 A0.X hI hO
          (fun j _ => flushOk_runBA P win usb sreq isArm edge kt A0 hedge hA j (hscan j))
      -- the arming writeback dispatches the ARM: y's head is valid, its index is nr
      have hW := wfBK_runBA P win usb sreq isArm edge kt A0 hok hedge hI hA hscan t0
      have harm' := harm
      unfold EngBA.arms at harm'
      simp only [Bool.and_eq_true, decide_eq_true_eq] at harm'
      obtain ⟨⟨⟨hst, hy⟩, -⟩, -⟩ := harm'
      have hd := hW.wf.disp (by rw [base_e, hst]; decide)
      rw [base_e, ← hy] at hd
      rw [hidxH t0 y harm, hO'.o1 y hd]

theorem hidxA_runBA (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (hI : WfBK A0.X) (hO : OrdBK A0.X) (hA : ArmInvB A0) (h0 : ∀ l, A0.armed l = false)
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0))
    (hidxH : ∀ t0 y, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.sq y
            ((runBA P win usb sreq isArm edge kt t0 A0).X.x.e.sel y) + 1)
    (t0 : Nat) (y : Lane) (harm : (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true) :
    kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
      = (runBA P win usb sreq isArm edge kt t0 A0).X.x.nr y + 1 :=
  hidxA_of_head P win usb sreq isArm edge kt A0 hok hedge hI hO hA h0 hscan hidxH (t0 + 1) t0 y
    (Nat.lt_succ_self _) harm

/-- **`ready_ft_edge_armed` on the head premise.** As `OrderK.ready_ft_edge_armed`, with `hidxA`
replaced by `hidxH`: at each arming, the flush keeps the word fetched right after the ARM. -/
theorem ready_ft_edge_head (hok : SReqB P sreq) (hedge : ∀ t l, t + 1 ≤ edge t l)
    (hI : WfBK A0.X) (hO : OrdBK A0.X) (hA : ArmInvB A0) (h0 : ∀ l, A0.armed l = false)
    (hscan : ∀ n, ScanOk P win usb sreq (runBA P win usb sreq isArm edge kt n A0))
    (hidxH : ∀ t0 y, (runBA P win usb sreq isArm edge kt t0 A0).arms P isArm y = true →
      kt (edge (runBA P win usb sreq isArm edge kt t0 A0).X.x.e.now y) y
        = (runBA P win usb sreq isArm edge kt t0 A0).X.x.sq y
            ((runBA P win usb sreq isArm edge kt t0 A0).X.x.e.sel y) + 1)
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
  ready_ft_edge_armed P win usb sreq isArm edge kt A0 hok hedge hI hO hA h0 hscan
    (hidxA_runBA P win usb sreq isArm edge kt A0 hok hedge hI hO hA h0 hscan hidxH) y f hfl hv

end

#print axioms keep_at_hit_lt
#print axioms keepOk_runBK_lt
#print axioms hidxA_of_head
#print axioms hidxA_runBA
#print axioms ready_ft_edge_head

end JLane

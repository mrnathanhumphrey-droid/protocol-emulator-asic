import JLane.BufEng
/-!
# Brick K12a — a second fetch never lands on an empty lane (11-22, the K12 model's premise 5)

A slot fetch issued while the lane's spare is full is a *second fetch* (`pb`): BufEng files it at
its capture into the first free place, head first (`capSlot`); the RTL never files into the head
(agent 1, 11-22: the spare if empty, else the buffer). The two agree unless the second fetch lands
with BOTH of the lane's slots empty -- and that never happens:

* it is issued only with both slots full (`SReqB`: the head valid; `pbNext`: the spare valid);
* between the issue and the capture (REQ, WAIT, then CAP) the lane retires at most once -- a
  writeback is followed by an idle cycle -- and one retirement moves the spare into the head.

`SecB` carries that through the three port states, the dispatch state standing in for "no second
retirement yet"; `secB_step` / `secB_run` keep it; `second_head_valid` reads the head valid at the
capture, so `capSlot` never takes its head branch for a second fetch (`capSlot_second`).

Scope: BufEng's engine (`stepB` / `runB`). On the flush run a flushed lane's in-flight capture is
killed (FlushKill K5), so the case does not arise there either; that lift is not written here.
-/
namespace JLane

/-- The second-fetch invariant, by port state, for the lane the port serves. -/
def SecB (x : EngB) : Prop :=
  x.pb = true →
    (x.e.pst = .req → x.e.headValid x.e.pl = true ∧
      (x.e.spareValid x.e.pl = true ∨ x.e.st = .idle)) ∧
    (x.e.pst = .wait → x.e.headValid x.e.pl = true ∧
      (x.e.spareValid x.e.pl = true ∨ x.e.st ≠ .wb)) ∧
    (x.e.pst = .cap → x.e.headValid x.e.pl = true)

theorem dispNext_wb (win : Engine → Option Lane) (e : Engine) (h : e.st = .wb) :
    (dispNext win e).st = .idle := by
  unfold dispNext; rw [h]

theorem dispNext_not_wb (win : Engine → Option Lane) (e : Engine) (h : e.st ≠ .drive) :
    (dispNext win e).st ≠ .wb := by
  unfold dispNext
  cases hs : e.st with
  | idle =>
    cases hw : win e with
    | none => simp
    | some w => by_cases hv : e.headValid w = true <;> simp [hv]
  | drive => exact absurd hs h
  | wb => simp

theorem selNext_noret (P : Program) (e : Engine) (l : Lane)
    (h : ¬(e.st = .wb ∧ l = e.cur ∧ P.ret e.now e.cur = true)) : selNext P e l = e.sel l := by
  unfold selNext; rw [if_neg h]

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : EngB → Option Lane)

/-- Without a retirement of `l`, a valid slot stays valid and the select stays. -/
theorem slot_keep_noret (x : EngB) (l : Lane) (s : Slot)
    (hn : ¬(x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true))
    (h : x.e.actv l s = true) : actvB P x l s = true :=
  actvB_of_true P x l s (fun h' => hn ⟨h'.1, h'.2.1, h'.2.2.2⟩) h

/-- Without a retirement, a lane's valid head stays valid. -/
theorem head_keep_noret (x : EngB) (l : Lane)
    (hn : ¬(x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true))
    (h : x.e.headValid l = true) : (stepB P win usb sreq x).e.headValid l = true := by
  show actvB P x l (selNext P x.e l) = true
  rw [selNext_noret P x.e l hn]
  exact slot_keep_noret P x l _ hn h

/-- Without a retirement, a lane's valid spare stays valid. -/
theorem spare_keep_noret (x : EngB) (l : Lane)
    (hn : ¬(x.e.st = .wb ∧ l = x.e.cur ∧ P.ret x.e.now x.e.cur = true))
    (h : x.e.spareValid l = true) : (stepB P win usb sreq x).e.spareValid l = true := by
  show actvB P x l (!selNext P x.e l) = true
  rw [selNext_noret P x.e l hn]
  exact slot_keep_noret P x l _ hn h

/-- Both slots valid: the head is valid next cycle, retirement or not. -/
theorem head_next_of_both (x : EngB) (l : Lane) (hh : x.e.headValid l = true)
    (hs : x.e.spareValid l = true) : (stepB P win usb sreq x).e.headValid l = true :=
  head_of_both P x l hh hs

/-- **`SecB` survives a cycle.** -/
theorem secB_step (hok : SReqB P sreq) (x : EngB) (hS : SecB x) :
    SecB (stepB P win usb sreq x) := by
  unfold SecB at hS ⊢
  intro hpb
  have hst : (stepB P win usb sreq x).e.st = (dispNext win x.e).st := rfl
  cases hp : x.e.pst with
  | scan =>
    -- a fresh issue: only the slot's branch sets `pb`, for a lane with both slots full
    cases hu : usbFirst P usb x.e with
    | true =>
      have := (portNextB_usb P usb sreq x hp hu).2
      rw [stepB_pb, this] at hpb; cases hpb
    | false =>
      cases hs : sreq x with
      | none =>
        have := (portNextB_none P usb sreq x hp hu hs).2
        rw [stepB_pb, this] at hpb; cases hpb
      | some w =>
        obtain ⟨h1, h2⟩ := portNextB_slot P usb sreq x hp hu hs
        rw [stepB_pb, h2] at hpb
        obtain ⟨_, hv, _, _⟩ := hok x w hs
        have hpl : (stepB P win usb sreq x).e.pl = w := by rw [stepB_pl, h1]
        have hps : (stepB P win usb sreq x).e.pst = .req := by rw [stepB_pst, h1]
        refine ⟨?_, ?_, ?_⟩
        · intro _
          rw [hpl]
          refine ⟨head_next_of_both P win usb sreq x w hv hpb, ?_⟩
          by_cases hr : x.e.st = .wb ∧ w = x.e.cur ∧ P.ret x.e.now x.e.cur = true
          · right; rw [hst]; exact dispNext_wb win x.e hr.1
          · left; exact spare_keep_noret P win usb sreq x w hr hpb
        · intro h; rw [hps] at h; cases h
        · intro h; rw [hps] at h; cases h
  | req =>
    have hk := portNextB_keeps P usb sreq x (by rw [hp]; decide)
    have hpb0 : x.pb = true := by rw [stepB_pb, hk.2.2] at hpb; exact hpb
    obtain ⟨hv, hor⟩ := (hS hpb0).1 hp
    have hps : (stepB P win usb sreq x).e.pst = .wait := by
      rw [stepB_pst, (portNextB_of_ne P usb sreq x (by rw [hp]; decide)).1]
      simp [portNext, hp]
    have hpl : (stepB P win usb sreq x).e.pl = x.e.pl := by rw [stepB_pl, hk.1]
    refine ⟨?_, ?_, ?_⟩
    · intro h; rw [hps] at h; cases h
    · intro _
      rw [hpl]
      rcases hor with hsv | hid
      · refine ⟨head_next_of_both P win usb sreq x _ hv hsv, ?_⟩
        by_cases hr : x.e.st = .wb ∧ x.e.pl = x.e.cur ∧ P.ret x.e.now x.e.cur = true
        · right; rw [hst, dispNext_wb win x.e hr.1]; decide
        · left; exact spare_keep_noret P win usb sreq x _ hr hsv
      · have hn : ¬(x.e.st = .wb ∧ x.e.pl = x.e.cur ∧ P.ret x.e.now x.e.cur = true) := by
          rintro ⟨h, -⟩; rw [hid] at h; cases h
        refine ⟨head_keep_noret P win usb sreq x _ hn hv, Or.inr ?_⟩
        rw [hst]
        exact dispNext_not_wb win x.e (by rw [hid]; decide)
    · intro h; rw [hps] at h; cases h
  | wait =>
    have hk := portNextB_keeps P usb sreq x (by rw [hp]; decide)
    have hpb0 : x.pb = true := by rw [stepB_pb, hk.2.2] at hpb; exact hpb
    obtain ⟨hv, hor⟩ := (hS hpb0).2.1 hp
    have hps : (stepB P win usb sreq x).e.pst = .cap := by
      rw [stepB_pst, (portNextB_of_ne P usb sreq x (by rw [hp]; decide)).1]
      simp [portNext, hp]
    have hpl : (stepB P win usb sreq x).e.pl = x.e.pl := by rw [stepB_pl, hk.1]
    refine ⟨?_, ?_, ?_⟩
    · intro h; rw [hps] at h; cases h
    · intro h; rw [hps] at h; cases h
    · intro _
      rw [hpl]
      rcases hor with hsv | hnw
      · exact head_next_of_both P win usb sreq x _ hv hsv
      · exact head_keep_noret P win usb sreq x _ (fun h => hnw h.1) hv
  | cap =>
    have hps : (stepB P win usb sreq x).e.pst = .scan := by
      rw [stepB_pst]; exact cap_to_scan P usb sreq x hp
    refine ⟨?_, ?_, ?_⟩ <;> intro h <;> rw [hps] at h <;> cases h

theorem secB_run (hok : SReqB P sreq) :
    ∀ (n : Nat) (x : EngB), SecB x → SecB (runB P win usb sreq n x)
  | 0, _, h => h
  | n + 1, x, h => secB_run hok n (stepB P win usb sreq x) (secB_step P win usb sreq hok x h)

/-- **A second fetch lands on a lane whose head is valid.** -/
theorem second_head_valid (x : EngB) (hS : SecB x) (hc : x.e.pst = .cap) (hpb : x.pb = true) :
    x.e.headValid x.e.pl = true :=
  (hS hpb).2.2 hc

/-- So BufEng's filing of a second fetch is the RTL's: never the head -- the spare if empty, else
the buffer. -/
theorem capSlot_second (x : EngB) (hS : SecB x) (hc : x.e.pst = .cap) (hpb : x.pb = true) :
    capSlot x.e x.e.pl = (if x.e.spareValid x.e.pl = false then some (!x.e.sel x.e.pl) else none) := by
  unfold capSlot
  rw [second_head_valid x hS hc hpb]
  rfl

end

end JLane

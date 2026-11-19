import JLane.Port
import JLane.OptRun
/-!
# Brick S — the guaranteed slot (Wilson 11-16: one requester, one buffer; 1b and F1)

The slot fetches an ARM-headed lane's next word **while the ARM is the head**, through the port,
at a priority the port grants at its scan: **USB receive's branch-1 refill first** (the USB lane
takes no charge from the slot: Wilson 11-16, w30's 1-cycle arming margin), then the slot, then
the other lanes' branch-1 refills, then the round robin.

The requester is abstract (`sreq : Engine → Option Lane`) with a contract (`SReqOK`): it names a
live lane whose head is valid (the ARM) and which wants a fetch, so the slot fills that lane's
spare (`fetchSlot` with a valid head). A slot issue moves the port exactly as a branch-1 issue
does (`pbr1 := true`: the round-robin pointer is not moved).

Proved here:
* `stepS_*` -- only the port's registers differ from `step`; `struct_stepS` -- the structural
  invariant holds under the slot;
* `chargeS` / `chargeS_le` -- **the per-victim charge**: a scan issue for a lane other than `y`
  (USB receive's branch 1, the slot, another lane's branch 1) costs `y` at most `L_REFILL`; an
  issue for `y` itself costs it nothing (it is `y`'s own fetch: `Hit y` at its CAP);
* `phi_stepS`, `port_waitS`, `port_wait_boundS` -- **the port wait bound under the slot**: a live
  lane owing a slot reaches `P_CAP` within 22 cycles plus `L_REFILL` per issue for another
  lane, the slot's issues included -- `Port.port_wait_bound` with the slot's term;
* `slot_waitS` -- **the slot's delay behind USB receive**: a slot request held from a cycle on
  is issued within `3 + L_REFILL · u` cycles, `u` the USB receive branch-1 issues meanwhile.

P1b from the fill (later in this file): `p1b_capture` (raise at capture, issued at the next
scan: the word valid at c + 5, margin `P1B_MARGIN_SCAN` = 0) and `p1b_direct` (issued at the
capture itself, P_CAP -> P_REQ: valid at c + 4, margin `P1B_MARGIN_DIRECT` = 1), both for an ARM
captured into its lane's empty head; the spare case needs the buffer word.

Owed (next bricks, named): `slot_once` (between two slot issues for a lane, it retires: one
fetch per ARM), the buffer at depth 2 (a third word per lane), and threading `stepS` through the
head-valid theorems that read `chargeSum` (they take `hB` on the charge; with `chargeSumS` the
slot's term enters `hB`).
-/
namespace JLane

/-- This scan serves USB receive's branch-1 refill (`usb` = the USB receive lane when live). -/
def usbFirst (P : Program) (usb : Option Lane) (e : Engine) : Bool :=
  match br1 P e, usb with
  | some w, some u => decide (w = u)
  | _, _ => false

/-- The requester's contract: a named lane is live, its head valid (the ARM), and it wants a
fetch -- so the slot fills its spare. -/
def SReqOK (P : Program) (sreq : Engine → Option Lane) : Prop :=
  ∀ e w, sreq e = some w → P.live w = true ∧ e.headValid w = true ∧ e.wantFetch w = true

/-- The port with the slot: at a scan, USB receive's branch 1, else the slot, else `portNext`. -/
def portNextS (P : Program) (usb : Option Lane) (sreq : Engine → Option Lane) (e : Engine) :
    Port :=
  match e.pst with
  | .scan =>
    if usbFirst P usb e = true then portNext P e
    else
      match sreq e with
      | some w => ⟨.req, w, e.prr, true, e.fetchSlot w⟩
      | none   => portNext P e
  | _ => portNext P e

/-- One cycle with the slot: `step` with the port's registers from `portNextS`. -/
def stepS (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : Engine → Option Lane) (e : Engine) : Engine :=
  let p := portNextS P usb sreq e
  { step P win e with pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot }

/-- `n` cycles with the slot. -/
def runS (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : Engine → Option Lane) : Nat → Engine → Engine
  | 0, e => e
  | n + 1, e => runS P win usb sreq n (stepS P win usb sreq e)

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : Engine → Option Lane)

theorem portOf_stepS (e : Engine) : portOf (stepS P win usb sreq e) = portNextS P usb sreq e :=
  rfl

theorem stepS_actv (e : Engine) : (stepS P win usb sreq e).actv = (step P win e).actv := rfl
theorem stepS_sel (e : Engine) : (stepS P win usb sreq e).sel = (step P win e).sel := rfl
theorem stepS_npf (e : Engine) : (stepS P win usb sreq e).npf = (step P win e).npf := rfl
theorem stepS_st (e : Engine) : (stepS P win usb sreq e).st = (step P win e).st := rfl
theorem stepS_cur (e : Engine) : (stepS P win usb sreq e).cur = (step P win e).cur := rfl

theorem stepS_want (e : Engine) (l : Lane) :
    (stepS P win usb sreq e).wantFetch l = (step P win e).wantFetch l := rfl

theorem stepS_headValid (e : Engine) (l : Lane) :
    (stepS P win usb sreq e).headValid l = (step P win e).headValid l := rfl

/-- Away from a scan, the slot's port is the shipped port. -/
theorem portNextS_of_ne (e : Engine) (h : e.pst ≠ .scan) :
    portNextS P usb sreq e = portNext P e := by
  unfold portNextS
  cases hp : e.pst with
  | scan => exact absurd hp h
  | req => rfl
  | wait => rfl
  | cap => rfl

/-- A scan serving USB receive's branch 1 is the shipped port. -/
theorem portNextS_usb (e : Engine) (hp : e.pst = .scan) (hu : usbFirst P usb e = true) :
    portNextS P usb sreq e = portNext P e := by
  unfold portNextS
  rw [hp]
  simp [hu]

/-- A scan with no USB receive refill and no slot request is the shipped port. -/
theorem portNextS_none (e : Engine) (hp : e.pst = .scan) (hu : usbFirst P usb e = false)
    (hs : sreq e = none) : portNextS P usb sreq e = portNext P e := by
  unfold portNextS
  rw [hp]
  simp [hu, hs]

/-- A slot issue. -/
theorem portNextS_slot (e : Engine) (hp : e.pst = .scan) (hu : usbFirst P usb e = false)
    {w : Lane} (hs : sreq e = some w) :
    portNextS P usb sreq e = ⟨.req, w, e.prr, true, e.fetchSlot w⟩ := by
  unfold portNextS
  rw [hp]
  simp [hu, hs]

/-! ### The structural invariant under the slot -/

theorem inFlightEmpty_stepS (hok : SReqOK P sreq) (e : Engine) (h1 : InFlightEmpty e) :
    InFlightEmpty (stepS P win usb sreq e) := by
  unfold InFlightEmpty at h1 ⊢
  intro hne
  change (portNextS P usb sreq e).pst ≠ .scan at hne
  show actvNext P e (portNextS P usb sreq e).pl (portNextS P usb sreq e).pslot = false
  by_cases hp : e.pst = .scan
  · by_cases hu : usbFirst P usb e = true
    · rw [portNextS_usb P usb sreq e hp hu] at hne ⊢
      exact actvNext_false P e _ _ (by rw [hp]; decide) (scan_issue_empty P e hp hne)
    · have hu' : usbFirst P usb e = false := by simpa using hu
      cases hs : sreq e with
      | none =>
        rw [portNextS_none P usb sreq e hp hu' hs] at hne ⊢
        exact actvNext_false P e _ _ (by rw [hp]; decide) (scan_issue_empty P e hp hne)
      | some w =>
        rw [portNextS_slot P usb sreq e hp hu' hs]
        exact actvNext_false P e _ _ (by rw [hp]; decide)
          (fetchSlot_invalid e w (hok e w hs).2.2)
  · rw [portNextS_of_ne P usb sreq e hp] at hne ⊢
    obtain ⟨hl, hs⟩ := portNext_keeps P e hp
    rw [hl, hs]
    exact actvNext_false P e _ _ (by
      intro hc
      have : (portNext P e).pst = .scan := by simp [portNext, hc]
      exact hne this) (h1 hp)

theorem dispHeadValid_stepS (e : Engine) (h2 : DispHeadValid e) :
    DispHeadValid (stepS P win usb sreq e) :=
  dispHeadValid_step P win e h2

theorem struct_stepS (hok : SReqOK P sreq) (e : Engine) (h : Struct e) :
    Struct (stepS P win usb sreq e) :=
  ⟨inFlightEmpty_stepS P win usb sreq hok e h.1, dispHeadValid_stepS P win usb sreq e h.2⟩

/-! ### The per-victim charge -/

/-- `L_REFILL` if this cycle's scan issues a fetch for a lane other than `y`: USB receive's
branch 1, the slot, or another lane's branch 1 (`Port.charge`). -/
def chargeS (y : Lane) (e : Engine) : Nat :=
  if e.pst = .scan ∧ usbFirst P usb e = false then
    match sreq e with
    | some w => if w ≠ y then L_REFILL else 0
    | none   => charge P y e
  else charge P y e

/-- Total charge over `n` cycles with the slot. -/
def chargeSumS (y : Lane) : Nat → Engine → Nat
  | 0, _ => 0
  | n + 1, e => chargeS P usb sreq y e + chargeSumS y n (stepS P win usb sreq e)

/-- **At most one refill's worth per cycle, and nothing for `y`'s own fetch.** -/
theorem chargeS_le (y : Lane) (e : Engine) : chargeS P usb sreq y e ≤ L_REFILL := by
  unfold chargeS charge
  split
  · split
    · split <;> simp
    · split
      · split <;> simp
      · simp
  · split
    · split <;> simp
    · simp

theorem chargeS_own (y : Lane) (e : Engine) (hp : e.pst = .scan)
    (hu : usbFirst P usb e = false) (hs : sreq e = some y) : chargeS P usb sreq y e = 0 := by
  unfold chargeS
  simp [hp, hu, hs]

/-! ### The port wait bound under the slot -/

theorem phi_stepS (y : Lane) (e : Engine) (hy : P.live y = true) (hw : e.wantFetch y = true)
    (hn : ¬Hit y e) :
    phi y (portOf (stepS P win usb sreq e)) + 1 ≤ phi y (portOf e) + chargeS P usb sreq y e := by
  rw [portOf_stepS]
  by_cases hp : e.pst = .scan
  · by_cases hu : usbFirst P usb e = true
    · rw [portNextS_usb P usb sreq e hp hu]
      have hc : chargeS P usb sreq y e = charge P y e := by
        unfold chargeS; rw [if_neg (fun h => by simp [h.2] at hu)]
      rw [hc, ← portOf_step P win e]
      exact phi_step P win y e hy hw hn
    · have hu' : usbFirst P usb e = false := by simpa using hu
      cases hs : sreq e with
      | none =>
        rw [portNextS_none P usb sreq e hp hu' hs]
        have hc : chargeS P usb sreq y e = charge P y e := by
          unfold chargeS; simp [hp, hu', hs]
        rw [hc, ← portOf_step P win e]
        exact phi_step P win y e hy hw hn
      | some w =>
        rw [portNextS_slot P usb sreq e hp hu' hs]
        by_cases hwy : w = y
        · simp [phi, ptr, portOf, rem, L_REFILL, hp, hwy] <;> omega
        · have hc : chargeS P usb sreq y e = L_REFILL := by
            unfold chargeS; simp [hp, hu', hs, hwy]
          simp [phi, ptr, portOf, rem, L_REFILL, hp, hwy, hc] <;> omega
  · rw [portNextS_of_ne P usb sreq e hp]
    have hc : chargeS P usb sreq y e = charge P y e := by
      unfold chargeS; rw [if_neg (fun h => hp h.1)]
    rw [hc, ← portOf_step P win e]
    exact phi_step P win y e hy hw hn

theorem want_stepS (y : Lane) (e : Engine) (hS : Struct e) (hw : e.wantFetch y = true)
    (hn : ¬Hit y e) : (stepS P win usb sreq e).wantFetch y = true := by
  rw [stepS_want]
  exact want_step P win y e hS hw hn

theorem port_waitS (hok : SReqOK P sreq) (y : Lane) (hy : P.live y = true) :
    ∀ (n : Nat) (e : Engine), Struct e → e.wantFetch y = true →
      (∀ i, i < n → ¬Hit y (runS P win usb sreq i e)) →
      phi y (portOf (runS P win usb sreq n e)) + n
        ≤ phi y (portOf e) + chargeSumS P win usb sreq y n e
  | 0, e, _, _, _ => by simp [runS, chargeSumS]
  | n + 1, e, hS, hw, hnh => by
    have h0 : ¬Hit y e := hnh 0 (Nat.succ_pos n)
    have hstep := phi_stepS P win usb sreq y e hy hw h0
    have ih := port_waitS hok y hy n (stepS P win usb sreq e)
      (struct_stepS P win usb sreq hok e hS) (want_stepS P win usb sreq y e hS hw h0)
      (fun i hi => hnh (i + 1) (Nat.succ_lt_succ hi))
    show phi y (portOf (runS P win usb sreq n (stepS P win usb sreq e))) + (n + 1)
      ≤ phi y (portOf e) + (chargeS P usb sreq y e
          + chargeSumS P win usb sreq y n (stepS P win usb sreq e))
    omega

/-- **Port wait bound under the slot.** A live lane that owes a slot reaches `P_CAP` within
22 cycles plus `L_REFILL` per fetch issued for another lane in the window -- USB receive's
branch 1, the slot's fetches for other lanes, the other lanes' branch 1 -- and nothing for its
own slot fetch. -/
theorem port_wait_boundS (hok : SReqOK P sreq) (y : Lane) (hy : P.live y = true) (n : Nat)
    (e : Engine) (hS : Struct e) (hw : e.wantFetch y = true)
    (hnh : ∀ i, i < n → ¬Hit y (runS P win usb sreq i e)) :
    n ≤ 22 + chargeSumS P win usb sreq y n e := by
  have h := port_waitS P win usb sreq hok y hy n e hS hw hnh
  have h2 := phi_le y (portOf e)
  omega

/-! ### The slot's delay behind USB receive -/

/-- A slot issue this cycle. -/
def SlotIssue (e : Engine) : Prop :=
  e.pst = .scan ∧ usbFirst P usb e = false ∧ (sreq e).isSome

/-- `L_REFILL` if this cycle's scan serves USB receive's branch 1. -/
def usbCharge (e : Engine) : Nat :=
  if e.pst = .scan ∧ usbFirst P usb e = true then L_REFILL else 0

def usbSum : Nat → Engine → Nat
  | 0, _ => 0
  | n + 1, e => usbCharge P usb e + usbSum n (stepS P win usb sreq e)

/-- **The slot waits only behind USB receive.** With a slot request at every cycle of
`[0, n)` and no slot issue in it, `n ≤ 3 + L_REFILL · (USB receive issues)`: from any port
state the scan comes within 3 cycles, and a scan that is not USB receive's issues the slot. -/
theorem slot_waitS :
    ∀ (n : Nat) (e : Engine),
      (∀ i, i < n → (sreq (runS P win usb sreq i e)).isSome = true) →
      (∀ i, i < n → ¬SlotIssue P usb sreq (runS P win usb sreq i e)) →
      n ≤ rem e.pst + usbSum P win usb sreq n e
  | 0, e, _, _ => by simp [usbSum]
  | n + 1, e, hq, hni => by
    have hq0 : (sreq e).isSome = true := hq 0 (Nat.succ_pos n)
    have hn0 : ¬SlotIssue P usb sreq e := hni 0 (Nat.succ_pos n)
    have ih := slot_waitS n (stepS P win usb sreq e)
      (fun i hi => hq (i + 1) (Nat.succ_lt_succ hi))
      (fun i hi => hni (i + 1) (Nat.succ_lt_succ hi))
    show n + 1 ≤ rem e.pst + (usbCharge P usb e + usbSum P win usb sreq n (stepS P win usb sreq e))
    have hr := rem_le (stepS P win usb sreq e).pst
    by_cases hp : e.pst = .scan
    · by_cases hu : usbFirst P usb e = true
      · have hc : usbCharge P usb e = L_REFILL := by unfold usbCharge; simp [hp, hu]
        -- USB receive's issue: the port goes to REQ (rem 3)
        have hpst : (stepS P win usb sreq e).pst = .req := by
          change (portNextS P usb sreq e).pst = .req
          rw [portNextS_usb P usb sreq e hp hu]
          unfold usbFirst at hu
          cases hb : br1 P e with
          | none => rw [hb] at hu; simp at hu
          | some w => simp [portNext, hp, hb]
        rw [hpst] at ih
        simp [rem, hc, hp, L_REFILL] at ih ⊢
        omega
      · exact absurd ⟨hp, by simpa using hu, hq0⟩ hn0
    · have hc : usbCharge P usb e = 0 := by unfold usbCharge; rw [if_neg (fun h => hp h.1)]
      have hpst : (stepS P win usb sreq e).pst = (portNext P e).pst := by
        change (portNextS P usb sreq e).pst = _
        rw [portNextS_of_ne P usb sreq e hp]
      rw [hpst] at ih
      cases hpe : e.pst with
      | scan => exact absurd hpe hp
      | req => simp [portNext, hpe, rem, hc] at ih ⊢; omega
      | wait => simp [portNext, hpe, rem, hc] at ih ⊢; omega
      | cap => simp [portNext, hpe, rem, hc] at ih ⊢; omega

/-! ### One slot fetch per ARM -/

theorem runS_succ' : ∀ (n : Nat) (e : Engine),
    runS P win usb sreq (n + 1) e = stepS P win usb sreq (runS P win usb sreq n e)
  | 0, _ => rfl
  | n + 1, e => runS_succ' n (stepS P win usb sreq e)

theorem runS_add : ∀ (a k : Nat) (e : Engine),
    runS P win usb sreq (a + k) e = runS P win usb sreq k (runS P win usb sreq a e)
  | a, 0, _ => rfl
  | a, k + 1, e => by
    rw [← Nat.add_assoc, runS_succ', runS_add a k e, ← runS_succ']

theorem keepS (u : Lane) (s : Slot) (e : Engine) (hr : ¬IsRet P u e) (h : e.actv u s = true) :
    (stepS P win usb sreq e).actv u s = true := by
  rw [stepS_actv]
  show actvNext P e u s = true
  unfold actvNext
  have hn := not_ret_form P u e hr
  rw [if_neg (fun h' => hn ⟨h'.1, h'.2.1, h'.2.2.2⟩)]
  split
  · rfl
  · exact h

theorem selS (u : Lane) (e : Engine) (hr : ¬IsRet P u e) :
    (stepS P win usb sreq e).sel u = e.sel u := by
  rw [stepS_sel]
  show selNext P e u = e.sel u
  unfold selNext
  rw [if_neg (not_ret_form P u e hr)]

theorem capFillS (u : Lane) (e : Engine) (hc : e.pst = .cap) (hl : e.pl = u)
    (hr : ¬IsRet P u e) : (stepS P win usb sreq e).actv u e.pslot = true := by
  rw [stepS_actv]
  show actvNext P e u e.pslot = true
  unfold actvNext
  have hn := not_ret_form P u e hr
  rw [if_neg (fun h' => hn ⟨h'.1, h'.2.1, h'.2.2.2⟩), if_pos ⟨hc, hl.symm, rfl⟩]

/-- **`slot_once`: one slot fetch per ARM.** Two slot issues for the same lane `u` have a
retirement of `u` between them: the first fills `u`'s spare behind its valid head (the ARM), and
until `u` retires both slots stay valid, so `u` wants no fetch and the requester cannot name it
(`SReqOK`). -/
theorem slot_once (hok : SReqOK P sreq) (u : Lane) (e1 : Engine) (n : Nat)
    (ha : SlotIssue P usb sreq e1) (hu : sreq e1 = some u)
    (hb : sreq (runS P win usb sreq n e1) = some u)
    (hbs : (runS P win usb sreq n e1).pst = .scan) (_hn : 0 < n) :
    ¬(∀ x, x < n → ¬IsRet P u (runS P win usb sreq x e1)) := by
  intro hnr
  obtain ⟨hp, hu0, _⟩ := ha
  have hv0 : e1.headValid u = true := (hok e1 u hu).2.1
  have hfs : e1.fetchSlot u = !e1.sel u := by
    unfold Engine.fetchSlot; rw [hv0]; rfl
  -- the port after the issue: REQ, WAIT, CAP on u's spare
  have h1 : runS P win usb sreq 1 e1 = stepS P win usb sreq e1 := rfl
  have hp1 : portOf (runS P win usb sreq 1 e1) = ⟨.req, u, e1.prr, true, !e1.sel u⟩ := by
    rw [h1, portOf_stepS, portNextS_slot P usb sreq e1 hp hu0 hu, hfs]
  have hpst1 : (runS P win usb sreq 1 e1).pst = .req := congrArg Port.pst hp1
  have hpl1 : (runS P win usb sreq 1 e1).pl = u := congrArg Port.pl hp1
  have hps1 : (runS P win usb sreq 1 e1).pslot = !e1.sel u := congrArg Port.pslot hp1
  have nxt : ∀ k, (runS P win usb sreq k e1).pst ≠ .scan →
      portOf (runS P win usb sreq (k + 1) e1) = portNext P (runS P win usb sreq k e1) := by
    intro k hk
    rw [runS_succ', portOf_stepS, portNextS_of_ne P usb sreq _ hk]
  have hpst2 : (runS P win usb sreq 2 e1).pst = .wait := by
    show (portOf (runS P win usb sreq (1 + 1) e1)).pst = .wait
    rw [nxt 1 (by rw [hpst1]; decide)]; simp [portNext, hpst1]
  have hkeep2 := portNext_keeps P (runS P win usb sreq 1 e1) (by rw [hpst1]; decide)
  have hpl2 : (runS P win usb sreq 2 e1).pl = u := by
    rw [show (runS P win usb sreq 2 e1).pl = (portOf (runS P win usb sreq (1 + 1) e1)).pl from rfl,
      nxt 1 (by rw [hpst1]; decide), hkeep2.1, hpl1]
  have hps2 : (runS P win usb sreq 2 e1).pslot = !e1.sel u := by
    rw [show (runS P win usb sreq 2 e1).pslot = (portOf (runS P win usb sreq (1 + 1) e1)).pslot from
      rfl, nxt 1 (by rw [hpst1]; decide), hkeep2.2, hps1]
  have hpst3 : (runS P win usb sreq 3 e1).pst = .cap := by
    show (portOf (runS P win usb sreq (2 + 1) e1)).pst = .cap
    rw [nxt 2 (by rw [hpst2]; decide)]; simp [portNext, hpst2]
  have hkeep3 := portNext_keeps P (runS P win usb sreq 2 e1) (by rw [hpst2]; decide)
  have hpl3 : (runS P win usb sreq 3 e1).pl = u := by
    rw [show (runS P win usb sreq 3 e1).pl = (portOf (runS P win usb sreq (2 + 1) e1)).pl from rfl,
      nxt 2 (by rw [hpst2]; decide), hkeep3.1, hpl2]
  have hps3 : (runS P win usb sreq 3 e1).pslot = !e1.sel u := by
    rw [show (runS P win usb sreq 3 e1).pslot = (portOf (runS P win usb sreq (2 + 1) e1)).pslot from
      rfl, nxt 2 (by rw [hpst2]; decide), hkeep3.2, hps2]
  -- the second request is at a scan, so n >= 4
  have hn4 : 4 ≤ n := by
    rcases (by omega : n = 1 ∨ n = 2 ∨ n = 3 ∨ 4 ≤ n) with h | h | h | h
    · rw [h, hpst1] at hbs; cases hbs
    · rw [h, hpst2] at hbs; cases hbs
    · rw [h, hpst3] at hbs; cases hbs
    · exact h
  -- with no retirement: the select holds, the head stays valid, the spare fills at 3
  have inv : ∀ k, k ≤ n → (runS P win usb sreq k e1).sel u = e1.sel u ∧
      (runS P win usb sreq k e1).actv u (e1.sel u) = true ∧
      (4 ≤ k → (runS P win usb sreq k e1).actv u (!e1.sel u) = true) := by
    intro k
    induction k with
    | zero => intro _; exact ⟨rfl, hv0, fun h => absurd h (by omega)⟩
    | succ k ih =>
      intro hk
      obtain ⟨hs, hh, hsp⟩ := ih (by omega)
      have hr := hnr k (by omega)
      rw [runS_succ']
      refine ⟨by rw [selS P win usb sreq u _ hr, hs], keepS P win usb sreq u _ _ hr hh, ?_⟩
      intro h4
      by_cases hk3 : k = 3
      · subst hk3
        have := capFillS P win usb sreq u _ hpst3 hpl3 hr
        rwa [hps3] at this
      · exact keepS P win usb sreq u _ _ hr (hsp (by omega))
  obtain ⟨hs, hh, hsp⟩ := inv n (Nat.le_refl n)
  have hw := (hok _ u hb).2.2
  unfold Engine.wantFetch Engine.headValid Engine.spareValid at hw
  rw [hs, hh, hsp hn4] at hw
  simp at hw


/-! ### USB receive: one branch-1 refill per retirement under the slot -/

theorem usbFirst_spec (v : Lane) (e : Engine) (h : usbFirst P (some v) e = true) :
    br1 P e = some v := by
  unfold usbFirst at h
  cases hb : br1 P e with
  | none => rw [hb] at h; simp at h
  | some w => rw [hb] at h; simp at h; rw [h]

/-- A USB receive branch-1 issue this cycle. -/
def UsbIssue (e : Engine) : Prop := e.pst = .scan ∧ usbFirst P usb e = true

instance (e : Engine) : Decidable (UsbIssue P usb e) :=
  inferInstanceAs (Decidable (e.pst = .scan ∧ usbFirst P usb e = true))

/-- **`usb_once_S`.** Under the slot, two USB receive issues have a retirement of the USB lane
between them: the first fills its empty head, which stays valid until it retires, and branch 1
needs an empty head. -/
theorem usb_once_S (v : Lane) (hv : usb = some v) (e1 : Engine) (n : Nat)
    (ha : UsbIssue P usb e1) (hb : UsbIssue P usb (runS P win usb sreq n e1)) (_hn : 0 < n) :
    ¬(∀ x, x < n → ¬IsRet P v (runS P win usb sreq x e1)) := by
  intro hnr
  subst hv
  obtain ⟨hp, hu0⟩ := ha
  have hb1 := usbFirst_spec P v e1 hu0
  have hp1 : portOf (runS P win (some v) sreq 1 e1) = ⟨.req, v, e1.prr, true, e1.sel v⟩ := by
    show portNextS P (some v) sreq e1 = _
    rw [portNextS_usb P (some v) sreq e1 hp hu0]
    simp [portNext, hp, hb1]
  have hpst1 : (runS P win (some v) sreq 1 e1).pst = .req := congrArg Port.pst hp1
  have hpl1 : (runS P win (some v) sreq 1 e1).pl = v := congrArg Port.pl hp1
  have hps1 : (runS P win (some v) sreq 1 e1).pslot = e1.sel v := congrArg Port.pslot hp1
  have nxt : ∀ k, (runS P win (some v) sreq k e1).pst ≠ .scan →
      portOf (runS P win (some v) sreq (k + 1) e1)
        = portNext P (runS P win (some v) sreq k e1) := by
    intro k hk
    rw [runS_succ', portOf_stepS, portNextS_of_ne P (some v) sreq _ hk]
  have hpst2 : (runS P win (some v) sreq 2 e1).pst = .wait := by
    show (portOf (runS P win (some v) sreq (1 + 1) e1)).pst = .wait
    rw [nxt 1 (by rw [hpst1]; decide)]; simp [portNext, hpst1]
  have hk2 := portNext_keeps P (runS P win (some v) sreq 1 e1) (by rw [hpst1]; decide)
  have hpl2 : (runS P win (some v) sreq 2 e1).pl = v := by
    rw [show (runS P win (some v) sreq 2 e1).pl
        = (portOf (runS P win (some v) sreq (1 + 1) e1)).pl from rfl,
      nxt 1 (by rw [hpst1]; decide), hk2.1, hpl1]
  have hps2 : (runS P win (some v) sreq 2 e1).pslot = e1.sel v := by
    rw [show (runS P win (some v) sreq 2 e1).pslot
        = (portOf (runS P win (some v) sreq (1 + 1) e1)).pslot from rfl,
      nxt 1 (by rw [hpst1]; decide), hk2.2, hps1]
  have hpst3 : (runS P win (some v) sreq 3 e1).pst = .cap := by
    show (portOf (runS P win (some v) sreq (2 + 1) e1)).pst = .cap
    rw [nxt 2 (by rw [hpst2]; decide)]; simp [portNext, hpst2]
  have hk3 := portNext_keeps P (runS P win (some v) sreq 2 e1) (by rw [hpst2]; decide)
  have hpl3 : (runS P win (some v) sreq 3 e1).pl = v := by
    rw [show (runS P win (some v) sreq 3 e1).pl
        = (portOf (runS P win (some v) sreq (2 + 1) e1)).pl from rfl,
      nxt 2 (by rw [hpst2]; decide), hk3.1, hpl2]
  have hps3 : (runS P win (some v) sreq 3 e1).pslot = e1.sel v := by
    rw [show (runS P win (some v) sreq 3 e1).pslot
        = (portOf (runS P win (some v) sreq (2 + 1) e1)).pslot from rfl,
      nxt 2 (by rw [hpst2]; decide), hk3.2, hps2]
  have hbs := hb.1
  have hn4 : 4 ≤ n := by
    rcases (by omega : n = 0 ∨ n = 1 ∨ n = 2 ∨ n = 3 ∨ 4 ≤ n) with h | h | h | h | h
    · omega
    · rw [h, hpst1] at hbs; cases hbs
    · rw [h, hpst2] at hbs; cases hbs
    · rw [h, hpst3] at hbs; cases hbs
    · exact h
  have inv : ∀ k, k ≤ n → (runS P win (some v) sreq k e1).sel v = e1.sel v ∧
      (4 ≤ k → (runS P win (some v) sreq k e1).actv v (e1.sel v) = true) := by
    intro k
    induction k with
    | zero => intro _; exact ⟨rfl, fun h => absurd h (by omega)⟩
    | succ k ih =>
      intro hk
      obtain ⟨hs, hh⟩ := ih (by omega)
      have hr := hnr k (by omega)
      rw [runS_succ']
      refine ⟨by rw [selS P win (some v) sreq v _ hr, hs], ?_⟩
      intro h4
      by_cases hk3 : k = 3
      · subst hk3
        have := capFillS P win (some v) sreq v _ hpst3 hpl3 hr
        rwa [hps3] at this
      · exact keepS P win (some v) sreq v _ _ hr (hh (by omega))
  obtain ⟨hs, hh⟩ := inv n (Nat.le_refl n)
  have hbr := usbFirst_spec P v _ hb.2
  have hhv := (br1_spec P _ v hbr).2
  unfold Engine.headValid at hhv
  rw [hs, hh hn4] at hhv
  cases hhv

/-! ### Counting along a slot run: one issue per retirement, plus one -/

/-- Cycles satisfying `Q` among the first `n` of the slot run. -/
def cntS (Q : Engine → Prop) [DecidablePred Q] : Nat → Engine → Nat
  | 0, _ => 0
  | n + 1, e => (if Q e then 1 else 0) + cntS Q n (stepS P win usb sreq e)

theorem cntS_add (Q : Engine → Prop) [DecidablePred Q] :
    ∀ (a k : Nat) (e : Engine),
      cntS P win usb sreq Q (a + k) e
        = cntS P win usb sreq Q a e + cntS P win usb sreq Q k (runS P win usb sreq a e)
  | 0, k, e => by
    show cntS P win usb sreq Q (0 + k) e = 0 + cntS P win usb sreq Q k e
    rw [Nat.zero_add, Nat.zero_add]
  | a + 1, k, e => by
    rw [Nat.add_right_comm]
    show (if Q e then 1 else 0) + cntS P win usb sreq Q (a + k) (stepS P win usb sreq e)
        = ((if Q e then 1 else 0) + cntS P win usb sreq Q a (stepS P win usb sreq e))
          + cntS P win usb sreq Q k (runS P win usb sreq a (stepS P win usb sreq e))
    rw [cntS_add Q a k (stepS P win usb sreq e)]
    omega

theorem cntS_reach (Q : Engine → Prop) [DecidablePred Q] :
    ∀ (n : Nat) (e : Engine) (k : Nat), k < cntS P win usb sreq Q n e →
      ∃ t, t < n ∧ cntS P win usb sreq Q t e = k ∧ Q (runS P win usb sreq t e)
  | 0, e, k, h => by simp [cntS] at h
  | n + 1, e, k, h => by
    have e1 : cntS P win usb sreq Q (n + 1) e
        = (if Q e then 1 else 0) + cntS P win usb sreq Q n (stepS P win usb sreq e) := rfl
    by_cases hq : Q e
    · rw [if_pos hq] at e1
      cases k with
      | zero => exact ⟨0, Nat.succ_pos n, rfl, hq⟩
      | succ k =>
        obtain ⟨t, ht, hc, hq'⟩ := cntS_reach Q n (stepS P win usb sreq e) k (by omega)
        have e2 : cntS P win usb sreq Q (t + 1) e
            = (if Q e then 1 else 0) + cntS P win usb sreq Q t (stepS P win usb sreq e) := rfl
        rw [if_pos hq] at e2
        exact ⟨t + 1, by omega, by omega, hq'⟩
    · rw [if_neg hq] at e1
      obtain ⟨t, ht, hc, hq'⟩ := cntS_reach Q n (stepS P win usb sreq e) k (by omega)
      have e2 : cntS P win usb sreq Q (t + 1) e
          = (if Q e then 1 else 0) + cntS P win usb sreq Q t (stepS P win usb sreq e) := rfl
      rw [if_neg hq] at e2
      exact ⟨t + 1, by omega, by omega, hq'⟩

theorem cntS_pos_of (Q : Engine → Prop) [DecidablePred Q] (e : Engine) (s t : Nat)
    (hst : s < t) (hq : Q (runS P win usb sreq s e)) : 1 ≤ cntS P win usb sreq Q t e := by
  obtain ⟨j, rfl⟩ : ∃ j, t = s + (j + 1) := ⟨t - s - 1, by omega⟩
  rw [cntS_add P win usb sreq Q s (j + 1) e]
  have h1 : cntS P win usb sreq Q (j + 1) (runS P win usb sreq s e)
      = (if Q (runS P win usb sreq s e) then 1 else 0)
        + cntS P win usb sreq Q j (stepS P win usb sreq (runS P win usb sreq s e)) := rfl
  rw [h1, if_pos hq]
  omega

/-- **One issue per retirement, plus one** -- for any issue predicate `I` whose two occurrences
always have a retirement `R` between them (`slot_once`, `usb_once_S`). -/
theorem cntS_once (I R : Engine → Prop) [DecidablePred I] [DecidablePred R] (e0 : Engine)
    (hOnce : ∀ a n, 0 < n → I (runS P win usb sreq a e0) →
      I (runS P win usb sreq (a + n) e0) →
      ¬(∀ x, x < n → ¬R (runS P win usb sreq (a + x) e0))) :
    ∀ m a, cntS P win usb sreq I m (runS P win usb sreq a e0)
      ≤ cntS P win usb sreq R m (runS P win usb sreq a e0) + 1 := by
  suffices H : ∀ N m a, m ≤ N → cntS P win usb sreq I m (runS P win usb sreq a e0)
      ≤ cntS P win usb sreq R m (runS P win usb sreq a e0) + 1 from
    fun m a => H m m a (Nat.le_refl m)
  intro N
  induction N with
  | zero =>
    intro m a hm
    have : m = 0 := by omega
    subst this
    simp [cntS]
  | succ N ih =>
    intro m a hm
    cases m with
    | zero => simp [cntS]
    | succ k =>
      have step1 : ∀ (Q : Engine → Prop) [DecidablePred Q],
          cntS P win usb sreq Q (k + 1) (runS P win usb sreq a e0)
            = (if Q (runS P win usb sreq a e0) then 1 else 0)
              + cntS P win usb sreq Q k (runS P win usb sreq (a + 1) e0) := by
        intro Q _
        rw [runS_succ']
        rfl
      rw [step1 I, step1 R]
      by_cases hia : I (runS P win usb sreq a e0)
      · rw [if_pos hia]
        rcases Nat.eq_zero_or_pos (cntS P win usb sreq I k (runS P win usb sreq (a + 1) e0))
          with h0 | hpos
        · rw [h0]; split <;> omega
        · obtain ⟨s0, hs0k, hc0, hq0⟩ :=
            cntS_reach P win usb sreq I k (runS P win usb sreq (a + 1) e0) 0 hpos
          rw [← runS_add, show a + 1 + s0 = a + (s0 + 1) by omega] at hq0
          have hret : 1 ≤ cntS P win usb sreq R (s0 + 1) (runS P win usb sreq a e0) := by
            rcases Nat.eq_zero_or_pos (cntS P win usb sreq R (s0 + 1) (runS P win usb sreq a e0))
              with hz | hp
            · exfalso
              apply hOnce a (s0 + 1) (by omega) hia hq0
              intro x hx hr
              have := cntS_pos_of P win usb sreq R (runS P win usb sreq a e0) x (s0 + 1) hx
                (by rw [← runS_add]; exact hr)
              omega
            · exact hp
          have hsplitI := cntS_add P win usb sreq I s0 (k - s0) (runS P win usb sreq (a + 1) e0)
          rw [show s0 + (k - s0) = k by omega, hc0, ← runS_add] at hsplitI
          have hsplitR := cntS_add P win usb sreq R (s0 + 1) (k - s0) (runS P win usb sreq a e0)
          rw [show s0 + 1 + (k - s0) = k + 1 by omega, ← runS_add,
            show a + (s0 + 1) = a + 1 + s0 by omega] at hsplitR
          have hih := ih (k - s0) (a + 1 + s0) (by omega)
          have eR1 := step1 R
          omega
      · rw [if_neg hia]
        have hih := ih k (a + 1) (by omega)
        split <;> omega

/-- A slot issue for lane `u`. -/
def SlotFor (u : Lane) (e : Engine) : Prop :=
  e.pst = .scan ∧ usbFirst P usb e = false ∧ sreq e = some u

instance (u : Lane) (e : Engine) : Decidable (SlotFor P usb sreq u e) :=
  inferInstanceAs (Decidable (e.pst = .scan ∧ usbFirst P usb e = false ∧ sreq e = some u))

/-- **The per-window count, the slot.** Over any `m` cycles, lane `u`'s slot fetches are at
most its retirements plus one: one fetch per ARM. -/
theorem slot_count (hok : SReqOK P sreq) (u : Lane) (e0 : Engine) (m a : Nat) :
    cntS P win usb sreq (SlotFor P usb sreq u) m (runS P win usb sreq a e0)
      ≤ cntS P win usb sreq (IsRet P u) m (runS P win usb sreq a e0) + 1 :=
  cntS_once P win usb sreq _ _ e0 (fun a n hn ha hb => by
    rw [runS_add] at hb
    have h := slot_once P win usb sreq hok u (runS P win usb sreq a e0) n
      ⟨ha.1, ha.2.1, by rw [ha.2.2]; rfl⟩ ha.2.2 hb.2.2 hb.1 hn
    intro hall
    exact h (fun x hx hr => hall x hx (by rw [runS_add]; exact hr))) m a

/-- **The per-window count, USB receive.** Over any `m` cycles, USB receive's branch-1 issues
under the slot are at most the USB lane's retirements plus one -- the count the certificate
evaluates per window (`lane_cert.br1_window_count`: one per late word). -/
theorem usb_count (v : Lane) (hv : usb = some v) (e0 : Engine) (m a : Nat) :
    cntS P win usb sreq (UsbIssue P usb) m (runS P win usb sreq a e0)
      ≤ cntS P win usb sreq (IsRet P v) m (runS P win usb sreq a e0) + 1 :=
  cntS_once P win usb sreq _ _ e0 (fun a n hn ha hb => by
    rw [runS_add] at hb
    have h := usb_once_S P win usb sreq v hv (runS P win usb sreq a e0) n ha hb hn
    intro hall
    exact h (fun x hx hr => hall x hx (by rw [runS_add]; exact hr))) m a

/-! ### The bound's constants (pinned: `proof_constants.slot_wait_base` / `slot_charge`) -/

/-- The slot's wait from any port state to its scan: the in-flight refill's remaining cycles. -/
abbrev SLOT_WAIT_BASE : Nat := L_REFILL - 1
/-- What one fetch for another lane costs a lane: one refill. -/
abbrev SLOT_CHARGE : Nat := L_REFILL

theorem slot_wait_base_val : SLOT_WAIT_BASE = 3 := rfl
theorem slot_charge_val : SLOT_CHARGE = 4 := rfl

/-- **The slot's wait, with its constants.** `n ≤ SLOT_WAIT_BASE + SLOT_CHARGE · (USB receive
issues)` (`slot_waitS`; `usbSum_eq_cnt`). -/
theorem slot_wait_bound (n : Nat) (e : Engine)
    (hq : ∀ i, i < n → (sreq (runS P win usb sreq i e)).isSome = true)
    (hni : ∀ i, i < n → ¬SlotIssue P usb sreq (runS P win usb sreq i e)) :
    n ≤ SLOT_WAIT_BASE + usbSum P win usb sreq n e := by
  have h := slot_waitS P win usb sreq n e hq hni
  have h2 := rem_le e.pst
  show n ≤ L_REFILL - 1 + _
  simp only [L_REFILL]
  omega

theorem usbSum_eq_cnt : ∀ (n : Nat) (e : Engine),
    usbSum P win usb sreq n e = SLOT_CHARGE * cntS P win usb sreq (UsbIssue P usb) n e
  | 0, _ => by simp [usbSum, cntS]
  | n + 1, e => by
    show usbCharge P usb e + usbSum P win usb sreq n (stepS P win usb sreq e)
      = SLOT_CHARGE * ((if UsbIssue P usb e then 1 else 0)
          + cntS P win usb sreq (UsbIssue P usb) n (stepS P win usb sreq e))
    rw [usbSum_eq_cnt n]
    unfold usbCharge UsbIssue
    split <;> simp [Nat.mul_add, SLOT_CHARGE]


/-! ### P1b from the fill: the requester raises at capture (Wilson 11-16)

The contract (`RaiseAtCapture`): when the port captures an ARM for lane `u` into `u`'s empty
head, the requester names `u` at the very next cycle (the scan right after the capture). With
priority below USB receive only, the slot issues there; nothing is in flight (the port has just
captured), so the fetch takes exactly `REQ → WAIT → CAP`.

`p1b_capture`, from the ARM's capture cycle `c`:
* the ARM's writeback is no earlier than `c + 3` (it needs its head valid two cycles before);
* the slot fills the ARM's spare by `c + 5`;
* that word stays valid until a retiring writeback of `u` on that very slot (its own retirement).
With ArmRetire (`arm_release_ge`: the successor is released at least 2 after the ARM's
writeback), the successor's earliest release is `c + 5`: **its head is valid at its release, with
zero slack**. The ARM captured into the spare (head already valid) needs the buffer word, the
next brick. -/

theorem stepS_st_wb (e : Engine) (h : (stepS P win usb sreq e).st = .wb) : e.st = .drive := by
  rw [stepS_st] at h
  change (dispNext win e).st = .wb at h
  unfold dispNext at h
  cases hs : e.st with
  | drive => rfl
  | wb => rw [hs] at h; simp at h
  | idle =>
    rw [hs] at h
    dsimp only at h
    cases hw : win e with
    | none => rw [hw] at h; simp at h
    | some w => rw [hw] at h; dsimp only at h; split at h <;> simp at h

theorem stepS_cur_drive (e : Engine) (h : e.st = .drive) :
    (stepS P win usb sreq e).cur = e.cur := by
  rw [stepS_cur]
  change (dispNext win e).cur = e.cur
  unfold dispNext
  rw [h]

theorem stepS_st_drive (e : Engine) (h : (stepS P win usb sreq e).st = .drive) :
    e.st = .idle ∧ e.headValid (stepS P win usb sreq e).cur = true := by
  have hst := h
  rw [stepS_st] at hst
  change (dispNext win e).st = .drive at hst
  rw [stepS_cur]
  change e.st = .idle ∧ e.headValid (dispNext win e).cur = true
  unfold dispNext at hst ⊢
  cases hs : e.st with
  | drive => rw [hs] at hst; simp at hst
  | wb => rw [hs] at hst; simp at hst
  | idle =>
    rw [hs] at hst
    dsimp only at hst ⊢
    refine ⟨rfl, ?_⟩
    cases hw : win e with
    | none => rw [hw] at hst; simp at hst
    | some w =>
      rw [hw] at hst
      dsimp only at hst ⊢
      by_cases hv : e.headValid w = true
      · rw [if_pos hv]; exact hv
      · rw [if_neg hv] at hst; simp at hst

/-- A valid slot stays valid unless a retiring writeback of its lane invalidates it. -/
theorem keepSlotS (u : Lane) (s : Slot) (e : Engine)
    (hr : ¬(e.st = .wb ∧ u = e.cur ∧ s = e.sel e.cur ∧ P.ret e.now e.cur = true))
    (h : e.actv u s = true) : (stepS P win usb sreq e).actv u s = true := by
  rw [stepS_actv]
  show actvNext P e u s = true
  unfold actvNext
  rw [if_neg hr]
  split
  · rfl
  · exact h

/-- The requester raises at capture: an ARM captured into `u`'s empty head (`hArm`, the word's
opcode, abstract like `fnpf`) makes the next cycle's request name `u`. -/
def RaiseAtCapture (isArm : Engine → Bool) : Prop :=
  ∀ e, e.pst = .cap → isArm e = true → e.headValid e.pl = false → e.pslot = e.sel e.pl →
    sreq (stepS P win usb sreq e) = some e.pl

theorem p1b_capture (isArm : Engine → Bool)
    (hRaise : RaiseAtCapture P win usb sreq isArm) (u : Lane) (e : Engine) (hS : Struct e)
    (hc : e.pst = .cap) (hl : e.pl = u) (hA : isArm e = true) (hh : e.headValid u = false)
    (hps : e.pslot = e.sel u) (hu : usbFirst P usb (stepS P win usb sreq e) = false) :
    (∀ t, t < 3 → ¬IsRet P u (runS P win usb sreq t e)) ∧
    (runS P win usb sreq 5 e).actv u (!e.sel u) = true ∧
    (∀ k, 5 ≤ k →
      (∀ x, 5 ≤ x → x < k → ¬((runS P win usb sreq x e).st = .wb ∧
        u = (runS P win usb sreq x e).cur ∧ (!e.sel u) = (runS P win usb sreq x e).sel u ∧
        P.ret (runS P win usb sreq x e).now (runS P win usb sreq x e).cur = true)) →
      (runS P win usb sreq k e).actv u (!e.sel u) = true) := by
  have hdv := hS.2
  -- (1) no retirement of u at c, c + 1, c + 2: its head is empty at c
  have hnr0 : ¬IsRet P u e := by
    rintro ⟨hw, hcu, _⟩
    have := hdv (by rw [hw]; decide)
    rw [hcu] at this
    rw [this] at hh; cases hh
  have hnr1 : ¬IsRet P u (runS P win usb sreq 1 e) := by
    rintro ⟨hw, hcu, _⟩
    have hd := stepS_st_wb P win usb sreq e hw
    have hcc := stepS_cur_drive P win usb sreq e hd
    have := hdv (by rw [hd]; decide)
    rw [show runS P win usb sreq 1 e = stepS P win usb sreq e from rfl] at hcu
    rw [hcc] at hcu
    rw [hcu] at this
    rw [this] at hh; cases hh
  have hnr2 : ¬IsRet P u (runS P win usb sreq 2 e) := by
    rintro ⟨hw, hcu, _⟩
    rw [runS_succ'] at hw hcu
    have hd := stepS_st_wb P win usb sreq _ hw
    have hcc := stepS_cur_drive P win usb sreq _ hd
    rw [hcc] at hcu
    have hi := stepS_st_drive P win usb sreq e hd
    rw [show runS P win usb sreq 1 e = stepS P win usb sreq e from rfl] at hcu
    rw [hcu] at hi
    rw [hi.2] at hh; cases hh
  have hnr : ∀ t, t < 3 → ¬IsRet P u (runS P win usb sreq t e) := by
    intro t ht
    rcases (by omega : t = 0 ∨ t = 1 ∨ t = 2) with h | h | h
    · subst h; exact hnr0
    · subst h; exact hnr1
    · subst h; exact hnr2
  -- the head fills at c (the ARM), the select holds through c + 2
  have e1 : runS P win usb sreq 1 e = stepS P win usb sreq e := rfl
  have hsel1 : (runS P win usb sreq 1 e).sel u = e.sel u := by
    rw [e1]; exact selS P win usb sreq u e hnr0
  have hhv1 : (runS P win usb sreq 1 e).headValid u = true := by
    unfold Engine.headValid
    rw [hsel1, e1]
    have := capFillS P win usb sreq u e hc hl hnr0
    rwa [hps] at this
  -- c + 1: the port is scanning (after CAP) and the slot issues for u
  have hpst1 : (runS P win usb sreq 1 e).pst = .scan := by
    rw [e1]
    show (portNextS P usb sreq e).pst = .scan
    rw [portNextS_of_ne P usb sreq e (by rw [hc]; decide)]
    simp [portNext, hc]
  have hq : sreq (runS P win usb sreq 1 e) = some u := by
    rw [e1, ← hl]; exact hRaise e hc hA (by rw [hl]; exact hh) (by rw [hl]; exact hps)
  have hu1 : usbFirst P usb (runS P win usb sreq 1 e) = false := by rw [e1]; exact hu
  have hfs : (runS P win usb sreq 1 e).fetchSlot u = !e.sel u := by
    unfold Engine.fetchSlot; rw [hhv1, hsel1]; rfl
  have hp2 : portOf (runS P win usb sreq 2 e) = ⟨.req, u, (runS P win usb sreq 1 e).prr, true,
      !e.sel u⟩ := by
    rw [runS_succ', portOf_stepS, portNextS_slot P usb sreq _ hpst1 hu1 hq, hfs]
  have hpst2 : (runS P win usb sreq 2 e).pst = .req := congrArg Port.pst hp2
  have hpl2 : (runS P win usb sreq 2 e).pl = u := congrArg Port.pl hp2
  have hps2 : (runS P win usb sreq 2 e).pslot = !e.sel u := congrArg Port.pslot hp2
  have nxt : ∀ k, (runS P win usb sreq k e).pst ≠ .scan →
      portOf (runS P win usb sreq (k + 1) e) = portNext P (runS P win usb sreq k e) := by
    intro k hk
    rw [runS_succ', portOf_stepS, portNextS_of_ne P usb sreq _ hk]
  have hpst3 : (runS P win usb sreq 3 e).pst = .wait := by
    show (portOf (runS P win usb sreq (2 + 1) e)).pst = .wait
    rw [nxt 2 (by rw [hpst2]; decide)]; simp [portNext, hpst2]
  have hk3 := portNext_keeps P (runS P win usb sreq 2 e) (by rw [hpst2]; decide)
  have hpl3 : (runS P win usb sreq 3 e).pl = u := by
    rw [show (runS P win usb sreq 3 e).pl = (portOf (runS P win usb sreq (2 + 1) e)).pl from rfl,
      nxt 2 (by rw [hpst2]; decide), hk3.1, hpl2]
  have hps3 : (runS P win usb sreq 3 e).pslot = !e.sel u := by
    rw [show (runS P win usb sreq 3 e).pslot
        = (portOf (runS P win usb sreq (2 + 1) e)).pslot from rfl,
      nxt 2 (by rw [hpst2]; decide), hk3.2, hps2]
  have hpst4 : (runS P win usb sreq 4 e).pst = .cap := by
    show (portOf (runS P win usb sreq (3 + 1) e)).pst = .cap
    rw [nxt 3 (by rw [hpst3]; decide)]; simp [portNext, hpst3]
  have hk4 := portNext_keeps P (runS P win usb sreq 3 e) (by rw [hpst3]; decide)
  have hpl4 : (runS P win usb sreq 4 e).pl = u := by
    rw [show (runS P win usb sreq 4 e).pl = (portOf (runS P win usb sreq (3 + 1) e)).pl from rfl,
      nxt 3 (by rw [hpst3]; decide), hk4.1, hpl3]
  have hps4 : (runS P win usb sreq 4 e).pslot = !e.sel u := by
    rw [show (runS P win usb sreq 4 e).pslot
        = (portOf (runS P win usb sreq (3 + 1) e)).pslot from rfl,
      nxt 3 (by rw [hpst3]; decide), hk4.2, hps3]
  -- the select through c + 3
  have hsel2 : (runS P win usb sreq 2 e).sel u = e.sel u := by
    rw [runS_succ', selS P win usb sreq u _ hnr1, hsel1]
  have hsel3 : (runS P win usb sreq 3 e).sel u = e.sel u := by
    rw [runS_succ', selS P win usb sreq u _ hnr2, hsel2]
  -- (2) the CAP at c + 4 fills !sel u: a retiring writeback of u at c + 4 has the select still
  -- at sel u (c + 3 was its DRIVE, not a writeback), so it invalidates the ARM's slot, not this
  have hfill : (runS P win usb sreq 5 e).actv u (!e.sel u) = true := by
    rw [runS_succ', stepS_actv]
    show actvNext P (runS P win usb sreq 4 e) u (!e.sel u) = true
    unfold actvNext
    rw [if_neg]
    · rw [if_pos ⟨hpst4, hpl4.symm, hps4.symm⟩]
    · rintro ⟨hw, hcu, hs, _⟩
      rw [runS_succ'] at hw hcu hs
      have hd := stepS_st_wb P win usb sreq _ hw
      have hcc := stepS_cur_drive P win usb sreq _ hd
      rw [hcc] at hcu hs
      rw [← hcu] at hs
      have hs4 := selS P win usb sreq u (runS P win usb sreq 3 e)
        (fun hr => by have h0 := hr.1; rw [hd] at h0; cases h0)
      rw [hs4, hsel3] at hs
      cases hsu : e.sel u <;> rw [hsu] at hs <;> simp at hs
  refine ⟨hnr, hfill, ?_⟩
  -- (3) it stays valid until a retiring writeback of u on that slot
  intro k hk hno
  induction k with
  | zero => omega
  | succ k ih =>
    by_cases h5 : k + 1 = 5
    · rw [h5]; exact hfill
    · have hk' : 5 ≤ k := by omega
      have hv := ih hk' (fun x h1 h2 => hno x h1 (by omega))
      rw [runS_succ']
      apply keepSlotS P win usb sreq u _ _ _ hv
      rintro ⟨hw, hcu, hs, hr⟩
      exact hno k hk' (by omega) ⟨hw, hcu, by rw [hs, ← hcu], hr⟩


/-! ### P1b, variant (1): issue AT capture (P_CAP → P_REQ, Wilson 11-16)

The port, at the CAP that files an ARM into its lane's empty head, goes straight to REQ for that
lane's spare instead of back to SCAN (the opcode and `paddr + ACT_BYTES` are both known at P_CAP,
`pe_engine.v` l.3300–3315), unless USB receive's branch 1 is pending (`usbFirst`): then it yields
and the scan runs. Elsewhere it is `portNextS`. -/

/-- The port with issue-at-capture. -/
def portNextC (P : Program) (usb : Option Lane) (sreq : Engine → Option Lane)
    (isArm : Engine → Bool) (e : Engine) : Port :=
  if e.pst = .cap ∧ isArm e = true ∧ e.headValid e.pl = false ∧ e.pslot = e.sel e.pl ∧
      usbFirst P usb e = false then
    ⟨.req, e.pl, (if e.pbr1 then e.prr else nextLane e.pl), true, !e.sel e.pl⟩
  else portNextS P usb sreq e

def stepC (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : Engine → Option Lane) (isArm : Engine → Bool) (e : Engine) : Engine :=
  let p := portNextC P usb sreq isArm e
  { stepS P win usb sreq e with
    pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot }

def runC (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : Engine → Option Lane) (isArm : Engine → Bool) : Nat → Engine → Engine
  | 0, e => e
  | n + 1, e => runC P win usb sreq isArm n (stepC P win usb sreq isArm e)

theorem runC_succ' (isArm : Engine → Bool) : ∀ (n : Nat) (e : Engine),
    runC P win usb sreq isArm (n + 1) e
      = stepC P win usb sreq isArm (runC P win usb sreq isArm n e)
  | 0, _ => rfl
  | n + 1, e => runC_succ' isArm n (stepC P win usb sreq isArm e)

theorem stepC_disp (isArm : Engine → Bool) (e : Engine) :
    (stepC P win usb sreq isArm e).st = (stepS P win usb sreq e).st ∧
    (stepC P win usb sreq isArm e).cur = (stepS P win usb sreq e).cur ∧
    (stepC P win usb sreq isArm e).actv = (stepS P win usb sreq e).actv ∧
    (stepC P win usb sreq isArm e).sel = (stepS P win usb sreq e).sel :=
  ⟨rfl, rfl, rfl, rfl⟩

theorem p1b_direct (isArm : Engine → Bool) (u : Lane) (e : Engine) (hS : Struct e)
    (hc : e.pst = .cap) (hl : e.pl = u) (hA : isArm e = true) (hh : e.headValid u = false)
    (hps : e.pslot = e.sel u) (hu : usbFirst P usb e = false) :
    (∀ t, t < 3 → ¬IsRet P u (runC P win usb sreq isArm t e)) ∧
    (runC P win usb sreq isArm 4 e).actv u (!e.sel u) = true := by
  have hdv := hS.2
  have hd1 : ∀ e', (stepC P win usb sreq isArm e').st = .wb → e'.st = .drive := fun e' h =>
    stepS_st_wb P win usb sreq e' ((stepC_disp P win usb sreq isArm e').1 ▸ h)
  have hcd : ∀ e', e'.st = .drive → (stepC P win usb sreq isArm e').cur = e'.cur := fun e' h =>
    ((stepC_disp P win usb sreq isArm e').2.1).trans (stepS_cur_drive P win usb sreq e' h)
  have hdd : ∀ e', (stepC P win usb sreq isArm e').st = .drive →
      e'.st = .idle ∧ e'.headValid (stepC P win usb sreq isArm e').cur = true := fun e' h => by
    rw [(stepC_disp P win usb sreq isArm e').2.1]
    exact stepS_st_drive P win usb sreq e' ((stepC_disp P win usb sreq isArm e').1 ▸ h)
  have hselC : ∀ e', ¬IsRet P u e' → (stepC P win usb sreq isArm e').sel u = e'.sel u :=
    fun e' hr => by rw [(stepC_disp P win usb sreq isArm e').2.2.2]; exact selS P win usb sreq u e' hr
  have hnr0 : ¬IsRet P u e := by
    rintro ⟨hw, hcu, _⟩
    have := hdv (by rw [hw]; decide)
    rw [hcu] at this; rw [this] at hh; cases hh
  have e1 : runC P win usb sreq isArm 1 e = stepC P win usb sreq isArm e := rfl
  have hnr1 : ¬IsRet P u (runC P win usb sreq isArm 1 e) := by
    rintro ⟨hw, hcu, _⟩
    rw [e1] at hw hcu
    have hd := hd1 e hw
    rw [hcd e hd] at hcu
    have := hdv (by rw [hd]; decide)
    rw [hcu] at this; rw [this] at hh; cases hh
  have hnr2 : ¬IsRet P u (runC P win usb sreq isArm 2 e) := by
    rintro ⟨hw, hcu, _⟩
    rw [runC_succ'] at hw hcu
    have hd := hd1 _ hw
    rw [hcd _ hd] at hcu
    rw [e1] at hd hcu
    have hi := hdd e hd
    rw [hcu] at hi
    rw [hi.2] at hh; cases hh
  refine ⟨fun t ht => ?_, ?_⟩
  · rcases (by omega : t = 0 ∨ t = 1 ∨ t = 2) with h | h | h
    · subst h; exact hnr0
    · subst h; exact hnr1
    · subst h; exact hnr2
  -- c + 1: REQ for u's spare; c + 2 WAIT; c + 3 CAP
  have hcond : e.pst = .cap ∧ isArm e = true ∧ e.headValid e.pl = false ∧
      e.pslot = e.sel e.pl ∧ usbFirst P usb e = false :=
    ⟨hc, hA, by rw [hl]; exact hh, by rw [hl]; exact hps, hu⟩
  have hp1 : portOf (runC P win usb sreq isArm 1 e)
      = ⟨.req, u, (if e.pbr1 then e.prr else nextLane e.pl), true, !e.sel u⟩ := by
    show portNextC P usb sreq isArm e = _
    unfold portNextC
    rw [if_pos hcond, hl]
  have hpst1 : (runC P win usb sreq isArm 1 e).pst = .req := congrArg Port.pst hp1
  have hpl1 : (runC P win usb sreq isArm 1 e).pl = u := congrArg Port.pl hp1
  have hps1 : (runC P win usb sreq isArm 1 e).pslot = !e.sel u := congrArg Port.pslot hp1
  have nxtC : ∀ k, (runC P win usb sreq isArm k e).pst ≠ .scan →
      (runC P win usb sreq isArm k e).pst ≠ .cap →
      portOf (runC P win usb sreq isArm (k + 1) e) = portNext P (runC P win usb sreq isArm k e) := by
    intro k hk hk2
    rw [runC_succ']
    show portNextC P usb sreq isArm _ = _
    unfold portNextC
    rw [if_neg (fun h => hk2 h.1), portNextS_of_ne P usb sreq _ hk]
  have hpst2 : (runC P win usb sreq isArm 2 e).pst = .wait := by
    show (portOf (runC P win usb sreq isArm (1 + 1) e)).pst = .wait
    rw [nxtC 1 (by rw [hpst1]; decide) (by rw [hpst1]; decide)]; simp [portNext, hpst1]
  have hk2 := portNext_keeps P (runC P win usb sreq isArm 1 e) (by rw [hpst1]; decide)
  have hpl2 : (runC P win usb sreq isArm 2 e).pl = u := by
    rw [show (runC P win usb sreq isArm 2 e).pl
        = (portOf (runC P win usb sreq isArm (1 + 1) e)).pl from rfl,
      nxtC 1 (by rw [hpst1]; decide) (by rw [hpst1]; decide), hk2.1, hpl1]
  have hps2 : (runC P win usb sreq isArm 2 e).pslot = !e.sel u := by
    rw [show (runC P win usb sreq isArm 2 e).pslot
        = (portOf (runC P win usb sreq isArm (1 + 1) e)).pslot from rfl,
      nxtC 1 (by rw [hpst1]; decide) (by rw [hpst1]; decide), hk2.2, hps1]
  have hpst3 : (runC P win usb sreq isArm 3 e).pst = .cap := by
    show (portOf (runC P win usb sreq isArm (2 + 1) e)).pst = .cap
    rw [nxtC 2 (by rw [hpst2]; decide) (by rw [hpst2]; decide)]; simp [portNext, hpst2]
  have hk3 := portNext_keeps P (runC P win usb sreq isArm 2 e) (by rw [hpst2]; decide)
  have hpl3 : (runC P win usb sreq isArm 3 e).pl = u := by
    rw [show (runC P win usb sreq isArm 3 e).pl
        = (portOf (runC P win usb sreq isArm (2 + 1) e)).pl from rfl,
      nxtC 2 (by rw [hpst2]; decide) (by rw [hpst2]; decide), hk3.1, hpl2]
  have hps3 : (runC P win usb sreq isArm 3 e).pslot = !e.sel u := by
    rw [show (runC P win usb sreq isArm 3 e).pslot
        = (portOf (runC P win usb sreq isArm (2 + 1) e)).pslot from rfl,
      nxtC 2 (by rw [hpst2]; decide) (by rw [hpst2]; decide), hk3.2, hps2]
  -- the select holds through c + 3 (no retirement at c, c + 1, c + 2)
  have hsel1 : (runC P win usb sreq isArm 1 e).sel u = e.sel u := by rw [e1]; exact hselC e hnr0
  have hsel2 : (runC P win usb sreq isArm 2 e).sel u = e.sel u := by
    rw [runC_succ', hselC _ hnr1, hsel1]
  have hsel3 : (runC P win usb sreq isArm 3 e).sel u = e.sel u := by
    rw [runC_succ', hselC _ hnr2, hsel2]
  -- c + 3: CAP files !sel u; a retiring writeback of u there invalidates sel u, not this slot
  rw [runC_succ', (stepC_disp P win usb sreq isArm _).2.2.1, stepS_actv]
  show actvNext P (runC P win usb sreq isArm 3 e) u (!e.sel u) = true
  unfold actvNext
  rw [if_neg]
  · rw [if_pos ⟨hpst3, hpl3.symm, hps3.symm⟩]
  · rintro ⟨_, hcu, hs, _⟩
    rw [← hcu, hsel3] at hs
    cases hsu : e.sel u <;> rw [hsu] at hs <;> simp at hs

/-! ### The two margins, generated (pinned: `proof_constants.p1b_margin_scan` / `_direct`)

The successor's earliest release, from the ARM's capture `c`: its writeback at `c + 3` at the
earliest (the first parts of `p1b_capture` / `p1b_direct`: `DISPATCH_CYCLES` after the head is
valid at `c + 1`, less one) plus ArmRetire's `ARM_RETIRE_GAP` (`arm_release_ge`: `now + 2`). The
word is valid at `c + 5` through the scan (`1 + L_REFILL`), at `c + 4` issued at capture
(`L_REFILL`). -/

/-- `arm_release_ge`'s `+ 2`: the successor of a plain ARM is released at least this far past
the ARM's writeback (pinned: `proof_constants.arm_retire_gap`). -/
abbrev ARM_RETIRE_GAP : Nat := 2
abbrev P1B_FILL_SCAN : Nat := 1 + L_REFILL
abbrev P1B_FILL_DIRECT : Nat := L_REFILL
abbrev P1B_MARGIN_SCAN : Nat := DISPATCH_CYCLES + ARM_RETIRE_GAP - P1B_FILL_SCAN
abbrev P1B_MARGIN_DIRECT : Nat := DISPATCH_CYCLES + ARM_RETIRE_GAP - P1B_FILL_DIRECT

theorem p1b_margin_scan_val : P1B_MARGIN_SCAN = 0 := rfl
theorem p1b_margin_direct_val : P1B_MARGIN_DIRECT = 1 := rfl

/-- **The margin, variant (2) (raise at capture, through the scan): 0.** For an ARM retirement of
`u` at `c + t` (`t ≥ 3` by `p1b_capture`), the word valid from `c + 5` is valid
`P1B_MARGIN_SCAN` cycles before the successor's earliest release `c + t + ARM_RETIRE_GAP`. -/
theorem p1b_margin_scan (t : Nat) (ht : ¬t < 3) :
    P1B_FILL_SCAN + P1B_MARGIN_SCAN ≤ t + ARM_RETIRE_GAP := by
  simp only [P1B_FILL_SCAN, P1B_MARGIN_SCAN, DISPATCH_CYCLES, ARM_RETIRE_GAP, L_REFILL] at *
  omega

/-- **The margin, variant (1) (issue at capture): 1.** -/
theorem p1b_margin_direct (t : Nat) (ht : ¬t < 3) :
    P1B_FILL_DIRECT + P1B_MARGIN_DIRECT ≤ t + ARM_RETIRE_GAP := by
  simp only [P1B_FILL_DIRECT, P1B_MARGIN_DIRECT, DISPATCH_CYCLES, ARM_RETIRE_GAP, L_REFILL] at *
  omega

end

end JLane

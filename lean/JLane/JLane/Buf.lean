import JLane.Slot
/-!
# Brick S2 — the depth-2 buffer, always two fetches per ARM (Wilson 11-16)

The requester fetches the ARM's next two words; the buffer (one per lane, two words deep) holds
what has no free slot yet and loads into the slot a retirement frees. Order by ARM type: a plain
ARM fetches PC+1 then PC+2; a FALLTHROUGH ARM fetches PC+2 (the edge word) then PC+1 (the
timeout word). The port does not care where a captured word is filed (slot or buffer): it runs
`SCAN → REQ → WAIT → CAP` either way, so the two fetches' timing is proved at the port, for an
ARM captured into its lane's head **or spare**.

Proved:
* `two_fetch_scan` -- raise at capture, each fetch issued at the scan: fetch 1 captured at
  `c + 4`, fetch 2 at `c + 8` (words valid at `c + 5`, `c + 9`);
* `two_fetch_direct` -- issue at capture (`P_CAP → P_REQ` for the ARM's capture and again for
  fetch 1's): fetch 1 captured at `c + 3`, fetch 2 at `c + 6` (valid at `c + 4`, `c + 7`);
* `buf_load` -- the buffer rule: a buffered word is in the slot its lane's retirement frees,
  valid the cycle after that writeback, one cycle before ArmRetire's earliest release;
* the margins, generated and pinned (`proof_constants`): the second word after an ARM whose
  PC+1 is an ARM (m1 / m3) -- `P1B2_MARGIN_ARM_SCAN` = 0, `P1B2_MARGIN_ARM_DIRECT` = 2; after a
  plain PC+1 of spacing `d` -- `d - 4` / `d - 2` (`p1b2_margin_plain_*`); a FALLTHROUGH ARM's
  timeout word, fetched second, against its deadline (`p1b2_margin_timeout_*`).

Owed (the carry-through brick): the buffer's state in the engine (`Struct` with buffered words),
`slot_count` at two per ARM, and the head-valid theorems under it.
-/
namespace JLane

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : Engine → Option Lane)

/-- Away from a scan the slot port runs the shipped FSM: `REQ → WAIT → CAP → SCAN`, lane and
slot held. -/
theorem portS_seq (e : Engine) (k : Nat) (hk : (runS P win usb sreq k e).pst ≠ .scan) :
    portOf (runS P win usb sreq (k + 1) e) = portNext P (runS P win usb sreq k e) := by
  rw [runS_succ', portOf_stepS, portNextS_of_ne P usb sreq _ hk]

/-- A slot issue at a scan for `u`: three cycles later the port captures for `u`. -/
theorem slot_issue_cap (u : Lane) (e : Engine) (k : Nat)
    (hp : (runS P win usb sreq k e).pst = .scan)
    (hu : usbFirst P usb (runS P win usb sreq k e) = false)
    (hq : sreq (runS P win usb sreq k e) = some u) :
    (runS P win usb sreq (k + 3) e).pst = .cap ∧ (runS P win usb sreq (k + 3) e).pl = u := by
  have h1 : portOf (runS P win usb sreq (k + 1) e)
      = ⟨.req, u, (runS P win usb sreq k e).prr, true,
          (runS P win usb sreq k e).fetchSlot u⟩ := by
    rw [runS_succ', portOf_stepS, portNextS_slot P usb sreq _ hp hu hq]
  have hp1 : (runS P win usb sreq (k + 1) e).pst = .req := congrArg Port.pst h1
  have hl1 : (runS P win usb sreq (k + 1) e).pl = u := congrArg Port.pl h1
  have h2 := portS_seq P win usb sreq e (k + 1) (by rw [hp1]; decide)
  have hp2 : (runS P win usb sreq (k + 2) e).pst = .wait := by
    show (portOf (runS P win usb sreq (k + 1 + 1) e)).pst = .wait
    rw [h2]; simp [portNext, hp1]
  have hl2 : (runS P win usb sreq (k + 2) e).pl = u := by
    show (portOf (runS P win usb sreq (k + 1 + 1) e)).pl = u
    rw [h2, (portNext_keeps P _ (by rw [hp1]; decide)).1, hl1]
  have h3 := portS_seq P win usb sreq e (k + 2) (by rw [hp2]; decide)
  constructor
  · show (portOf (runS P win usb sreq (k + 2 + 1) e)).pst = .cap
    rw [h3]; simp [portNext, hp2]
  · show (portOf (runS P win usb sreq (k + 2 + 1) e)).pl = u
    rw [h3, (portNext_keeps P _ (by rw [hp2]; decide)).1, hl2]

/-- After a CAP the port scans. -/
theorem cap_then_scan (e : Engine) (k : Nat) (hc : (runS P win usb sreq k e).pst = .cap) :
    (runS P win usb sreq (k + 1) e).pst = .scan := by
  show (portOf (runS P win usb sreq (k + 1) e)).pst = .scan
  rw [portS_seq P win usb sreq e k (by rw [hc]; decide)]
  simp [portNext, hc]

/-- **Two fetches, raised at capture, each issued at the scan.** From the CAP `c` that files the
ARM for `u` (into its head or its spare): with the request naming `u` at the scan after it and
again at the scan after fetch 1's capture, and USB receive not taking those scans, fetch 1 is
captured at `c + 4` and fetch 2 at `c + 8`. -/
theorem two_fetch_scan (u : Lane) (e : Engine) (hc : e.pst = .cap)
    (hq1 : sreq (runS P win usb sreq 1 e) = some u)
    (hu1 : usbFirst P usb (runS P win usb sreq 1 e) = false)
    (hq2 : sreq (runS P win usb sreq 5 e) = some u)
    (hu2 : usbFirst P usb (runS P win usb sreq 5 e) = false) :
    ((runS P win usb sreq 4 e).pst = .cap ∧ (runS P win usb sreq 4 e).pl = u) ∧
    ((runS P win usb sreq 8 e).pst = .cap ∧ (runS P win usb sreq 8 e).pl = u) := by
  have hs1 : (runS P win usb sreq 1 e).pst = .scan :=
    cap_then_scan P win usb sreq e 0 hc
  have f1 := slot_issue_cap P win usb sreq u e 1 hs1 hu1 hq1
  have hs5 : (runS P win usb sreq 5 e).pst = .scan :=
    cap_then_scan P win usb sreq e 4 f1.1
  exact ⟨f1, slot_issue_cap P win usb sreq u e 5 hs5 hu2 hq2⟩

end

/-! ### Issue at capture, for both fetches -/

/-- The port with issue-at-capture for both fetches: at the CAP that files an ARM (`isArm`) and
at the CAP that files an ARM lane's first slot word (`isFirst`), straight to REQ for that lane,
unless USB receive's branch 1 is pending. -/
def portNextC2 (P : Program) (usb : Option Lane) (sreq : Engine → Option Lane)
    (isArm isFirst : Engine → Bool) (e : Engine) : Port :=
  if e.pst = .cap ∧ (isArm e = true ∨ isFirst e = true) ∧ usbFirst P usb e = false then
    ⟨.req, e.pl, (if e.pbr1 then e.prr else nextLane e.pl), true, !e.sel e.pl⟩
  else portNextS P usb sreq e

def stepC2 (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : Engine → Option Lane) (isArm isFirst : Engine → Bool) (e : Engine) : Engine :=
  let p := portNextC2 P usb sreq isArm isFirst e
  { stepS P win usb sreq e with
    pst := p.pst, pl := p.pl, prr := p.prr, pbr1 := p.pbr1, pslot := p.pslot }

def runC2 (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
    (sreq : Engine → Option Lane) (isArm isFirst : Engine → Bool) : Nat → Engine → Engine
  | 0, e => e
  | n + 1, e => runC2 P win usb sreq isArm isFirst n (stepC2 P win usb sreq isArm isFirst e)

section
variable (P : Program) (win : Engine → Option Lane) (usb : Option Lane)
  (sreq : Engine → Option Lane) (isArm isFirst : Engine → Bool)

theorem runC2_succ' : ∀ (n : Nat) (e : Engine),
    runC2 P win usb sreq isArm isFirst (n + 1) e
      = stepC2 P win usb sreq isArm isFirst (runC2 P win usb sreq isArm isFirst n e)
  | 0, _ => rfl
  | n + 1, e => runC2_succ' n (stepC2 P win usb sreq isArm isFirst e)

theorem portC2_seq (e : Engine) (k : Nat)
    (hk : (runC2 P win usb sreq isArm isFirst k e).pst ≠ .scan)
    (hk2 : (runC2 P win usb sreq isArm isFirst k e).pst ≠ .cap) :
    portOf (runC2 P win usb sreq isArm isFirst (k + 1) e)
      = portNext P (runC2 P win usb sreq isArm isFirst k e) := by
  rw [runC2_succ']
  show portNextC2 P usb sreq isArm isFirst _ = _
  unfold portNextC2
  rw [if_neg (fun h => hk2 h.1), portNextS_of_ne P usb sreq _ hk]

/-- A direct issue at a CAP for its lane: three cycles later the port captures for that lane. -/
theorem direct_issue_cap (u : Lane) (e : Engine) (k : Nat)
    (hc : (runC2 P win usb sreq isArm isFirst k e).pst = .cap)
    (hl : (runC2 P win usb sreq isArm isFirst k e).pl = u)
    (hw : isArm (runC2 P win usb sreq isArm isFirst k e) = true ∨
      isFirst (runC2 P win usb sreq isArm isFirst k e) = true)
    (hu : usbFirst P usb (runC2 P win usb sreq isArm isFirst k e) = false) :
    (runC2 P win usb sreq isArm isFirst (k + 3) e).pst = .cap ∧
    (runC2 P win usb sreq isArm isFirst (k + 3) e).pl = u := by
  have h1 : portOf (runC2 P win usb sreq isArm isFirst (k + 1) e)
      = ⟨.req, u, (if (runC2 P win usb sreq isArm isFirst k e).pbr1
            then (runC2 P win usb sreq isArm isFirst k e).prr
            else nextLane (runC2 P win usb sreq isArm isFirst k e).pl), true,
          !(runC2 P win usb sreq isArm isFirst k e).sel
            (runC2 P win usb sreq isArm isFirst k e).pl⟩ := by
    rw [runC2_succ']
    show portNextC2 P usb sreq isArm isFirst _ = _
    unfold portNextC2
    rw [if_pos ⟨hc, hw, hu⟩, hl]
  have hp1 : (runC2 P win usb sreq isArm isFirst (k + 1) e).pst = .req := congrArg Port.pst h1
  have hl1 : (runC2 P win usb sreq isArm isFirst (k + 1) e).pl = u := congrArg Port.pl h1
  have h2 := portC2_seq P win usb sreq isArm isFirst e (k + 1) (by rw [hp1]; decide)
    (by rw [hp1]; decide)
  have hp2 : (runC2 P win usb sreq isArm isFirst (k + 2) e).pst = .wait := by
    show (portOf (runC2 P win usb sreq isArm isFirst (k + 1 + 1) e)).pst = .wait
    rw [h2]; simp [portNext, hp1]
  have hl2 : (runC2 P win usb sreq isArm isFirst (k + 2) e).pl = u := by
    show (portOf (runC2 P win usb sreq isArm isFirst (k + 1 + 1) e)).pl = u
    rw [h2, (portNext_keeps P _ (by rw [hp1]; decide)).1, hl1]
  have h3 := portC2_seq P win usb sreq isArm isFirst e (k + 2) (by rw [hp2]; decide)
    (by rw [hp2]; decide)
  constructor
  · show (portOf (runC2 P win usb sreq isArm isFirst (k + 2 + 1) e)).pst = .cap
    rw [h3]; simp [portNext, hp2]
  · show (portOf (runC2 P win usb sreq isArm isFirst (k + 2 + 1) e)).pl = u
    rw [h3, (portNext_keeps P _ (by rw [hp2]; decide)).1, hl2]

/-- **Two fetches, issued at capture.** From the CAP `c` filing the ARM for `u` (head or spare):
fetch 1 captured at `c + 3`; that CAP is fetch 1's (`isFirst`), so fetch 2 is issued at once and
captured at `c + 6`. USB receive's branch 1 is not pending at either CAP. -/
theorem two_fetch_direct (u : Lane) (e : Engine) (hc : e.pst = .cap) (hl : e.pl = u)
    (hA : isArm e = true) (hu0 : usbFirst P usb e = false)
    (hF : isFirst (runC2 P win usb sreq isArm isFirst 3 e) = true)
    (hu3 : usbFirst P usb (runC2 P win usb sreq isArm isFirst 3 e) = false) :
    ((runC2 P win usb sreq isArm isFirst 3 e).pst = .cap ∧
      (runC2 P win usb sreq isArm isFirst 3 e).pl = u) ∧
    ((runC2 P win usb sreq isArm isFirst 6 e).pst = .cap ∧
      (runC2 P win usb sreq isArm isFirst 6 e).pl = u) := by
  have f1 := direct_issue_cap P win usb sreq isArm isFirst u e 0 hc hl (Or.inl hA) hu0
  exact ⟨f1, direct_issue_cap P win usb sreq isArm isFirst u e 3 f1.1 f1.2 (Or.inr hF) hu3⟩

end

/-! ### The buffer rule -/

/-- One lane's storage at a writeback: the head slot, the other slot, the buffer's front word. -/
structure LaneStore where
  head  : Bool
  spare : Bool
  buf   : Bool

/-- A retiring writeback: the head is consumed, the spare becomes the head, and the slot the
retirement frees (the old head's) takes the buffer's front word, if any. -/
def retireStore (s : LaneStore) : LaneStore :=
  { head := s.spare, spare := s.buf, buf := false }

/-- **`buf_load`.** A word in the buffer at a retirement whose successor is already in the spare
is in the freed slot the cycle after, and becomes the head at the next retirement: one cycle
after the writeback, one before ArmRetire's earliest release (`ARM_RETIRE_GAP` = 2). -/
theorem buf_load (s : LaneStore) (hs : s.spare = true) (hb : s.buf = true) :
    (retireStore s).head = true ∧ (retireStore s).spare = true ∧
    (retireStore (retireStore s)).head = true := by
  simp [retireStore, hs, hb]

theorem buf_load_margin : 1 + 1 ≤ ARM_RETIRE_GAP := by decide

/-- Always two (Wilson 11-16): the requester fetches two words per ARM, so each ARM costs the
other lanes two slot fetches (pinned: `proof_constants.slot_fetches_per_arm`). -/
abbrev SLOT_FETCHES_PER_ARM : Nat := 2

theorem slot_fetches_per_arm_val : SLOT_FETCHES_PER_ARM = 2 := rfl

/-! ### The margins, generated (pinned through `proof_constants`) -/

/-- Fetch 2's word valid at `c +` this: through the scan `1 + 2·L_REFILL`, at capture
`2·L_REFILL - 1`. -/
abbrev P1B2_FILL_SCAN : Nat := 1 + 2 * L_REFILL
abbrev P1B2_FILL_DIRECT : Nat := 2 * L_REFILL - 1
/-- The second word's earliest release when PC+1 is itself an ARM: PC+1 released at
`c + DISPATCH_CYCLES + ARM_RETIRE_GAP`, decided then, written back `DISPATCH_CYCLES - 1` later,
its successor `ARM_RETIRE_GAP` after that. -/
abbrev P1B2_REL_ARM : Nat :=
  DISPATCH_CYCLES + ARM_RETIRE_GAP + (DISPATCH_CYCLES - 1) + ARM_RETIRE_GAP
abbrev P1B2_MARGIN_ARM_SCAN : Nat := P1B2_REL_ARM - P1B2_FILL_SCAN
abbrev P1B2_MARGIN_ARM_DIRECT : Nat := P1B2_REL_ARM - P1B2_FILL_DIRECT

theorem p1b2_fill_scan_val : P1B2_FILL_SCAN = 9 := rfl
theorem p1b2_fill_direct_val : P1B2_FILL_DIRECT = 7 := rfl
theorem p1b2_margin_arm_scan_val : P1B2_MARGIN_ARM_SCAN = 0 := rfl
theorem p1b2_margin_arm_direct_val : P1B2_MARGIN_ARM_DIRECT = 2 := rfl

/-- **m1 / m3 (PC+1 an ARM), through the scan: margin 0.** -/
theorem p1b2_margin_arm_scan : P1B2_FILL_SCAN + P1B2_MARGIN_ARM_SCAN ≤ P1B2_REL_ARM := by decide

/-- **m1 / m3 (PC+1 an ARM), at capture: margin 2.** -/
theorem p1b2_margin_arm_direct : P1B2_FILL_DIRECT + P1B2_MARGIN_ARM_DIRECT ≤ P1B2_REL_ARM := by
  decide

/-- **A plain PC+1 of spacing `d`** (released at `c + 5` at the earliest, PC+2 `d` later):
through the scan the margin is `d - 4`. -/
theorem p1b2_margin_plain_scan (d : Nat) (hd : 4 ≤ d) :
    P1B2_FILL_SCAN + (d - 4) ≤ (DISPATCH_CYCLES + ARM_RETIRE_GAP) + d := by
  simp only [P1B2_FILL_SCAN, DISPATCH_CYCLES, ARM_RETIRE_GAP, L_REFILL]; omega

/-- **A plain PC+1 of spacing `d`, at capture: margin `d - 2`.** -/
theorem p1b2_margin_plain_direct (d : Nat) (hd : 2 ≤ d) :
    P1B2_FILL_DIRECT + (d - 2) ≤ (DISPATCH_CYCLES + ARM_RETIRE_GAP) + d := by
  simp only [P1B2_FILL_DIRECT, DISPATCH_CYCLES, ARM_RETIRE_GAP, L_REFILL]; omega

/-- **A FALLTHROUGH ARM's timeout word, fetched second.** It is released at the deadline, at
least `T - L` past the ARM's capture (`T` the timeout, `L` the ARM's certified lateness: the
ARM is captured by its release plus `L`). Margins `T - L - 9` / `T - L - 7`. -/
theorem p1b2_margin_timeout_scan (T L : Nat) (h : P1B2_FILL_SCAN + L ≤ T) :
    P1B2_FILL_SCAN + (T - L - P1B2_FILL_SCAN) ≤ T - L := by omega

theorem p1b2_margin_timeout_direct (T L : Nat) (h : P1B2_FILL_DIRECT + L ≤ T) :
    P1B2_FILL_DIRECT + (T - L - P1B2_FILL_DIRECT) ≤ T - L := by omega

end JLane

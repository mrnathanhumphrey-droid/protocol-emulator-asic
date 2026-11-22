import JLane.BufEng
/-!
# Brick K13 — the slot yields to the USB lane only once USB is on (Wilson 11-22)

`BufEng.stepB` takes the USB receive lane as a fixed parameter `usb`: the slot yields to its
branch-1 refill (`usbFirst`) on every cycle of the run. The RTL (agent 1, 11-22, must-fire
`M_SLOT_YIELD_UNGATED`) gates the yield by a register `usb_on`: off at reset, set when lane 0's
first USB receive executes, never cleared. Here `usb_on` is state:

* `EngBU` is the buffered engine with the flag; `stepBU` steps `stepB` with
  `usb := usbOf on` (lane 0 while on, `none` while off) and sets the flag on `rx` (lane 0's USB
  receive executes this cycle: an abstract input, like `win` and `sreq`);
* `usbFirst_off` -- while off the slot never yields to lane 0 (the port is `stepB`'s with
  `usb = none`);
* `runBU_on` -- once on, the run **is** `runB` with `usb = some usbLane`, and stays on: every
  theorem proved on `runB` for a fixed `usb` applies from the cycle `usb_on` is set;
* `runBU_off` -- until `rx` fires, the run is `runB` with `usb = none`;
* `wfBU_run`, `ordBU_run`, `heldBU_step` -- well-formedness, the order invariant and
  conservation hold across the switch (their step theorems hold for every `usb`).

`model/step_b.py` mirrors this (`usb_on` in the state, set by `ext['usb_rx']`).
-/
namespace JLane

/-- The USB receive lane (K13: lane 0). -/
def usbLane : Lane := ⟨0, by decide⟩

/-- `stepB`'s `usb`, read from the flag. -/
def usbOf : Bool → Option Lane
  | true => some usbLane
  | false => none

/-- The buffered engine with K13's `usb_on`. -/
structure EngBU where
  x  : EngB
  on : Bool

section
variable (P : Program) (win : Engine → Option Lane) (sreq : EngB → Option Lane)
  (rx : EngB → Bool)

/-- One cycle: `stepB` with the yield gated by the flag; the flag is set by lane 0's receive. -/
def stepBU (z : EngBU) : EngBU :=
  { x := stepB P win (usbOf z.on) sreq z.x, on := z.on || rx z.x }

def runBU : Nat → EngBU → EngBU
  | 0, z => z
  | n + 1, z => runBU n (stepBU P win sreq rx z)

theorem stepBU_x (z : EngBU) : (stepBU P win sreq rx z).x = stepB P win (usbOf z.on) sreq z.x :=
  rfl

/-- While off, the slot never yields to the USB lane. -/
theorem usbFirst_off (e : Engine) : usbFirst P (usbOf false) e = false := by
  unfold usbFirst usbOf
  cases br1 P e <;> rfl

/-- **Once on, always on, and the run is `runB` with the USB lane fixed.** -/
theorem runBU_on : ∀ (n : Nat) (z : EngBU), z.on = true →
    (runBU P win sreq rx n z).x = runB P win (some usbLane) sreq n z.x ∧
      (runBU P win sreq rx n z).on = true
  | 0, _, h => ⟨rfl, h⟩
  | n + 1, z, h => by
    have hs : (stepBU P win sreq rx z).on = true := by
      show (z.on || rx z.x) = true
      rw [h]; rfl
    have hx : (stepBU P win sreq rx z).x = stepB P win (some usbLane) sreq z.x := by
      show stepB P win (usbOf z.on) sreq z.x = _
      rw [h]; rfl
    have ih := runBU_on n (stepBU P win sreq rx z) hs
    refine ⟨?_, ih.2⟩
    show (runBU P win sreq rx n (stepBU P win sreq rx z)).x
      = runB P win (some usbLane) sreq n (stepB P win (some usbLane) sreq z.x)
    rw [ih.1, hx]

/-- **Until lane 0's receive, the run is `runB` with no USB lane.** -/
theorem runBU_off : ∀ (n : Nat) (z : EngBU), z.on = false →
    (∀ k, k < n → rx (runBU P win sreq rx k z).x = false) →
    (runBU P win sreq rx n z).x = runB P win none sreq n z.x ∧
      (runBU P win sreq rx n z).on = false
  | 0, _, h, _ => ⟨rfl, h⟩
  | n + 1, z, h, hr => by
    have h0 : rx z.x = false := hr 0 (Nat.succ_pos n)
    have hs : (stepBU P win sreq rx z).on = false := by
      show (z.on || rx z.x) = false
      rw [h, h0]; rfl
    have hx : (stepBU P win sreq rx z).x = stepB P win none sreq z.x := by
      show stepB P win (usbOf z.on) sreq z.x = _
      rw [h]; rfl
    have ih := runBU_off n (stepBU P win sreq rx z) hs
      (fun k hk => hr (k + 1) (Nat.succ_lt_succ hk))
    refine ⟨?_, ih.2⟩
    show (runBU P win sreq rx n (stepBU P win sreq rx z)).x
      = runB P win none sreq n (stepB P win none sreq z.x)
    rw [ih.1, hx]

/-- Well-formedness holds across the switch. -/
theorem wfBU_run (hok : SReqB P sreq) :
    ∀ (n : Nat) (z : EngBU), WfB z.x → WfB (runBU P win sreq rx n z).x
  | 0, _, h => h
  | n + 1, z, h =>
    wfBU_run hok n (stepBU P win sreq rx z) (wfB_step P win (usbOf z.on) sreq hok z.x h)

/-- The order invariant holds across the switch. -/
theorem ordBU_run (hok : SReqB P sreq) :
    ∀ (n : Nat) (z : EngBU), WfB z.x → OrdB z.x → OrdB (runBU P win sreq rx n z).x
  | 0, _, _, h => h
  | n + 1, z, hW, hO =>
    ordBU_run hok n (stepBU P win sreq rx z) (wfB_step P win (usbOf z.on) sreq hok z.x hW)
      (ordB_step P win (usbOf z.on) sreq hok z.x hW hO)

/-- Conservation of words, one cycle, whichever side of the switch. -/
theorem heldBU_step (z : EngBU) (hW : WfB z.x) (y : Lane) :
    (stepBU P win sreq rx z).x.held y + (if IsRet P y z.x.e then 1 else 0)
      = z.x.held y + (if Hit y z.x.e then 1 else 0) :=
  held_step P win (usbOf z.on) sreq z.x hW y

end

end JLane

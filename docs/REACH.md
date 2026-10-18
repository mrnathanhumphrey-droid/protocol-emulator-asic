# Reach list

Ideas for after the lock. It's a list, not a plan, and nothing in it is
promised. Each item says where it came from and what it is known to cost.

## The branch, in order

All five come from the post-lock branch as planned with Wilson. Where a cost
has not been estimated, it says so.

1. **SRAM.**
   - Design rule: any added store latency is absorbed before capture, so the
     Lean invariants stay untouched.
   - Cost: not yet estimated.
2. **60+ MHz.**
   - Groundwork: PREP-60 (`clock.json`, `model/fclk.py`, branch `prep-60`).
   - Cost: a dispatch pipeline aimed at the scheduler paths, which must clear at
     all three placement densities by more than the ~0.7 ns noise band.
3. **Per-lane serializers with line coder and CRC.**
   - Cost: not yet estimated.
4. **USB.**
   - Cost: not yet estimated.
5. **Ethernet.**
   - Cost: not yet estimated.

## Candidates gathered on the way

- **WS2812.**
  - From: withdrawn at 50 MHz: T0H max 380 ns is below D* (400 ns).
  - Cost: may return at 60+ MHz. Prospective only.
- **Per-lane status in the frame:** which lane timed out, underran or
  overflowed.
  - From: the HOST_INTERFACE audit (the host can't tell which lane; see
    *What is kept*).
  - Cost: the frame format changes for every host.
- **Idle-slot-only heartbeat:** liveness at no data cost.
  - From: the HOST_INTERFACE audit (an idle chip is silent, so a host can't
    tell idle from dead). A fixed heartbeat was rejected because it would cost
    the data it reports; one sent only in slots where nothing is waiting fills
    time the stream would otherwise spend silent.
  - Cost: logic and frame change; evaluate next to per-lane status.
- **Remove the dead `l_timeout` registers.**
  - From: `l_timeout_m` / `l_timeout_k` have no logic reader; host timeout
    visibility is via `sticky_ovr`.
  - Cost: a netlist change, so canaries and a harden; deferred from the lock.
- **Generated RTL clock constants** (`clock_params.vh` from the PREP-60
  generator), so the hardware is one number too.
  - From: PREP-60.
  - Cost: a CE5 re-certification.
- **Parametric Lean port FSM** (`wait n` from `L_REFILL`).
  - From: ruled.
  - Cost: not yet estimated; LN1 referees before merge.
- **I²C at a full 397–400 kHz on a real bus.**
  - From: the FPGA bench witness. The published Fast-mode lane runs at
    397 kHz with ideal edges, and measured 370.4 kHz (range 365.0–374.5) on
    the PA100T with ~3.2 kΩ pull-ups on a breadboard. The chip waits for each
    real SCL rise before counting the high phase, so the rate depends on the
    bus by design. A rise-matched simulation reproduces the measured rate:
    each bit adds the FPGA glue's 3 cycles plus the real rise.
  - Cost: a shorter programmed delay for a known bus, or stronger pull-ups.
    Either is a bench re-measurement, not a silicon change. The claim stays
    "measured" until a run measures it.
- **`.gitattributes` pinning line endings** for the fingerprinted files.
  - From: CRLF noise in recorded hashes.
  - Cost: small; can land right after the lock.

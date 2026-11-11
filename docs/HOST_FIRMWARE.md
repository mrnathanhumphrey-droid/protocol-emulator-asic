# Host firmware requirements (the RP2040)

**What this is.** The obligations the chip places on the host firmware — on
the Tiny Tapeout demo board, the RP2040 that loads programs, feeds the TX
queues and reads the serial stream. `docs/HOST_INTERFACE.md` is the **wire
contract** (pins, frames, what the chip does); this file is what the
**firmware must do** for that contract to hold. Each requirement is numbered
(FW-n) and names the chip behaviour or gate that depends on it, so a change on
either side shows what else moves.

**Numbers are generated, never typed.** Every value between `gen:` markers is
written by `python model/gate_clock_consistency.py --write` from
`model/clock.py` and the chip's clock in `info.yaml`, and check 9 of that gate
is red if the text here and the computation disagree. Times are given in
**chip cycles** first; nanoseconds are at the **slow edge of the clock band**
(the chip clock divided by the band), because the firmware must cover the
longest chip cycle it may meet.

---

## Push timing (every TX push, every tag)

**FW-1 — Hold.** After raising `wr` (`ui_in[6]`), hold `tx_nibble`
(`ui_in[4:1]`) and `tag` (`{ui_in[5], ui_in[0]}`) stable for at least
<!--gen:fw_hold-->**5 chip cycles** (87.5 ns at the band's slow edge, 57.143 MHz, for a 60 MHz chip)<!--/gen-->.
- This covers **every** push: an ordinary TX queue, **tag 3** while it is the
  USB response buffer, and **tag 2** while it is the USB control channel. Those
  bytes are captured on the same synchronised `wr` edge as a queue byte.
- *Why this number:* `wr` passes a 3-flop synchroniser, so the data is
  captured on the **3rd** chip clock edge after the pad edge, or the **4th** if
  the first synchroniser flop resolves late. 4 is the bare worst case; the 5th
  cycle is margin for the capture flop's hold time and for skew between the
  nibble pins and `wr` (TT's FAQ puts the I/O round trip near 10 ns).
- *Depends on it:* every capture site on the synchronised edge
  (`model/gate_cdc_qual.py` proves no flop takes a raw pin while that edge is
  low), the SRAM macro's inputs (`model/gate_macro_inputs.py`), and check 9 of
  `model/gate_clock_consistency.py`, which derives the count from the RTL's
  synchroniser depth. The bench driver (`test/host_feed.vh`) holds exactly
  this many cycles.

**FW-2 — Setup.** Make `tx_nibble` and `tag` stable at least
<!--gen:fw_setup-->**1 chip cycle** (17.5 ns at the band's slow edge, 57.143 MHz, for a 60 MHz chip)<!--/gen-->
before raising `wr`.
- *Why this number:* the earliest capture is at least 2 cycles after the pad
  edge, so a nibble that is stable when `wr` rises is already safe. The 1 cycle
  is skew margin, the same margin FW-1 carries.
- *Depends on it:* as FW-1.

**FW-3 — `wr` pulse.** Hold `wr` high for at least 3 chip cycles, so its
synchroniser sees the edge (the load procedure's rule in `HOST_INTERFACE.md`,
which applies to every push).
- *Depends on it:* `wr_rise` in `src/project.v`; a missed edge is a push that
  never arrives.

---

## USB device (while the USB lane is live)

**FW-4 — Acknowledge a bus reset.** A USB bus reset makes the chip clear its
address, READY and the response buffer and send **one kind-5 frame** on the
serial stream. Until the firmware sends `0x01` on **tag 2**, every tag-3 byte
and pending-address record is **refused** (the TX-full status bit), so a
record sent before the firmware learned of the reset can never land. An
acknowledgement with no reset pending changes nothing.
- *Depends on it:* the reset fence (`usb_fence` in `src/project.v`),
  `test/run_usbrst.py`, `test/run_usbaddr.py`.

**FW-5 — Treat `rx_drop_sticky` as a reset.** If `rx_drop_sticky` is set while
USB is on, assume a bus reset was missed: send `0x01` on tag 2 and
resynchronise. This is the backstop for a kind-5 notice the firmware did not
see.
- *Depends on it:* FW-4's fence; the serial stream's drop flag
  (`HOST_INTERFACE.md`, status byte).

**FW-6 — SET_ADDRESS order.** For SET_ADDRESS(n):
1. the chip ACKs the SETUP;
2. the firmware writes the pending address n (tag 2, `1aaaaaaa`);
3. the firmware loads the zero-length DATA1 (tag 3), which sets READY;
4. the host's IN to the **old** address gets the ZLP;
5. the host's ACK clears READY and the chip commits the address, in hardware,
   on the same edge — no firmware latency can make the chip answer the new
   address early or the old one late.
- *Depends on it:* the pending-address compare and the hardware commit
  (`src/project.v`), `test/run_usbaddr.py` (M7, M10, M10b: lost ZLP, lost ACK).

**FW-7 — Descriptor `bmAttributes` = `0x80`.** Bus-powered, **no remote
wakeup**: the chip has no remote-wakeup signalling, so it must not advertise
it (`0xA0` would).
- *Depends on it:* nothing on chip; the host-side model `usb_model.py` carries
  the same value (step 7a ruling Q8).

**FW-8 — The chip's clock for USB.** USB low speed needs the chip clock within
<!--gen:fw_usb_osc-->**±1.25 %** of nominal (at 60 MHz)<!--/gen-->,
two-sided: the USB jitter budget minus the bit-time quantisation at that clock.
The firmware sets the chip clock; it must not be trimmed or spread outside
this.
- *Depends on it:* `model/clock.py` `usb_osc_allowed`, check 8 of
  `model/gate_clock_consistency.py`. ⚠ The clock **source's** accuracy is a
  lock item (`SOURCE_PPM`, provisional).

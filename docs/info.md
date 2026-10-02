<!---
This file is used to generate your project datasheet. Please fill in the information
below and delete any unused sections.
-->

## How it works

A **protocol emulator**: a small reprogrammable machine that drives and samples pins
to timing precise enough to speak real serial protocols, so one piece of silicon can
be a UART, an SPI master or an I²C controller depending on the program loaded into
it — including protocols that did not exist when the chip was fabricated.

**What is built so far is the program-load path and the pin abstraction**, not the
protocol engine.

**Loading a program.** Loading and running are mutually exclusive, which is what
makes the pin budget work: while a program is being loaded, no protocol is being
emulated, so the eight bidirectional pins are free to act as the load data port.
That removes any need for a separate data bus, and the address bus is removed too by
**auto-increment** — programs are written front to back, one byte per `WR` pulse, and
the pointer advances itself. Total pin cost of the load interface: **zero**.

Mode select (`PROG_MODE`), the write strobe (`WR`) and the pointer reset (`PTR_RST`)
all come from the **dedicated** inputs, never from the bidirectional pins, so the
protocol pins stay free. `WR` is treated as an asynchronous pin strobe and passes
through a two-flop synchroniser and an edge detector.

Reprogramming is deliberately scoped as **halt, reload, resume** — there is no
mid-transaction program swap.

**Reading a program back.** In load mode the outputs echo the write pointer, which
confirms a write *landed*. In run mode the outputs present the byte at a slowly
advancing read pointer, which shows *what was written* — so a loaded program is
verifiable from outside the chip with nothing but a logic analyser.

**Open-drain pins.** I²C needs pins that pull low or release but never drive high.
This is done structurally: the output data for those pins is held low and only the
output *enable* is modulated, so driving a hard 1 on an open-drain pin is not
merely untested but impossible by construction.

⚠️ Consequently this build cannot drive a logic 1 on any bidirectional pin, so the
push-pull protocols (UART TX, SPI clock and data) are **not** supported yet. Those
need a per-pin drive-mode selection, which belongs with the protocol engine.

## How to test

Everything below is observable at the pins; no internal access is needed.

**Load and read back a program.**

1. Hold `PROG_MODE` (`ui[7]`) high and pulse `PTR_RST` (`ui[5]`) to zero the pointer.
2. Put a byte on `uio[7:0]` and pulse `WR` (`ui[6]`) high then low. Hold each level
   for at least three clocks — `WR` is synchronised, not sampled directly.
3. Watch `uo[5:0]`: it should read 1 after the first byte, 2 after the second, and so
   on. That is the pointer echo confirming each write landed.
4. Repeat for as many bytes as you want to load.
5. Drop `PROG_MODE` low. The outputs now present the loaded program, one byte at a
   time, advancing every 256 clocks. Compare against what you wrote.

**Check the open-drain behaviour.** Load bytes whose low two bits cover `00`, `01`,
`10` and `11`, then run. `uio[0]` and `uio[1]` should pull low when the corresponding
bit is 0 and release (float to the pull-up) when it is 1 — and should never be driven
high. With no external pull-ups those pins read as floating rather than high.

**Check the pins are released while loading.** Throughout `PROG_MODE`, all eight
bidirectional pins are inputs, which is what allows them to carry load data.

The automated test suite covers all of the above, including a check that the
open-drain enable genuinely asserts — otherwise "never drives high" would pass
trivially on a design that never drives anything.

## External hardware

None required for the load path or the readback.

For the open-drain pins, **pull-up resistors** (typically 4.7 kΩ to the supply) on
`uio[0]` and `uio[1]`, as any I²C bus needs. Without them a released pin floats
instead of reading high.

A logic analyser or an oscilloscope is useful for watching the program read back,
and a microcontroller or FPGA is a convenient way to drive the load sequence.

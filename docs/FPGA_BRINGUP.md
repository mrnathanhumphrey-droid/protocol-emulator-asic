# FPGA bring-up: the pre-run step

Board: Puzhi PA100T-EDU (xc7a100tfgg484-2). The board clock is set in `fpga/board.yaml` and nowhere else.

## ⛔ No board session on a pre-F1.5 bitstream (Wilson 11-09)

Every bitstream built before F1.5 has the board glue loading **v1's 256 bytes with no MAGIC**. The v2 chip refuses that load (CONFIG_ERR), so the board sits silent. F1.5 sizes the glue from `PE_STORE_BYTES` and regenerates the board images as v2. Only a bitstream built after it is worth taking to the bench.

## The rule (bundle F1, Wilson 11-09)

**Before any board session, the full Vivado build runs on Nathan's machine. Its WNS and WHS go in the table below.**

- CI's `test/gate_fpga_synth.py` only proves the build parses, elaborates and maps (Yosys `synth_xilinx`, all three variants). It doesn't check timing, and it never runs Vivado.
- A negative WNS or WHS is a failed build: `build.tcl` exits non-zero and writes no bitstream.
- A board session never runs a bitstream that has no row here.

## The store

**The board runs the chip's own store** (Wilson 11-09). `MEM_TYPE` stays at the chip's default, `"sram"`, and no store define is set.
- The arbitration, the one-entry write buffer and its forwarding, and the buffer-read slot in `pe_store.v`'s sram arm are the code that tapes out.
- Only the RAM core differs:
  - The TT flow's `PE_SRAM_MACRO` binds the IHP `RM_IHPSG13_1P_256x32_c2_bm_bist` macro.
  - Here, the inline core is that macro's behaviour.
- The inline core was compared against the PDK's `RM_IHPSG13_1P_core_behavioral_bm_bist.v` (cmos5l, identical to the g2 copy):
  - a write holds `dout`;
  - a read registers `mem[a]`, a one-cycle latency;
  - the macro's write-through needs WEN and REN together, which the store never issues;
  - neither has a reset.
- `test/gate_fpga_synth.py` asserts that this arm was built. It is red if `PE_MEM_FLOPS` or `PE_SRAM_MACRO` reaches this build.

## The command (admin PowerShell, from the repo root)

```powershell
# UART bring-up (default)
& C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat -mode batch -nojournal -source fpga/pa100t/build.tcl
# 1-Wire on J11
& C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat -mode batch -nojournal -source fpga/pa100t/build.tcl -tclargs ow
# I2C FRAM on J11
& C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat -mode batch -nojournal -source fpga/pa100t/build.tcl -tclargs i2c
```

To read the result:

```powershell
Select-String vivado.log -Pattern 'PE_FPGA: setup WNS'      # vivado.log lands where Vivado was started
Select-String fpga\build\pa100t\timing_summary.rpt -Pattern 'WNS\(ns\)' -Context 0,2
```

The output folder is `fpga/build/pa100t`, `pa100t_ow` or `pa100t_i2c`.

## The record

| date | commit | variant | clock | WNS (ns) | WHS (ns) | LUT / FF | bitstream | note |
|---|---|---|---|---|---|---|---|---|
| 2026-11-10 | **F2 (48f512f)** | UART | **60 MHz** | +4.639 | +0.092 | 9,414 / 3,395 | `fpga/build/pa100t/pa100t_top.bit` (sha256 0b79eba89afac536…) | **The board at the chip's own clock** (MMCM ×6, VCO 1200, /20). Image `uart_rx_board.hex`, rebuilt from CLK_HZ (T 521), byte-identical to the chip bench's `test/uart_rx_image.hex`. Loader, 1-Wire, I2C and UART-rx sims green at 60 MHz; fpga-synth green. Supersedes F1.5 for the bench. |
| 2026-11-09 | **F1.5 (485fb29)** | UART | 50 MHz | +7.466 | +0.079 | 9,391 / 3,390 | `fpga/build/pa100t/pa100t_top.bit` (sha256 e6678fce27aa02fe…) | **First bitstream fit for the bench**: the glue loads the whole v2 store (512 bytes, MAGIC); sims green with exact load checks. 224 LUTs as memory (the RAM core plus the 512-byte boot ROM / PC buffer). |
| 2026-11-09 | F1 (work/fpga-f1, on 73a387a) | UART | 50 MHz | +6.970 | +0.078 | 9,335 / 3,388 | `fpga/build/pa100t/pa100t_top.bit` | **F1 as ruled: the chip's own "sram" store** (no store define). The RAM core maps to 176 LUTs of distributed RAM, not block RAM (its byte-mask merge reads the array asynchronously). |
| 2026-11-09 | F1 draft (1ea33ba) | UART | 50 MHz | +7.316 | +0.082 | 9,399 / 3,378 | superseded | Withdrawn draft with `PE_MEM_FLOPS` (the flop store). Kept for comparison. |
| 2026-11-09 | 73a387a + scratch | UART | 60 MHz | +4.586 | +0.069 | 9,406 / 3,383 | scratch only | **Not F1.** Trial for F2: scratch copy with MMCM ×6 and `clock_hz` 60 MHz, plus the F1 fixes. Not for board use. |

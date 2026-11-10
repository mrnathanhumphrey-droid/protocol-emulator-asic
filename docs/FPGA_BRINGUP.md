# FPGA bring-up: the pre-run step

Board: Puzhi PA100T-EDU (xc7a100tfgg484-2). The board clock is set in `fpga/board.yaml` and nowhere else.

## The rule (bundle F1, Wilson 11-09)

**Before any board session, the full Vivado build runs on Nathan's machine. Its WNS and WHS go in the table below.**

- CI's `test/gate_fpga_synth.py` only proves the build parses, elaborates and maps (Yosys `synth_xilinx`, all three variants). It doesn't check timing, and it never runs Vivado.
- A negative WNS or WHS is a failed build: `build.tcl` exits non-zero and writes no bitstream.
- A board session never runs a bitstream that has no row here.

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
| 2026-11-09 | F1 (work/fpga-f1, uncommitted on 73a387a) | UART | 50 MHz | +7.316 | +0.082 | 9,399 / 3,378 | `fpga/build/pa100t/pa100t_top.bit` | The F1 build itself: first clean Vivado build since 11-07. |
| 2026-11-09 | 73a387a + scratch | UART | 60 MHz | +4.586 | +0.069 | 9,406 / 3,383 | scratch only | **Not F1.** Trial for F2: scratch copy with MMCM ×6 and `clock_hz` 60 MHz, plus the F1 fixes. Not for board use. |

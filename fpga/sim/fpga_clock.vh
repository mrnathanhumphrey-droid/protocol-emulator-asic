// fpga_clock.vh -- THE FPGA BENCH CLOCK, for target `fpga` (Wilson 11-03).
// ⛔ GENERATED: `python model/gate_clock_consistency.py --write` writes the
// default below from fpga/board.yaml clock_hz, and the gate fails if it
// disagrees. Never typed: every FPGA bench used to say `always #10 clk`.
// ⭐ `-DPE_FPGA_CLK_HZ=<Hz>` runs a bench at another board clock. Benches pass
// `.CLK_HZ(PE_FPGA_CLK_HZ)` to pe_fpga_core, which sizes the chip for it.
// Included INSIDE the bench module.
`ifndef PE_FPGA_CLK_HZ
`define PE_FPGA_CLK_HZ 60000000
`endif
localparam integer PE_FPGA_CLK_HZ   = `PE_FPGA_CLK_HZ;
localparam integer PE_CLK_PERIOD_PS = 1000000000 / (`PE_FPGA_CLK_HZ / 1000);
localparam real    PE_CLK_NS        = PE_CLK_PERIOD_PS / 1000.0;
localparam real    PE_CLK_HALF_NS   = PE_CLK_PERIOD_PS / 2000.0;

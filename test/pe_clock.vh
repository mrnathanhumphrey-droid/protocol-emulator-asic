// pe_clock.vh -- THE BENCH CLOCK, for target `chip` (Wilson 11-03).
// ⛔ GENERATED: `python model/gate_clock_consistency.py --write` writes the
// default below from info.yaml clock_hz through model/clock.py (whole ps,
// rounded down -- src/project.v's CLK_PERIOD_PS), and the gate fails if it
// disagrees. Never typed: every bench used to say `always #10 clk`, 50 MHz.
// ⭐ `-DPE_CLK_PS=<ps>` runs a bench at another clock (the cross-clock gate);
// a bench that also passes `.CLK_PERIOD_PS(PE_CLK_PERIOD_PS)` to the dut sizes
// the chip for it too. Included INSIDE the bench module.
`ifndef PE_CLK_PS
`define PE_CLK_PS 16666
`endif
localparam integer PE_CLK_PERIOD_PS = `PE_CLK_PS;
localparam real    PE_CLK_NS        = `PE_CLK_PS / 1000.0;
localparam real    PE_CLK_HALF_NS   = `PE_CLK_PS / 2000.0;
// the 1 ns phase bins one period holds (model/clock.py phases()): 20 / 17
localparam integer PE_PHASES        = (`PE_CLK_PS + 999) / 1000;

/* tb_trace.v -- emit a per-cycle PORT trace, for cross-simulator comparison.
 *
 * THE ONE CLAIM: two independent simulators, given the same RTL and the same
 * stimulus, produce byte-identical traces -- and a disagreement is a real tool
 * or netlist problem rather than a modelling one, because both sides are the
 * same design.
 *
 * ⭐⭐ PORTS ONLY, AND THAT IS A HARD CONSTRAINT RATHER THAN A PREFERENCE. The
 * same bench has to run against the GATE-LEVEL NETLIST, which has no internal
 * signal names at all -- `dut.u_eng.l_armed` does not exist after synthesis.
 * Every other bench in this project reaches inside (tb_smoke reads
 * `jitter_max`, tb_edge reads `l_armed`), which is right for what they measure
 * and makes them RTL-only. This one trades that away deliberately so one
 * artefact covers RTL, Verilator and GL.
 *
 * ⛔ AND IT IS WHY THE COMPARISON NEEDS NO GOLDEN MODEL. Per Wilson's Q1, the
 * simulator-vs-simulator arm compares resolved driven pin values per cycle and
 * nothing else; the two engines are each other's witness. Bringing the golden
 * model in here would mean growing it into a cycle-accurate second
 * implementation of the pipeline, which Law 1 says is worth nothing.
 *
 * ⛔⛔ UNINITIALISED STATE IS THE FIRST THING THIS WOULD HAVE TRIPPED ON.
 * iverilog starts a flop at X; Verilator at 0 or at a per-flop random pattern.
 * `model/gate_reset_audit.py` had to come first and name all 2,087 unreset
 * flops before a disagreement here could mean anything -- and the seed sweep
 * (>= 3 `--x-initial unique` seeds, traces identical) is the RUNTIME check
 * behind that allowlist's otherwise-only-stated write-before-read reasons.
 *
 * ⚠ X IS PRINTED AS A DISTINCT TOKEN, not folded to 0 or 1. iverilog can emit
 * X and Verilator cannot, so a trace containing X will differ between them BY
 * CONSTRUCTION -- which is information, not noise: it means a port is driven
 * from something uninitialised and the comparison is not yet meaningful.
 */

`default_nettype none
`timescale 1ns / 1ps

module tb_trace;

  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00;
  reg  [7:0] uio_drv = 8'h00;
  reg  [7:0] uio_oe_tb = 8'h00;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in;

  // the resolved bus, same semantics as tb_edge: two active drivers -> X
  genvar b;
  generate
    for (b = 0; b < 8; b = b + 1) begin : g_bus
      assign uio_in[b] = (uio_oe[b] && uio_oe_tb[b])
                       ? ((uio_out[b] === uio_drv[b]) ? uio_out[b] : 1'bx)
                       : uio_oe[b]    ? uio_out[b]
                       : uio_oe_tb[b] ? uio_drv[b]
                       : 1'b1;
    end
  endgenerate

  always #10 clk = ~clk;

  localparam integer IMG_MAX = 256;
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;

  reg [7:0]  img [0:IMG_MAX-1];
  integer    img_bytes, i, cyc, fd, ncyc;
  reg [8*64-1:0] imgfile, outfile;

  // ⛔ A SINGLE FORMATTING FUNCTION, so the two simulators cannot differ in
  // how they RENDER a value and have that look like a design disagreement.
  // `%b` on an 8-bit vector prints X as `x`, which is exactly the distinct
  // token the header asks for.
  task emit;
    begin
      $fwrite(fd, "%0d %b %b %b\n", cyc, uo_out, uio_out, uio_oe);
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) imgfile = "test/smoke_image.hex";
    if (!$value$plusargs("OUT=%s", outfile)) outfile = "trace.txt";
    if (!$value$plusargs("NCYC=%d", ncyc))   ncyc = 2000;

    // ⛔⛔ THE LENGTH IS PASSED IN, NOT DERIVED FROM UNINITIALISED STATE, AND
    // THE REASON IS A BUG THIS BENCH ALREADY HAD. tb_smoke derives it by
    // scanning for the first X (`$readmemh` leaves unwritten entries X), which
    // is correct in iverilog and SILENTLY WRONG in Verilator: Verilator
    // initialises the array to 0, so every one of the 256 entries looks
    // written and the derivation returned 256 instead of 51.
    // ⭐ The provenance header caught it -- added for the clobber hazard, it
    // reported `bytes=256` against iverilog's `bytes=51` before a single trace
    // line was compared. A cross-simulator bench cannot depend on
    // uninitialised-array semantics, which is the same X-vs-zero hazard the
    // reset audit exists for, inside the bench itself.
    if (!$value$plusargs("NBYTES=%d", img_bytes)) begin
      // ⛔ SEPARATE $display CALLS: Verilog has NO C-style adjacent string
      // concatenation, and this project has made that mistake before.
      $display("tb_trace: FATAL -- +NBYTES=<n> is required.");
      $display("  The image length must be passed explicitly; deriving it");
      $display("  from unwritten-array state is simulator-dependent.");
      $finish;
    end
    $readmemh(imgfile, img);

    fd = $fopen(outfile, "w");
    // ⭐ The header records what produced the trace. A trace file with no
    // provenance is the clobber hazard the C/J measurements already hit once.
    $fwrite(fd, "# img=%0s bytes=%0d ncyc=%0d\n", imgfile, img_bytes, ncyc);

    // ⛔⛔⛔ EVERY EDGE IN THIS BENCH IS A NEGEDGE, AND THAT IS WHAT MAKES THE
    //    TWO SIMULATORS COMPARABLE AT ALL. Driving stimulus in the SAME
    //    TIMESTEP as the posedge is a race: the DUT samples at that posedge,
    //    and whether it sees the old or the new value depends on the
    //    simulator's region ordering. The iverilog DUT saw the OLD value and
    //    the 2-state one saw the NEW one, so its program ran ONE CYCLE EARLY:
    //    `vl[n] == iv[n+1]` with EXACTLY 0 mismatches across all 1500 cycles
    //    once the shift was applied.
    // ⛔ AND NO COMMENT LINE HERE MAY BEGIN WITH THAT TOOL'S NAME: such a
    //    line is read as a LINT PRAGMA, case- and whitespace-insensitively,
    //    and then rejected as an unknown one. This paragraph broke the build
    //    THREE TIMES -- as the explanation, as the warning about the
    //    explanation, and as the quoted error text -- because each rewrite
    //    rewrapped the name onto the start of a line. A comment is not inert.
    //    The build failure is itself the standing guard, so no gate is owed.
    // ⚠ THE FIRST FIX WAS THE WRONG HALF. Seeing the offset, I moved only the
    //    SAMPLING off the edge; the traces stayed one cycle apart because the
    //    race was upstream in the stimulus. A pure shift with zero residual is
    //    the signature of a whole program displaced, not of a sampled value.
    // ⇒ The clock is driven off the posedge and the bench lives entirely on
    //   the negedge: inputs change half a period before the DUT samples them,
    //   and outputs are read half a period after it drove them. No bench
    //   event ever shares a timestep with the active edge.
    cyc = 0;
    repeat (4) @(negedge clk);
    rst_n = 1;
    @(negedge clk);

    // ---- LOAD ----------------------------------------------------------
    ui_in[PIN_PROG] = 1'b1;
    uio_oe_tb = 8'hFF;
    ui_in[PIN_PTR] = 1'b1; @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; @(negedge clk);
    for (i = 0; i < img_bytes; i = i + 1) begin
      uio_drv = img[i];
      @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end

    // ---- RUN, tracing every cycle --------------------------------------
    ui_in[PIN_PROG] = 1'b0;
    uio_oe_tb = 8'h00;              // release the bus; the engine owns it
    uio_drv   = 8'hFF;
    for (i = 0; i < ncyc; i = i + 1) begin
      @(negedge clk);
      cyc = cyc + 1;
      emit;
    end

    $fclose(fd);
    $display("tb_trace: %0d cycles -> %0s", ncyc, outfile);
    $finish;
  end

  tt_um_protocol_emulator dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

endmodule

`default_nettype wire

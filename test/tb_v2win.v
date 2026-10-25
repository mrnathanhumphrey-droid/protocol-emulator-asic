/* tb_v2win.v -- THE SYNCHRONIZER WINDOW, MEASURED (Wilson, WF2 #8 / V2).
 *
 * A host push crosses a synchronizer before the queue sees it, so a byte
 * pushed just before a TX byte slot may or may not be taken. V2 (pins only)
 * must call such a slot AMBIGUOUS rather than guess, and HOST_INTERFACE
 * must state how early a byte has to be pushed to be guaranteed taken. This
 * bench measures the chip's side of that, instead of assuming it.
 *
 * One clocked push-pull SHIFT lane (lane 0, MOSI on uo_out[2], SCK on
 * uo_out[1]) loops over an EMPTY queue, so every slot underruns (sends 0s).
 * +LEAD=k pushes ONE byte 0xFF whose LOW nibble is seen on the pins (the
 * PUSH rise, sampled at a posedge -- V2's decode instant) exactly k cycles
 * before slot +SLOT's writeback (its first LOW, found in a dry run with no
 * push: +DRY=1 prints every slot's writeback cycle). The verdict line says
 * whether that slot sent the pushed byte (its first bit 1) or underran (0).
 *   +DRY=1           print `SLOT j WB c` for the first slots and stop
 *   +LEAD=k +AT=c    push so the low nibble is decoded at cycle c - k
 * Verdict: `V2WIN lead=k taken=0|1`.
 */
`default_nettype none
`timescale 1ns / 1ps
module tb_v2win;
  reg        clk = 0, rst_n = 0, ena = 1;
  reg  [7:0] ui_in = 8'h00, uio_drv = 8'hFF;
  wire [7:0] uo_out, uio_out, uio_oe;
  wire [7:0] uio_in = (uio_oe & uio_out) | (~uio_oe & uio_drv);
  localparam integer PIN_PROG = 7, PIN_PTR = 5, PIN_WR = 6;
`include "test/store_filler.vh"   // v2: PE_STORE_BYTES, never a typed 256
  reg  [7:0] img [0:PE_STORE_BYTES-1];
  reg [8*256-1:0] imgfile;
  integer    i, cyc = 0, dry, lead, at, nslot = 0, taken = -1, slot_wb = -1;
  // +PHPS=p (audit item 2, 10-22): the LOW-nibble PUSH rise moves p ps after
  // its negedge -- anywhere from 10 ns before the sampling posedge to 9 ns
  // after one -- and both instants are printed in ns, so the window is
  // measured edge -> slot, not posedge -> slot. 0 = the historical phase.
  integer    phps, walk_now = 0;
  real       t_rise = -1.0, t_slot = -1.0;
  always #10 clk = ~clk;

  tt_um_protocol_emulator #(.SPL(2)) dut (
      .ui_in(ui_in), .uo_out(uo_out), .uio_in(uio_in), .uio_out(uio_out),
      .uio_oe(uio_oe), .ena(ena), .clk(clk), .rst_n(rst_n));

  // ⚠ ONE BLOCK for the cycle count, the slot detection and the sample, so
  // no block reads another's same-edge blocking write (ruling RA3). The
  // initial block reads `cyc` only on negedges.
  // a slot = a clocked SHIFT's first LOW writeback on lane 0; the slot's
  // first bit is read on the pin at its first HIGH
  always @(posedge clk) if (rst_n) begin
    cyc = cyc + 1;
    if (ui_in[PIN_PROG] === 1'b0 && dut.u_eng.st === 2'd2
        && dut.u_eng.cur == 0) begin
      if (dut.u_eng.ck_shift === 1'b1 && dut.u_eng.ck_is_low === 1'b1
          && dut.u_eng.l_ckbit[0] == 0) begin
        if (dry && nslot < 8) $display("SLOT %0d WB %0d", nslot, cyc);
        if (!dry && cyc == at) begin slot_wb = cyc; t_slot = $realtime; end
        nslot = nslot + 1;
      end
      if (!dry && slot_wb >= 0 && taken < 0 && dut.u_eng.ck_is_high === 1'b1)
        taken = uo_out[2];
    end
  end

  task nib(input [3:0] n, input integer when);   // PUSH rise sampled at `when`
    begin
      ui_in[4:1] = n; ui_in[5] = 1'b0; ui_in[0] = 1'b0;
      while (cyc < when - 1) @(negedge clk);
      @(negedge clk);
      if (walk_now && phps > 0) #(phps / 1000.0);
      ui_in[PIN_WR] = 1'b1;                       // seen at the next posedge
      if (walk_now) t_rise = $realtime;
      @(negedge clk); @(negedge clk); @(negedge clk);
      ui_in[PIN_WR] = 1'b0;
    end
  endtask

  initial begin
    if (!$value$plusargs("IMG=%s", imgfile)) begin $display("FATAL +IMG"); $finish; end
    if (!$value$plusargs("DRY=%d", dry)) dry = 0;
    if (!$value$plusargs("LEAD=%d", lead)) lead = 0;
    if (!$value$plusargs("AT=%d", at)) at = 0;
    if (!$value$plusargs("PHPS=%d", phps)) phps = 0;
    $readmemh(imgfile, img);
    repeat (4) @(negedge clk); rst_n = 1; @(negedge clk);
    ui_in[PIN_PROG] = 1'b1;
    repeat (3) @(negedge clk); ui_in[PIN_PTR] = 1'b1; repeat (3) @(negedge clk);
    ui_in[PIN_PTR] = 1'b0; repeat (3) @(negedge clk);
    for (i = 0; i < 256; i = i + 1) begin
      uio_drv = img[i];
      @(negedge clk); @(negedge clk); ui_in[PIN_WR] = 1'b1;
      @(negedge clk); @(negedge clk); @(negedge clk); ui_in[PIN_WR] = 1'b0;
      @(negedge clk);
    end
    ui_in[PIN_PROG] = 1'b0; uio_drv = 8'hFF;
    if (dry) begin
      repeat (4000) @(posedge clk);
      $finish;
    end
    nib(4'hF, at - lead - 40);                    // high nibble, well before
    walk_now = 1;
    nib(4'hF, at - lead);                         // low nibble: decoded at at-lead
    walk_now = 0;
    wait (taken >= 0 || cyc > at + 2000);
    $display("V2WIN lead=%0d taken=%0d", lead, taken < 0 ? 0 : taken);
    $display("V2WIN-NS phps=%0d rise_ns=%0.3f slot_ns=%0.3f edge_to_slot_ns=%0.3f",
             phps, t_rise, t_slot, t_slot - t_rise);
    $finish;
  end
endmodule
`default_nettype wire

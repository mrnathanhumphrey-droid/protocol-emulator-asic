/* od_bus.vh -- THE ONE OPEN-DRAIN BUS RESOLUTION, for every bench.
 *
 * ⛔⛔ WHY THIS FILE EXISTS: THREE MODELS OF THE SAME WIRE. The `uio` bank's
 * resolution was written out in `tb_trace.v` (over `tb_oe`/`tb_val`), again in
 * `tb_edge.v` (over `uio_oe_tb`/`uio_drv`) -- `tb_trace`'s own comment says
 * "same semantics as tb_edge", which is a copy admitting it is a copy -- and a
 * THIRD time in Python, inside `test.py`, as a cocotb coroutine. Four private
 * copies of a slot index have already cost this project a published column;
 * three copies of the electrical layer is the same shape on the one thing that
 * decides whether a protocol claim means anything.
 * ⚠ AND THE PYTHON COPY WAS WRONG for most of its life: it set `uio_in` to a
 * CONSTANT 0xFF, modelling the pull-ups but not the DUT's pull-downs, so the
 * bus never TRANSITIONED. It went unnoticed until the engine started parking on
 * an observed SCL rise -- a bench that cannot produce a rise cannot test one.
 *
 * THE SEMANTICS, and the X is the point:
 *   both sides driving and DISAGREEING   -> X  (contention, reported)
 *   both sides driving and agreeing      -> that value
 *   one side driving                     -> that side
 *   nobody driving                        -> 1, the pull-up
 * ⛔ TWO DRIVERS THAT AGREE ARE INDISTINGUISHABLE FROM ONE, which is exactly
 * why ENABLE OVERLAP, and not X, is the contention detector elsewhere. A bus
 * model that silently picks a winner cannot detect contention at all, and that
 * is the class 1.6r closed on MISO.
 *
 * WHAT THE INCLUDING SCOPE MUST PROVIDE:
 *   wire [7:0] uio_oe, uio_out    from the DUT
 *   wire [7:0] ob_oe, ob_val      the BENCH/PEER side: enable and value
 *   wire [7:0] uio_in             resolved HERE, so it must be a wire
 *
 * ⭐ A BENCH KEEPS ITS OWN NAMES by aliasing into `ob_oe`/`ob_val` on the line
 * before the include. The resolution itself exists once.
 */
genvar ob_b;
generate
  for (ob_b = 0; ob_b < 8; ob_b = ob_b + 1) begin : g_od_bus
    // ⛔ M_BUS_NO_PULLDOWN drops the DUT's pull-down from this ONE model, so a
    // released line reads high even while the part is pulling it low. It must
    // break the cocotb suite AND the Verilog benches together -- that both see
    // it is the whole claim of having one model.
`ifdef M_BUS_NO_PULLDOWN
    assign uio_in[ob_b] = ob_oe[ob_b] ? ob_val[ob_b] : 1'b1;
`else
    assign uio_in[ob_b] = (uio_oe[ob_b] && ob_oe[ob_b])
                        ? ((uio_out[ob_b] === ob_val[ob_b]) ? uio_out[ob_b]
                                                            : 1'bx)
                        : uio_oe[ob_b] ? uio_out[ob_b]
                        : ob_oe[ob_b]  ? ob_val[ob_b]
                        : 1'b1;                  // pull-up / idle high
`endif
  end
endgenerate

module ttop(input clk, input rst, input we, input [3:0] a, input [7:0] d, output [7:0] q, output [7:0] cnt_o, output z);
  reg [7:0] cnt; reg [7:0] mem [0:15];
  always @(posedge clk) if (rst) cnt <= 8'd0; else cnt <= cnt + 8'd1;
  always @(posedge clk) if (we) mem[a] <= d;
  assign q = mem[a]; assign cnt_o = cnt; assign z = &cnt & we;
endmodule

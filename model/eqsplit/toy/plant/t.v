module ttop(input clk, input rst, input we, input [3:0] a, input [7:0] d, output [7:0] q, output [7:0] cnt_o, output z);
  reg [7:0] cntn; reg [7:0] mem [0:15];
  always @(posedge clk) if (rst) cntn <= 8'hFF; else cntn <= ~(~cntn + 8'd1);
  always @(posedge clk) if (we) mem[a] <= d;
  assign q = mem[a]; assign cnt_o = ~cntn; assign z = &(~cntn) & ~we;
endmodule

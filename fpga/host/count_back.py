"""How many bytes does the running program return per UART frame? (board check)

Sends N frames one at a time and counts the bytes that come back: 2 per frame
for the normal UART-rx program (data + stop byte), 1 for the nostop variant --
which is how a PC load is proven to have changed the running program.

Usage:  python fpga/host/count_back.py COM3 [N]
"""
import sys
import time

import serial

port = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
s = serial.Serial(port, 115200, timeout=0.2)
s.reset_input_buffer()
back = b""
for i in range(n):
    s.write(bytes([0x40 + i]))
    s.flush()
    time.sleep(0.005)
    back += s.read(8)
time.sleep(0.05)
back += s.read(64)
s.close()
print("COUNT-BACK: %d frame(s) -> %d byte(s) = %.2f per frame; first %s"
      % (n, len(back), len(back) / float(n), back[:8].hex()))

"""gen_usbdev_fpga -- the USB build's ROM image (Wilson 11-14, the USB keyboard bring-up).

Writes test/usbdev.py's device program exactly as the chip benches write it
(pe_isa.write_image(path, usbdev.image()) -- run_usbaddr's usbdev_dev.hex, the image the
branch budget certificate, the lane certificate and the row-3 witness are about), so the
board runs the certified bytes. Recipe line in test/artefacts.sha256.

Usage: python fpga/sim/gen_usbdev_fpga.py [out.hex]   (default fpga/images/usbdev_fpga.hex)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(ROOT, "test"), os.path.join(ROOT, "model")]
import pe_isa as I  # noqa: E402
import usbdev as V  # noqa: E402


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "fpga", "images",
                                                               "usbdev_fpga.hex")
    I.write_image(out, V.image())
    print("wrote %s" % out)


if __name__ == "__main__":
    main()

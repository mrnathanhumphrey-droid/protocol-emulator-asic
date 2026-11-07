"""
LibreLane plugin: extend the tile's Metal4 power stripes over the IHP SRAM
macro (see odb_stripes.py for what the step does and why).

Based on Ken Pettit's librelane_plugin_prism_pdn.py from
https://github.com/kdp1965/ihp-um-janestreet-prism.

LibreLane loads this file automatically, as it imports any librelane_plugin_*
module from the directory it runs in (the repository root). The "meta" block
in src/config.json runs the step right after OpenROAD.GeneratePDN.
"""
import os
from decimal import Decimal

from librelane.config import Variable
from librelane.steps import Step
from librelane.steps.odb import OdbpyStep

HERE = os.path.dirname(os.path.abspath(__file__))


@Step.factory.register()
class ExtendPowerStripes(OdbpyStep):
    id = "Project.ExtendPowerStripes"
    name = "Extend Power Stripes Over the IHP SRAM"

    config_vars = [
        Variable("EXTEND_STRIPES_LAYER", str, "The tile's vertical single-layer PDN layer, which is also the layer of the IHP SRAM's power columns.", default="Metal4"),
        Variable("EXTEND_STRIPES_CLEARANCE", Decimal, "Spacing kept between a drawn stripe and the tile's signal pins on the stripe layer.", units="µm", default=Decimal("0.24")),
        Variable("EXTEND_STRIPES_PIN_FACE_MARGIN", Decimal, "No rail via stack within this distance of a macro edge that carries pins (the stack would block the pins' escape); 0 leaves pdngen's stacks alone.", units="µm", default=Decimal("3")),
        Variable("EXTEND_STRIPES_SRAM_ARRAY_EVERY_OTHER", bool, "In each bit-cell array of an IHP SRAM, add a VPWR/VGND stripe pair on every other available pair position (the grid's pairs stay; the macro's standard-cell band is left as the grid gives it).", default=False),
    ]

    def get_script_path(self):
        return os.path.join(HERE, "odb_stripes.py")

    def get_command(self):
        cmd = super().get_command() + [
            "--layer", self.config["EXTEND_STRIPES_LAYER"],
            "--clearance", str(self.config["EXTEND_STRIPES_CLEARANCE"]),
            "--pin-face-margin", str(self.config["EXTEND_STRIPES_PIN_FACE_MARGIN"]),
        ]
        if self.config["EXTEND_STRIPES_SRAM_ARRAY_EVERY_OTHER"]:
            cmd += ["--sram-array-every-other"]
        return cmd

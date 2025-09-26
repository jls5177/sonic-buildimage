# led_control.py
#
# Platform-specific LED control functionality for SONiC
#

import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from sonic_led.led_control_base import LedControlBase
    import threading
    import logging
    import struct
    import time
    import syslog
    from socket import *
    from select import *
    from domutil import Wedge400DomIO, DomFpgaLedColor
except ImportError as e:
    raise ImportError(str(e) + " - required module not found")


class LedControl(LedControlBase):
    """Platform specific LED control class"""
    SONIC_PORT_NAME_PREFIX = "Ethernet"
    SONIC_ALIAS_PORT_NAME_PREFIX = "etp"

    def __init__(self):
        self.w400 = Wedge400DomIO()

    def _port_name_to_index(self, port_name):
        if port_name.startswith(self.SONIC_PORT_NAME_PREFIX):
            # Strip "Ethernet" off port name
            phy_idx = int(port_name[len(self.SONIC_PORT_NAME_PREFIX):])
            if phy_idx < 128:
                return phy_idx / 8
            return  ((phy_idx-128) / 4) + 16
        if port_name.startswith(self.SONIC_ALIAS_PORT_NAME_PREFIX):
            # Strip "etp" off the port name
            port_idx = int(port_name[len(self.SONIC_ALIAS_PORT_NAME_PREFIX):])
            return port_idx
        return -1

    def _port_state_to_mode(self, state) -> tuple[DomFpgaLedColor, bool]:
        if state == "up":
            return DomFpgaLedColor.GREEN, True  # port linkup, led is green
        else:
            return DomFpgaLedColor.OFF, False  # port linkdown, led is off

    def port_link_state_change(self, portname, state):
        port_idx = self._port_name_to_index(portname)
        state, blink = self._port_state_to_mode(state)
        self.w400.set_led_state(port_idx, state=state, blink=blink)

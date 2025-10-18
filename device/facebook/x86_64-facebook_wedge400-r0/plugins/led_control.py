# led_control.py
#
# Platform-specific LED control functionality for SONiC
#

try:
    from sonic_led.led_control_base import LedControlBase
    import threading
    import os
    import logging
    import struct
    import time
    import syslog
    from socket import *
    from select import *
    from wedge400.domutil import Wedge400DomIO, DomFpgaLedColor
except ImportError as e:
    raise ImportError(str(e) + " - required module not found")


class LedControl(LedControlBase):
    """Platform specific LED control class"""
    SONIC_PORT_NAME_PREFIX = "Ethernet"
    SONIC_ALIAS_PORT_NAME_PREFIX = "etp"
    MAX_FRONT_PANEL_PORTS = 48
    STARTING_PHY_INDEX_200G = 128
    UPDATE_ALL_PORTS_ON_CHANGE = True

    def __init__(self):
        self.w400 = Wedge400DomIO()
        self.port_state = dict()

    def _port_name_to_index(self, port_name):
        if port_name.startswith(self.SONIC_PORT_NAME_PREFIX):
            # Strip "Ethernet" off port name
            phy_idx = int(port_name[len(self.SONIC_PORT_NAME_PREFIX):])
            if phy_idx < self.STARTING_PHY_INDEX_200G:
                index = int(phy_idx / 8)
                subport = (phy_idx % 8) + 1
                return index, subport
            index = (phy_idx - self.STARTING_PHY_INDEX_200G) / 4
            subport = (index % 4) + 1
            return int(index), subport
        if port_name.startswith(self.SONIC_ALIAS_PORT_NAME_PREFIX):
            # Strip "etp" off the port name
            port_idx = int(port_name[len(self.SONIC_ALIAS_PORT_NAME_PREFIX):])
            if "/" in port_idx:
                port_idx, subport_idx = port_idx.split("/")
            return int(port_idx), int(subport_idx)
        return -1

    def _port_state_to_mode(self, state, port_idx, subport) -> tuple[DomFpgaLedColor, bool]:
        if state == "up":
            if subport != 1:
                return DomFpgaLedColor.BLUE, False  # only the first subport shows green when link is up
            return DomFpgaLedColor.GREEN, False  # port linkup, led is green
        elif port_idx in self.w400.tcvr_present:
            return DomFpgaLedColor.YELLOW, True  # port is present but link is down, led is yellow
        else:
            return DomFpgaLedColor.OFF, False  # port linkdown, led is off

    def port_link_state_change(self, portname, state):
        port_idx, subport = self._port_name_to_index(portname)
        if port_idx >= self.MAX_FRONT_PANEL_PORTS:
            return
        
        self.port_state[port_idx] += 1 if state == "up" else 0

        if not self.UPDATE_ALL_PORTS_ON_CHANGE:
            if port_idx in self.w400.tcvr_present:
                # force the transceiver to be powered on when link is up
                self.w400.release_tcvr_reset(port_idx)
                self.w400.release_tcvr_lp_mode(port_idx)
            led_state, blink = self._port_state_to_mode(state, port_idx, subport)
            self.w400.set_led_state(port_idx, state=led_state, blink=blink)
        else:
            self.w400.clear_all_tcvr_reset()
            self.w400.clear_all_tcvr_lp_mode()
            for idx in range(self.MAX_FRONT_PANEL_PORTS):
                curr_state = "up" if self.port_state.get(idx, 0) > 0 else "down"
                led_state, blink = self._port_state_to_mode(curr_state, idx, 1)
                self.w400.set_led_state(idx, state=led_state, blink=blink)

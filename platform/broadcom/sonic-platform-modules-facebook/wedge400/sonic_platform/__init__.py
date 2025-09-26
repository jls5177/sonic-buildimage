"""
sonic_platform
================
Facebook Wedge400 platform implementation package exposed to SONiC platform
monitor (pmon) and related daemons. Provides the Platform class entry point
required by SONiC.

Structure
---------
Platform           High-level hardware access aggregation class required by SONiC

Future modules (fans, psu, chassis, thermal, eeprom, led, etc.) should be added
in this directory and imported lazily inside Platform to keep import time low.
"""
from .platform import Platform  # noqa: F401

__all__ = ["Platform"]

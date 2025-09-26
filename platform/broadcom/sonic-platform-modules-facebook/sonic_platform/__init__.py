# empty
"""Facebook Wedge400 SONiC platform package

This package is exposed to the system as 'sonic_platform' (see setup.py).
It provides the minimal objects expected by SONiC daemons so that pmon
can import the platform package and start device specific services (e.g. ledd).
"""

__all__ = ["platform"]

# Re-export (lazy) – platform.py will be added to provide Platform class
try:
	from . import platform  # noqa: F401
except Exception:
	# Allow build to proceed even if optional modules are not yet implemented
	pass

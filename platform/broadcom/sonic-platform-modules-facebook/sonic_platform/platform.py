"""Platform definition for Facebook Wedge400

Minimal stub sufficient to let SONiC services (pmon/ledd) import the
`sonic_platform` package. Extend with real chassis, PSU, fan, thermal
implementations as hardware support is added.
"""

try:
    from sonic_platform_base.platform_base import PlatformBase
except ImportError as e:  # pragma: no cover
    raise ImportError("{} - required module not found".format(e))


class Platform(PlatformBase):
    PLATFORM_NAME = "wedge400"

    def __init__(self):  # noqa: D401
        super(Platform, self).__init__()
        # Lazy import / placeholder until chassis module is implemented
        try:
            from .chassis import Chassis  # type: ignore
            self._chassis = Chassis()
        except Exception:
            self._chassis = None

    def get_chassis(self):  # noqa: D401
        return self._chassis

    def get_platform_info(self):
        return {"name": self.PLATFORM_NAME}

import mmap
import os
import struct
import time
from ctypes import c_uint32
from enum import IntEnum
from typing import Optional


class DomFpgaLedColor(IntEnum):
    """
    Led register map:
        [31:5] reserved
        [4:2] led color profile:
               (0-7) -> (white, cyan, blue, pink, red, orange, yellow, green)
        [1:1] led flash off/on
        [0:0] led off/on
    """
    OFF = 0x0
    WHITE = 0x01
    CYAN = 0x05
    BLUE = 0x09
    PINK = 0x0D
    RED = 0x11
    ORANGE = 0x15
    YELLOW = 0x19
    GREEN = 0x1D


class MmioDevice(object):
    """
    Simple wrapper around a PCIe resource MMIO region providing 32-bit access.

    - Opens the resource file (e.g., /sys/bus/pci/devices/0000:bb:dd.f/resource0)
    - mmaps the requested size (default 0x8000)
    - Exposes read32/write32 by byte offset
    - Supports context manager and explicit close
    """

    def __init__(self, resource_path: str, size: int = 0x8000):
        self._path = resource_path
        self._size = size
        # Ensure MMIO is enabled in PCI config space before mapping resource0
        try:
            self._ensure_mmio_enabled()
        except Exception:
            # Proceed even if we fail to flip the bit (may already be enabled)
            pass
        self._file = open(resource_path, "rb+")
        self._mmap = mmap.mmap(
            self._file.fileno(),
            self._size,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_WRITE | mmap.PROT_READ,
            offset=0,
        )
        # Create a 32-bit view into the mapping. 0x8000 bytes -> 0x2000 uint32s
        self._u32 = (c_uint32 * (self._size // 4)).from_buffer(self._mmap)

    def close(self) -> None:
        try:
            if hasattr(self, "_mmap") and self._mmap is not None:
                self._mmap.close()
        finally:
            if hasattr(self, "_file") and self._file is not None:
                self._file.close()
        self._mmap = None  # type: ignore
        self._file = None  # type: ignore

    def __del__(self):
        try:
            self.close()
        except Exception:
            # Suppress exceptions in GC path
            pass

    # Context manager helpers
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _ensure_mmio_enabled(self) -> None:
        """
        Ensure the PCIe device has Memory Space Enable (MSE) set in the
        PCI Command register so that BAR MMIO is accessible.
        """
        # Derive the PCI device directory from the resource path
        dev_dir = os.path.dirname(self._path)
        cfg_path = os.path.join(dev_dir, "config")
        if not os.path.exists(cfg_path):
            return
        with open(cfg_path, "rb+") as cfg:
            # Read 16-bit Command register at offset 0x04
            cfg.seek(4)
            data = cfg.read(2)
            if len(data) != 2:
                return
            (cmd,) = struct.unpack("<H", data)
            MSE = 0x2  # Memory Space Enable bit
            if (cmd & MSE) == 0:
                cmd |= MSE
                cfg.seek(4)
                cfg.write(struct.pack("<H", cmd))
                cfg.flush()

    def _check_offset(self, offset_bytes: int) -> int:
        if offset_bytes % 4 != 0:
            raise ValueError("MMIO offset must be 4-byte aligned")
        if not (0 <= offset_bytes < self._size):
            raise ValueError("MMIO offset out of range")
        return offset_bytes >> 2

    def read32(self, offset_bytes: int) -> int:
        idx = self._check_offset(offset_bytes)
        return int(self._u32[idx])

    def write32(self, offset_bytes: int, value: int) -> None:
        idx = self._check_offset(offset_bytes)
        self._u32[idx] = value & 0xFFFFFFFF


class DomFpga(MmioDevice):
    # DOM register map copied from pimutil.py to remove external dependency
    REG = {
        "revision": 0x0,
        "system_led": 0xC,
        "intr_status": 0x2C,
        "qsfp_present": 0x48,
        "qsfp_present_intr": 0x50,
        "qsfp_present_intr_mask": 0x58,
        "qsfp_intr": 0x60,
        "qsfp_intr_mask": 0x68,
        "qsfp_reset": 0x70,
        "qsfp_lp_mode": 0x78,
        "device_power_bad_status": 0x90,
        "port_led_color_profile": {
            0: 0x300,
            1: 0x300,
            2: 0x304,
            3: 0x304,
            4: 0x308,
            5: 0x308,
            6: 0x30C,
            7: 0x30C,
        },
        "port_led_control": {
            0: 0x310,
            1: 0x314,
            2: 0x318,
            3: 0x31C,
            4: 0x320,
            5: 0x324,
            6: 0x328,
            7: 0x32C,
            8: 0x330,
            9: 0x334,
            10: 0x338,
            11: 0x33C,
            12: 0x340,
            13: 0x344,
            14: 0x348,
            15: 0x34C,
            16: 0x350,
            17: 0x358,
            18: 0x360,
            19: 0x368,
            20: 0x370,
            21: 0x378,
            22: 0x380,
            23: 0x388,
        },
        "dom_control_config": 0x410,
        "dom_global_status": 0x414,
        "dom_data": 0x4000,
    }

    MMIO_SIZE = 0x8000

    def __init__(self, resource_path: str, reg_map: Optional[dict] = None):
        super().__init__(resource_path, size=self.MMIO_SIZE)
        if reg_map is not None:
            self.REG = reg_map

    def _resolve_offset(self, key):
        """
        Resolve a register key into a byte offset using REG.
        key can be:
        - int: returned as-is
        - str: top-level name or dot-separated path (e.g., 'mdio.config')
        - tuple/list: path components (e.g., ('mdio','config') or ('port_led_control', 3))
        """
        reg = self.REG
        if isinstance(key, int):
            return key
        if isinstance(key, str):
            path = key.split('.') if '.' in key else [key]
        elif isinstance(key, (tuple, list)):
            path = list(key)
        else:
            raise KeyError("Unsupported register key type")
        cur = reg
        for comp in path:
            # Allow numeric comps passed as strings
            if isinstance(comp, str) and comp.isdigit():
                comp_cast: int | str = int(comp)
            else:
                comp_cast = comp
            if isinstance(cur, dict):
                if comp_cast in cur:
                    cur = cur[comp_cast]
                else:
                    raise KeyError(f"Unknown register path component: {comp}")
            else:
                raise KeyError(f"Path goes through non-dict at component {comp}")
        if isinstance(cur, int):
            return cur
        raise KeyError("Register path did not resolve to an integer offset")

    def read_reg(self, key) -> Optional[int]:
        try:
            offset = self._resolve_offset(key)
        except KeyError:
            return None
        return self.read32(offset)

    def write_reg(self, key, value: int) -> bool:
        try:
            offset = self._resolve_offset(key)
        except KeyError:
            return False
        self.write32(offset, value)
        return True

    def set_led_state(self, port_idx: int, state: DomFpgaLedColor, blink: bool = False):
        led_state = state.value + (2 if blink else 0)
        self.write_reg(key=("port_led_control", port_idx), value=led_state)

    def clear_all_tcvr_reset(self) -> None:
        self.write_reg("qsfp_reset", 0x0)

    def trigger_qsfp_hard_reset(self, port_idx: int):
        orig_val = self.read_reg("qsfp_reset")
        new_val = orig_val | (1 << port_idx)
        self.write_reg("qsfp_reset", new_val)
        time.sleep(0.01)
        self.write_reg("qsfp_reset", orig_val)

    def release_qsfp_reset(self, port_idx: int):
        orig_val = self.read_reg("qsfp_reset")
        # 0 == release, 1 == hold in reset
        new_val = orig_val | ~(1 << port_idx)
        self.write_reg("qsfp_reset", new_val)

    @property
    def qsfp_present(self) -> int:
        return self.read_reg("qsfp_present")

    @property
    def qsfp_present_intr(self) -> int:
        return self.read_reg("qsfp_present_intr")

    @property
    def qsfp_present_intr_mask(self) -> int:
        return self.read_reg("qsfp_present_intr_mask")

    @property
    def registers(self):
        return self.REG

    def dump_registers(self, exclude: Optional[set[str] | list[str]] = None) -> dict:
        """
        Read and return all register values from this DomFpga as a dict mapping
        register names to values. Registers are named using dot-paths for nested
        maps (e.g., 'port_led_control.3').

        The following top-level registers are excluded by default as they either
        represent control or large data regions:
          - dom_control_config
          - dom_global_status
          - dom_data

        You can pass an additional iterable of names via `exclude` to skip other
        top-level registers as needed.
        """
        default_exclude = {"dom_control_config", "dom_global_status", "dom_data"}
        excluded = set(exclude) if exclude is not None else set()
        excluded |= default_exclude

        results: dict[str, int | None] = {}

        def walk(prefix: str, node, top_level: bool) -> None:
            if isinstance(node, int):
                # Leaf offset: read value (guard against read issues)
                try:
                    val = self.read32(node)
                except Exception:
                    val = None
                results[prefix] = val
                return
            if isinstance(node, dict):
                for k, v in node.items():
                    # Skip excluded top-level keys
                    if top_level and isinstance(k, str) and k in excluded:
                        continue
                    key_str = f"{prefix}.{k}" if prefix else str(k)
                    walk(key_str, v, top_level=False)

        walk("", self.REG, top_level=True)
        return results


class Wedge400DomIO(object):
    DEVICES = [
        "/sys/devices/pci0000:00/0000:00:03.0/0000:05:00.0/resource0",
        "/sys/devices/pci0000:00/0000:00:03.3/0000:08:00.0/resource0",
    ]

    MAX_PORTS = 48

    def __init__(self):
        self._fpgas: list[DomFpga] = []
        for path in self.DEVICES:
            if os.path.exists(path):
                self._fpgas.append(DomFpga(path))

    def _get_tcvr_led_group(self, tcvr_id: int) -> int:
        """
        Create groups of 4 LEDs to add a lock around each group
        Groups 0 thru 7 are on FPGA0 and 8 thru 15 are on FPGA1
        """
        if 0 <= tcvr_id < self.MAX_PORTS:
            return tcvr_id if tcvr_id < 16 else ((tcvr_id - 16) / 2)
        return 0

    def _get_fpga(self, tcvr_id: int) -> DomFpga | None:
        """
        The transciever ids are laid out ad follows on the front panel:
             0 -- 7  ,  8  --  15
            16 -- 31 , 32  --  47
        The mapping logic is based on this:
        transceiver [0, 7] + [16, 31] are accessed through the leftFpga and
        [8, 15] + [32, 47] are accessed through rightFpga. Furthermore [0, 15] are
        QSFP-DD uplink ports and [16, 47] are downlink QSFP ports.
        """
        if 0 <= tcvr_id < self.MAX_PORTS:
            fpga_idx = 0 if self._get_tcvr_led_group(tcvr_id) < 8 else 1
            return self._fpgas[fpga_idx]
        return None

    def _get_fpga_port_index(self, tcvr_id: int) -> int:
        """
         [0 .. 7] returns [16 .. 23]
         [8 .. 15] return [16 .. 23]
         [16 .. 31] returns [0 .. 15]
         [32 .. 47] returns [0 .. 15]
        """
        if 0 <= tcvr_id < self.MAX_PORTS:
            if tcvr_id < 8:
                return tcvr_id + 16
            if tcvr_id < 16:
                return tcvr_id + 8
            if tcvr_id < 32:
                return tcvr_id - 16
            return tcvr_id - 32
        return 0

    def set_led_state(self, tcvr_id: int, state: DomFpgaLedColor, blink: bool = False):
        port_idx = self._get_fpga_port_index(tcvr_id)
        fpga = self._get_fpga(tcvr_id)
        fpga.set_led_state(port_idx, state=state, blink=blink)

    def clear_all_tcvr_reset(self) -> None:
        for fpga in self._fpgas:
            fpga.clear_all_tcvr_reset()

    def release_tcvr_reset(self, tcvr_id: int) -> None:
        port_idx = self._get_fpga_port_index(tcvr_id)
        fpga = self._get_fpga(tcvr_id)
        fpga.release_qsfp_reset(port_idx)

    def _dom_port_to_tcvr(self, fpga_index: int, local_idx: int) -> int | None:
        """
        Map a DOM FPGA-local port index (0..23) to the global transceiver index (0..47).
        This captures the wedge400-specific wiring and can be reused for presence,
        interrupts, etc.

        - Left FPGA (index 0):
          local [0..15]  -> global [16..31]
          local [16..23] -> global [0..7]
        - Right FPGA (index 1):
          local [0..15]  -> global [32..47]
          local [16..23] -> global [8..15]
        """
        if fpga_index not in (0, 1) or not (0 <= local_idx < 24):
            return None
        if fpga_index == 0:
            if local_idx < 16:
                return 16 + local_idx
            else:
                return local_idx - 16
        else:  # fpga_index == 1
            if local_idx < 16:
                return 32 + local_idx
            else:
                return 8 + (local_idx - 16)

    @property
    def tcvr_present(self) -> list[int]:
        """
        Return a list of global transceiver port IDs (0..47) that are present.

        Each FPGA exposes a 24-bit presence bitmap (bit set == present). Mapping
        from DOM-local bit to global port is handled by _dom_port_to_tcvr().
        """
        present_ports: list[int] = []

        # Iterate over up to two FPGAs and map set bits to global ports
        for fpga_index in (0, 1):
            if fpga_index >= len(self._fpgas) or self._fpgas[fpga_index] is None:
                continue
            try:
                bitmap = self._fpgas[fpga_index].qsfp_present or 0
            except Exception:
                bitmap = 0
            bitmap &= 0xFFFFFF  # ensure 24-bit
            for local_idx in range(24):
                if bitmap & (1 << local_idx):
                    g = self._dom_port_to_tcvr(fpga_index, local_idx)
                    if g is not None:
                        present_ports.append(g)

        present_ports.sort()
        return present_ports

    def read32(self, fpga_index: int, offset_bytes: int) -> Optional[int]:
        if 0 <= fpga_index < len(self._fpgas):
            return self._fpgas[fpga_index].read32(offset_bytes)
        return None

    def write32(self, fpga_index: int, offset_bytes: int, value: int) -> None:
        if 0 <= fpga_index < len(self._fpgas):
            self._fpgas[fpga_index].write32(offset_bytes, value)

    def read_reg(self, key, fpga_index: int = 0) -> Optional[int]:
        if 0 <= fpga_index < len(self._fpgas):
            return self._fpgas[fpga_index].read_reg(key)
        return None

    def write_reg(self, key, value: int, fpga_index: int = 0) -> bool:
        if 0 <= fpga_index < len(self._fpgas):
            return self._fpgas[fpga_index].write_reg(key, value)
        return False

    def print_reg(self, key, fpga_index: int = 0) -> None:
        reg_val = self.read_reg(key, fpga_index)
        if reg_val:
            print(f"{key}[{fpga_index}]: {hex(reg_val)}")

    def dump_registers(self, exclude: Optional[set[str] | list[str]] = None) -> str:
        """
        Pretty-print DOM FPGA register values in a side-by-side table for the first two FPGAs.

        - Columns: Address | Register | FPGA 0 | FPGA 1
        - Sorted by the numeric memory address (ascending).
        - Excludes large/control registers by default (as defined in DomFpga.dump_registers),
          and you may provide additional top-level keys to exclude via `exclude`.

        Returns the rendered table string.
        """
        # Gather dumps for up to two FPGAs (0 and 1). Fill with None if absent.
        dumps: list[dict[str, int | None] | None] = []
        for idx in (0, 1):
            if idx < len(self._fpgas):
                try:
                    dumps.append(self._fpgas[idx].dump_registers(exclude=exclude))
                except Exception:
                    dumps.append({})
            else:
                dumps.append(None)

        # Build a map of register name -> address by flattening the REG map
        reg_map = self.registers
        default_exclude = {"dom_control_config", "dom_global_status", "dom_data"}
        excluded = set(exclude) if exclude is not None else set()
        excluded |= default_exclude

        name_to_addr: dict[str, int] = {}

        def walk(prefix: str, node, top_level: bool) -> None:
            if isinstance(node, int):
                name_to_addr[prefix] = node
                return
            if isinstance(node, dict):
                for k, v in node.items():
                    if top_level and isinstance(k, str) and k in excluded:
                        continue
                    key_str = f"{prefix}.{k}" if prefix else str(k)
                    walk(key_str, v, top_level=False)

        walk("", reg_map, top_level=True)

        # Sort register entries by address
        sorted_entries = sorted(name_to_addr.items(), key=lambda kv: kv[1])

        def fmt_val(v: int | None, present: bool) -> str:
            if not present:
                return "N/A"
            if isinstance(v, int):
                return f"0x{v:08X}"
            return "ERR"

        # Build rows as (addr_str, register_name, val0_str, val1_str)
        rows: list[tuple[str, str, str, str]] = []
        for name, addr in sorted_entries:
            v0 = fmt_val(dumps[0].get(name) if isinstance(dumps[0], dict) else None, isinstance(dumps[0], dict))
            v1 = fmt_val(dumps[1].get(name) if isinstance(dumps[1], dict) else None, isinstance(dumps[1], dict))
            rows.append((f"0x{addr:08X}", name, v0, v1))

        # Prepare a simple ASCII table with headers: Address | Register | FPGA 0 | FPGA 1
        headers = ("Address", "Register", "FPGA 0", "FPGA 1")
        col_addr = [r[0] for r in rows]
        col_reg = [r[1] for r in rows]
        col_f0 = [r[2] for r in rows]
        col_f1 = [r[3] for r in rows]
        w_addr = max(len(headers[0]), *(len(s) for s in col_addr)) if rows else len(headers[0])
        w_reg = max(len(headers[1]), *(len(s) for s in col_reg)) if rows else len(headers[1])
        w_f0 = max(len(headers[2]), *(len(s) for s in col_f0)) if rows else len(headers[2])
        w_f1 = max(len(headers[3]), *(len(s) for s in col_f1)) if rows else len(headers[3])

        def hr() -> str:
            return f"+{'-'*(w_addr+2)}+{'-'*(w_reg+2)}+{'-'*(w_f0+2)}+{'-'*(w_f1+2)}+"

        def row(c1: str, c2: str, c3: str, c4: str) -> str:
            return f"| {c1:>{w_addr}} | {c2:<{w_reg}} | {c3:>{w_f0}} | {c4:>{w_f1}} |"

        lines = [hr(), row(*headers), hr()]
        for r in rows:
            lines.append(row(r[0], r[1], r[2], r[3]))
        lines.append(hr())

        table = "\n".join(lines)
        print(table)
        return table

    @property
    def registers(self):
        return DomFpga.REG

    def __enter__(self):
        # Allow use in `with Wedge400DomIO() as w400:`
        return self

    def __exit__(self, exc_type, exc, tb):
        # Ensure resources are released even on exceptions
        self.close()
        # Returning False propagates any exception from inside the with-block
        return False

    def close(self):
        # Idempotent cleanup of underlying FPGA resources
        for fpga in getattr(self, "_fpgas", []):
            try:
                if hasattr(fpga, "close") and callable(fpga.close):
                    fpga.close()
            except Exception:
                # Avoid masking original exceptions during context exit
                pass


if __name__ == '__main__':
    # fbfpgaio.hw_init()
    # Example usage (not executed during import): initialize external hw if needed
    with Wedge400DomIO() as w400:
        w400.dump_registers(exclude=["port_led_color_profile", "port_led_control"])

        present_ports = w400.tcvr_present
        print(f"Tcvrs present: {present_ports}")

        for port in range(0, Wedge400DomIO.MAX_PORTS):
            if port in present_ports:
                w400.set_led_state(port, DomFpgaLedColor.BLUE, True)
            else:
                w400.set_led_state(port, DomFpgaLedColor.OFF, False)

import sys


# mock ghidra dependencies completely since this is a jython script
class MockGhidraApp:
    DecompInterface = None
    DecompileOptions = None


class MockGhidraProgram:
    @staticmethod
    def getMonitor():
        return None


class MockGhidraUtil:
    class task:
        TaskMonitor = None


sys.modules["ghidra"] = type("Mock", (), {})()
sys.modules["ghidra.app"] = type("Mock", (), {})()
sys.modules["ghidra.app.decompiler"] = MockGhidraApp
sys.modules["ghidra.program"] = type("Mock", (), {})()
sys.modules["ghidra.program.model"] = type("Mock", (), {})()
sys.modules["ghidra.program.model.listing"] = type("Mock", (), {"Function": None})
sys.modules["ghidra.util"] = MockGhidraUtil
sys.modules["ghidra.util.task"] = MockGhidraUtil.task

# mock ghidra globals
import builtins  # noqa: E402

builtins.getMonitor = MockGhidraProgram.getMonitor
builtins.getState = lambda: type("MockState", (), {"getCurrentProgram": lambda: None})()
builtins.monitor = None

from processors.ghidra_decompile.scripts.extract_dispatch import (  # noqa: E402
    decode_ioctl_code,
    extract_ioctl_codes,
)


def test_extract_ioctl_codes():
    c = "if (iVar == 0x222004) { return; } case 2236420:"
    codes = extract_ioctl_codes(c)
    assert 0x222004 in codes
    assert 2236420 in codes


class TestAnIoctlEntryRecordsTheCodeNotTheRoutine:
    """one routine handles every code in a driver and is recorded once. Putting
    it in each entry instead grew a single driver's result to 52 MB, and 706 MB
    of a 734 MB corpus was the same text repeated."""

    def test_an_entry_carries_only_the_code_and_its_decoded_fields(self):
        entry = decode_ioctl_code(0x00222004)
        assert set(entry) == {"code", "hex", "device_type", "function", "method", "access"}

    def test_no_entry_field_can_hold_a_routine(self):
        # the regression is a large text field appearing here, whatever it is named
        entry = decode_ioctl_code(0x00222004)
        assert not [v for v in entry.values() if isinstance(v, str) and len(v) > 32]

    def test_the_code_decodes_the_way_ctl_code_defines_it(self):
        # 0x222004: FILE_DEVICE_UNKNOWN, function 0x801, METHOD_BUFFERED, any access
        entry = decode_ioctl_code(0x00222004)
        assert entry["hex"] == "0x00222004"
        assert entry["device_type"] == 0x22
        assert entry["function"] == 0x801
        assert entry["method"] == 0
        assert entry["access"] == 0

    def test_a_method_neither_code_is_decoded_as_such(self):
        # METHOD_NEITHER hands the driver a raw user pointer, so the low bits
        # deciding it are worth a case of their own
        assert decode_ioctl_code(0x00222003)["method"] == 3

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

from processors.ghidra_decompile.scripts.extract_dispatch import extract_ioctl_codes  # noqa: E402


def test_extract_ioctl_codes():
    c = "if (iVar == 0x222004) { return; } case 2236420:"
    codes = extract_ioctl_codes(c)
    assert 0x222004 in codes
    assert 2236420 in codes

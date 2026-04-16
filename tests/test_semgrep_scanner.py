from deepzero.engine.stage import StageSpec
from processors.semgrep_scanner.semgrep_scanner import SemgrepScanner


def test_semgrep_scanner_init():
    spec = StageSpec(name="test_scanner", processor="semgrep", config={"rules": []})
    scanner = SemgrepScanner(spec)
    assert scanner.description != ""

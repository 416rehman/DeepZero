from processors.semgrep_scanner.semgrep_scanner import SemgrepScanner
from deepzero.engine.stage import StageSpec


def test_semgrep_scanner_init():
    spec = StageSpec(name="test_scanner", processor="semgrep", config={"rules": []})
    scanner = SemgrepScanner(spec)
    assert scanner.description != ""

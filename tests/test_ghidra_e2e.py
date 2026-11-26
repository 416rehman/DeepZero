import os
import struct
from pathlib import Path

import pytest

from deepzero.engine.runner import PipelineRunner
from deepzero.engine.stage import IngestProcessor, ProcessorContext, Sample, StageSpec
from deepzero.engine.state import RunState, StateStore
from processors.ghidra_decompile.ghidra_decompile import GhidraDecompile


class E2EIngest(IngestProcessor):
    def __init__(self, target_file: Path):
        self.spec = StageSpec(name="discover", processor="e2e_ingest")
        self.target_file = target_file
        self.config = {}

    def setup(self, global_config):
        pass

    def process(self, ctx: ProcessorContext, target: Path) -> list[Sample]:
        return [
            Sample(
                sample_id="dummy123",
                source_path=self.target_file,
                filename="dummy.sys",
                data={"sha256": "fakehash"},
            )
        ]


# Small synthetic ELF so E2E timing does not depend on host OS binaries.
def _minimal_elf64() -> bytes:
    code = b"\xc3" + b"\x90" * 7
    ehdr_size = 64
    phdr_size = 56
    total_size = ehdr_size + phdr_size + len(code)
    base_vaddr = 0x400000
    entry_vaddr = base_vaddr + ehdr_size + phdr_size
    e_ident = b"\x7fELF\x02\x01\x01" + b"\x00" * 9
    et_exec = 2
    em_x86_64 = 62
    ev_current = 1
    pt_load = 1
    pf_rx = 5
    ehdr = struct.pack(
        "<16sHHIQQQIHHHHHH",
        e_ident,
        et_exec,
        em_x86_64,
        ev_current,
        entry_vaddr,
        ehdr_size,
        0,
        0,
        ehdr_size,
        phdr_size,
        1,
        0,
        0,
        0,
    )
    phdr = struct.pack(
        "<IIQQQQQQ",
        pt_load,
        pf_rx,
        0,
        base_vaddr,
        base_vaddr,
        total_size,
        total_size,
        0x1000,
    )
    return ehdr + phdr + code


@pytest.mark.ghidra
def test_physical_ghidra_pipeline_run(tmp_path):
    """
    Absolutely unmocked physical integration test interacting natively with the
    Ghidra Java Virtual Machine installed on the local system matching user specifications.
    """
    ghidra_dir = os.environ.get("GHIDRA_INSTALL_DIR")
    if not ghidra_dir or not Path(ghidra_dir).exists():
        pytest.fail(
            "GHIDRA_INSTALL_DIR not set or does not exist — Ghidra must be installed to run this test"
        )

    store = StateStore(tmp_path / "work")
    run_state = RunState(run_id="test_ghidra_e2e", pipeline="loldrivers")
    store.save_run(run_state)

    dummy_bin = tmp_path / "dummy.sys"
    dummy_bin.write_bytes(_minimal_elf64())

    ingest = E2EIngest(dummy_bin)

    # Write a fast fake post-script to bypass minutes of auto-analysis loops
    fast_script = tmp_path / "fast_script.py"
    fast_script.write_text("""
import os, json
out_dir = os.environ.get("DEEPZERO_OUTPUT_DIR", ".")
if not os.path.exists(out_dir):
    os.makedirs(out_dir)

with open(os.path.join(out_dir, "ghidra_result.json"), "w") as f:
    json.dump({"success": True, "device_name": "E2ETestDriver"}, f)
""")

    spec = StageSpec(
        name="decompile",
        processor="ghidra_decompile",
        config={
            "ghidra_install_dir": ghidra_dir,
            "strategy": str(fast_script.absolute()),
            "timeout": 180,
        },
    )
    decompile_proc = GhidraDecompile(spec)
    # The processor natively searches its _tool_dir for the script
    decompile_proc._tool_dir = Path("processors/ghidra_decompile").absolute()

    runner = PipelineRunner(
        ingest=ingest,
        stages=[(spec, decompile_proc)],
        state_store=store,
        pipeline_dir=tmp_path / "work" / "pipeline",
        global_config={},
    )

    result = runner.run(Path("."), run_state)

    assert result.status == "completed"

    sample = store.load_sample("dummy123")
    assert sample is not None
    assert "decompile" in sample.history
    assert sample.history["decompile"].error is None, (
        f"Decompile stage failed: {sample.history['decompile'].error}"
    )

    # Assert physical file dropped by actual Java natively exists within DeepZero cache bindings!
    ghidra_result = store.sample_dir("dummy123") / "decompiled" / "ghidra_result.json"
    assert ghidra_result.exists()

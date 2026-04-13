from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from deepzero.providers.decompiler import _find_analyze_headless, run_ghidra_headless


class TestFindAnalyzeHeadless:
    def test_finds_bat_on_windows(self, tmp_path):
        support = tmp_path / "support"
        support.mkdir()
        bat = support / "analyzeHeadless.bat"
        bat.write_text("@echo off")

        with patch.object(sys, "platform", "win32"):
            result = _find_analyze_headless(tmp_path)
        assert result == bat

    def test_finds_sh_on_linux(self, tmp_path):
        support = tmp_path / "support"
        support.mkdir()
        sh = support / "analyzeHeadless"
        sh.write_text("#!/bin/bash")

        with patch.object(sys, "platform", "linux"):
            result = _find_analyze_headless(tmp_path)
        assert result == sh

    def test_fallback_finds_either(self, tmp_path):
        support = tmp_path / "support"
        support.mkdir()
        bat = support / "analyzeHeadless.bat"
        bat.write_text("@echo off")

        # even on linux, fallback should find the .bat
        with patch.object(sys, "platform", "linux"):
            result = _find_analyze_headless(tmp_path)
        assert result == bat

    def test_raises_when_not_found(self, tmp_path):
        support = tmp_path / "support"
        support.mkdir()
        with pytest.raises(FileNotFoundError, match="analyzeHeadless"):
            _find_analyze_headless(tmp_path)

    def test_raises_when_no_support_dir(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _find_analyze_headless(tmp_path)


class TestRunGhidraHeadless:
    def test_cache_hit(self, tmp_path):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        cached = output_dir / "ghidra_result.json"
        cached.write_text(json.dumps({"success": True, "data": "cached"}))

        result = run_ghidra_headless(
            binary_path=tmp_path / "test.sys",
            output_dir=output_dir,
            ghidra_install_dir=tmp_path,
            post_script=tmp_path / "script.py",
        )
        assert result["success"] is True
        assert result["data"] == "cached"

    def test_corrupt_cache_regenerates(self, tmp_path):
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        cached = output_dir / "ghidra_result.json"
        cached.write_text("not json")

        # create a minimal ghidra dir so _find_analyze_headless works
        ghidra_dir = tmp_path / "ghidra"
        support = ghidra_dir / "support"
        support.mkdir(parents=True)
        if sys.platform == "win32":
            script = support / "analyzeHeadless.bat"
            script.write_text("@echo off\nexit /b 1")
        else:
            script = support / "analyzeHeadless"
            script.write_text("#!/bin/sh\nexit 1")
            script.chmod(0o755)

        binary = tmp_path / "test.sys"
        binary.write_bytes(b"MZ")

        result = run_ghidra_headless(
            binary_path=binary,
            output_dir=output_dir,
            ghidra_install_dir=ghidra_dir,
            post_script=tmp_path / "script.py",
            timeout=5,
        )
        # proves it re-ran (exited non-zero from our fake script)
        assert result["success"] is False

    def test_missing_result_file(self, tmp_path):
        output_dir = tmp_path / "output"
        ghidra_dir = tmp_path / "ghidra"

        # create the analyzeHeadless script that does nothing
        support = ghidra_dir / "support"
        support.mkdir(parents=True)
        if sys.platform == "win32":
            script = support / "analyzeHeadless.bat"
            script.write_text("@echo off\nexit /b 0")
        else:
            script = support / "analyzeHeadless"
            script.write_text("#!/bin/sh\nexit 0")
            script.chmod(0o755)

        post_script = tmp_path / "extract.py"
        post_script.write_text("# no-op")

        binary = tmp_path / "test.sys"
        binary.write_bytes(b"MZ")

        result = run_ghidra_headless(
            binary_path=binary,
            output_dir=output_dir,
            ghidra_install_dir=ghidra_dir,
            post_script=post_script,
            timeout=5,
        )
        # should fail because the fake script doesn't produce ghidra_result.json
        assert result["success"] is False
        assert "ghidra_result.json" in result.get("error", "")

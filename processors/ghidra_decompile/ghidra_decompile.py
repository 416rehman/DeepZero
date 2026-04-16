from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
)

log = logging.getLogger("deepzero.processor.ghidra")


class GhidraDecompile(MapProcessor):
    description = (
        "decompiles binaries using ghidra headless analysis with a configurable post-script"
    )
    version = "2.0"

    @dataclass
    class Config:
        strategy: str = ""
        timeout: int = 300
        max_functions: int | None = None
        max_depth: int | None = None
        ghidra_install_dir: str = ""
        java_home: str = ""

    def validate(self, ctx: ProcessorContext) -> list[str]:
        if not self.config.ghidra_install_dir:
            return [
                "ghidra_install_dir is required - set it in config or via ${GHIDRA_INSTALL_DIR}"
            ]
        ghidra_dir = Path(self.config.ghidra_install_dir)
        if not ghidra_dir.exists():
            return [f"ghidra not found at {ghidra_dir}"]
        try:
            self._find_analyze_headless(ghidra_dir)
        except FileNotFoundError as e:
            return [str(e)]
        return []

    def should_skip(self, ctx: ProcessorContext, entry: ProcessorEntry) -> str | None:
        cached = entry.sample_dir / "decompiled" / "ghidra_result.json"
        if cached.exists():
            try:
                with open(cached, "r", encoding="utf-8") as f:
                    json.load(f)
                return "decompilation already cached"
            except (json.JSONDecodeError, OSError, ValueError) as e:
                self.log.debug("failed to read cached ghidra output: %s", e)
        return None

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        if not self.config.ghidra_install_dir:
            return ProcessorResult.fail("ghidra_install_dir not configured")

        ghidra_dir = Path(self.config.ghidra_install_dir)
        if not ghidra_dir.exists():
            return ProcessorResult.fail(f"ghidra not found: {ghidra_dir}")

        if not self.config.strategy:
            return ProcessorResult.fail("no strategy script configured")

        script_path = self._resolve_script(self.config.strategy)
        output_dir = entry.sample_dir / "decompiled"

        extra_env: dict[str, str] = {}
        if self.config.max_functions is not None:
            extra_env["DEEPZERO_MAX_FUNCTIONS"] = str(self.config.max_functions)
        if self.config.max_depth is not None:
            extra_env["DEEPZERO_MAX_DEPTH"] = str(self.config.max_depth)

        active_timeout = self.spec.timeout if self.spec.timeout > 0 else self.config.timeout
        result = self._run_ghidra_headless(
            binary_path=entry.source_path,
            output_dir=output_dir,
            ghidra_install_dir=ghidra_dir,
            post_script=script_path,
            timeout=active_timeout,
            java_home=self.config.java_home,
            extra_env=extra_env if extra_env else None,
        )

        if not result.get("success", False):
            return ProcessorResult.fail(result.get("error", "ghidra analysis failed"))

        data: dict[str, Any] = {}
        for key in ("device_name", "symbolic_link", "dispatch_name", "function_count"):
            if key in result:
                data[key] = result[key]

        artifacts = {"ghidra_result": "decompiled/ghidra_result.json"}
        dispatch_file = output_dir / "dispatch_ioctl.c"
        if dispatch_file.exists():
            artifacts["dispatch_ioctl"] = "decompiled/dispatch_ioctl.c"

        return ProcessorResult.ok(artifacts=artifacts, data=data)

    def _resolve_script(self, strategy: str) -> Path:
        local_script = self.processor_dir / "scripts" / strategy
        if local_script.exists():
            return local_script

        abs_path = Path(strategy)
        if abs_path.is_absolute() and abs_path.exists():
            return abs_path

        raise FileNotFoundError(
            f"strategy '{strategy}' not found in {self.processor_dir / 'scripts'}"
        )

    def _build_ghidra_cmd(
        self,
        binary_path: Path,
        output_dir: Path,
        ghidra_install_dir: Path,
        post_script: Path,
        timeout: int,
    ) -> list[str]:
        analyze_headless = self._find_analyze_headless(ghidra_install_dir)
        project_dir = output_dir / "ghidra_project"
        project_dir.mkdir(parents=True, exist_ok=True)
        project_name = f"dz_{binary_path.stem[:20]}"
        cmd = [
            str(analyze_headless),
            str(project_dir),
            project_name,
            "-import",
            str(binary_path),
            "-postScript",
            str(post_script),
            "-scriptPath",
            str(post_script.parent),
            "-overwrite",
            "-deleteProject",
            "-analysisTimeoutPerFile",
            str(timeout),
        ]
        return cmd

    def _run_ghidra_headless(
        self,
        binary_path: Path,
        output_dir: Path,
        ghidra_install_dir: Path,
        post_script: Path,
        timeout: int = 300,
        java_home: str = "",
        extra_env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)

        cached_result = output_dir / "ghidra_result.json"
        if cached_result.exists():
            log.info("ghidra cache hit for %s", binary_path.name)
            try:
                return json.loads(cached_result.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                log.warning("cached result is corrupt, re-running analysis", exc_info=e)
                cached_result.unlink(missing_ok=True)

        cmd = self._build_ghidra_cmd(
            binary_path, output_dir, ghidra_install_dir, post_script, timeout
        )

        env = dict(os.environ)
        env["DEEPZERO_OUTPUT_DIR"] = str(output_dir)

        if java_home:
            env["JAVA_HOME"] = java_home

        if extra_env:
            env.update(extra_env)

        stdout_log = output_dir / "ghidra_stdout.log"
        stderr_log = output_dir / "ghidra_stderr.log"

        log.info("starting ghidra analysis of %s (timeout=%ds)", binary_path.name, timeout)

        start_time = time.monotonic()

        try:
            with open(stdout_log, "wb") as fout, open(stderr_log, "wb") as ferr:
                proc = subprocess.Popen(
                    cmd,
                    stdout=fout,
                    stderr=ferr,
                    stdin=subprocess.DEVNULL,
                    env=env,
                )

                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                    elapsed = time.monotonic() - start_time
                    log.warning("ghidra timed out for %s after %.1fs", binary_path.name, elapsed)
                    return {"success": False, "error": f"ghidra timed out after {timeout}s"}

        except OSError as e:
            return {"success": False, "error": f"execution error: {e}"}

        elapsed = time.monotonic() - start_time

        if proc.returncode != 0:
            stderr_text = ""
            if stderr_log.exists():
                stderr_text = stderr_log.read_text(encoding="utf-8", errors="replace")[-500:]
            log.warning(
                "ghidra failed for %s (code %d, %.1fs)", binary_path.name, proc.returncode, elapsed
            )
            return {
                "success": False,
                "error": f"ghidra exited with code {proc.returncode}: {stderr_text}",
            }

        if not cached_result.exists():
            log.warning("ghidra produced no result for %s (%.1fs)", binary_path.name, elapsed)
            return {"success": False, "error": "ghidra succeeded but no result found"}

        log.info("ghidra completed %s (%.1fs)", binary_path.name, elapsed)

        try:
            return json.loads(cached_result.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return {"success": False, "error": f"failed to parse ghidra output: {e}"}

    def _find_analyze_headless(self, ghidra_dir: Path) -> Path:
        if sys.platform == "win32":
            bat = ghidra_dir / "support" / "analyzeHeadless.bat"
            if bat.exists():
                return bat
        else:
            sh = ghidra_dir / "support" / "analyzeHeadless"
            if sh.exists():
                return sh

        for name in ("analyzeHeadless.bat", "analyzeHeadless"):
            p = ghidra_dir / "support" / name
            if p.exists():
                return p

        raise FileNotFoundError(
            f"analyzeHeadless not found in {ghidra_dir}/support/ - verify ghidra install directory"
        )

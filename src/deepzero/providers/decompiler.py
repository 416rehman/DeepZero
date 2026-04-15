from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("deepzero.decompiler")


def run_ghidra_headless(
    binary_path: Path,
    output_dir: Path,
    ghidra_install_dir: Path,
    post_script: Path,
    timeout: int = 300,
    java_home: str = "",
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """run ghidra headless analysis with a configurable post-script.
    returns the parsed ghidra_result.json or an error dict."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # check for cached result
    cached_result = output_dir / "ghidra_result.json"
    if cached_result.exists():
        log.info("ghidra cache hit for %s", binary_path.name)
        try:
            return json.loads(cached_result.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("cached result is corrupt, re-running analysis")

    analyze_headless = _find_analyze_headless(ghidra_install_dir)

    project_dir = output_dir / "ghidra_project"
    project_dir.mkdir(parents=True, exist_ok=True)

    project_name = f"dz_{binary_path.stem[:20]}"

    cmd = [
        str(analyze_headless),
        str(project_dir),
        project_name,
        "-import", str(binary_path),
        "-postScript", str(post_script),
        "-scriptPath", str(post_script.parent),
        "-deleteProject",
        "-analysisTimeoutPerFile", str(timeout),
    ]

    env = dict(os.environ)
    env["DEEPZERO_OUTPUT_DIR"] = str(output_dir)

    if java_home:
        env["JAVA_HOME"] = java_home

    if extra_env:
        env.update(extra_env)

    stdout_log = output_dir / "ghidra_stdout.log"
    stderr_log = output_dir / "ghidra_stderr.log"

    log.info("starting ghidra analysis of %s (timeout=%ds)", binary_path.name, timeout)
    start_time = time.time()

    proc = None
    try:
        with open(stdout_log, "w") as fout, open(stderr_log, "w") as ferr:
            proc = subprocess.Popen(
                cmd, stdout=fout, stderr=ferr, stdin=subprocess.DEVNULL, env=env,
            )

            while proc.poll() is None:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    proc.kill()
                    proc.wait(timeout=10)
                    return {"success": False, "error": f"ghidra timed out after {elapsed:.0f}s"}

                time.sleep(1)

        elapsed = time.time() - start_time

        if proc.returncode != 0:
            stderr_text = ""
            if stderr_log.exists():
                stderr_text = stderr_log.read_text(encoding="utf-8", errors="replace")[-500:]
            return {
                "success": False,
                "error": f"ghidra exited with code {proc.returncode}: {stderr_text}",
            }

        log.info("ghidra analysis of %s completed in %.1fs", binary_path.name, elapsed)

    except (OSError, subprocess.SubprocessError) as e:
        return {"success": False, "error": f"execution error: {e}"}
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError as exc:
                log.debug("cleanup kill skipped — pid already exited: %s", exc)

    if not cached_result.exists():
        contents = [f.name for f in output_dir.iterdir()] if output_dir.exists() else []
        return {
            "success": False,
            "error": f"post-script did not produce ghidra_result.json. output dir contains: {contents}",
        }

    try:
        return json.loads(cached_result.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"success": False, "error": f"failed to parse ghidra output: {e}"}


def _find_analyze_headless(ghidra_dir: Path) -> Path:
    if sys.platform == "win32":
        bat = ghidra_dir / "support" / "analyzeHeadless.bat"
        if bat.exists():
            return bat
    else:
        sh = ghidra_dir / "support" / "analyzeHeadless"
        if sh.exists():
            return sh

    # try both as fallback
    for name in ("analyzeHeadless.bat", "analyzeHeadless"):
        p = ghidra_dir / "support" / name
        if p.exists():
            return p

    raise FileNotFoundError(
        f"analyzeHeadless not found in {ghidra_dir}/support/ - verify ghidra install directory"
    )

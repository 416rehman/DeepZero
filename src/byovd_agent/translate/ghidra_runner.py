from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

from byovd_agent.models import (
    BufferMethod,
    DecompiledHandler,
    IOCTLCode,
    TranslationResult,
)

log = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent / "scripts"
EXTRACT_SCRIPT = SCRIPT_DIR / "extract_dispatch.py"


def _find_analyze_headless(ghidra_dir: Path) -> Path:
    """locate the analyzeHeadless script in the ghidra installation"""
    bat = ghidra_dir / "support" / "analyzeHeadless.bat"
    if bat.exists():
        return bat

    sh = ghidra_dir / "support" / "analyzeHeadless"
    if sh.exists():
        return sh

    raise FileNotFoundError(
        f"analyzeHeadless not found in {ghidra_dir}/support/ — "
        "verify GHIDRA_INSTALL_DIR is correct"
    )


def run_ghidra_headless(
    sys_path: Path,
    work_dir: Path,
    ghidra_dir: Path,
    timeout: int = 300,
) -> TranslationResult:
    """run ghidra headless analysis on a single .sys file and extract
    the IRP dispatch table + decompiled IOCTL handlers.

    output is cached: if ghidra_result.json already exists in work_dir/decompiled,
    the cached result is returned without re-running ghidra."""
    sha256 = work_dir.name
    result = TranslationResult(sha256=sha256)

    # check cache first
    output_dir = work_dir / "decompiled"
    cached_result = output_dir / "ghidra_result.json"
    if cached_result.exists():
        log.info("[ghidra] cache hit for %s — skipping re-analysis", sys_path.name)
        return _parse_ghidra_result(cached_result, result)

    analyze_headless = _find_analyze_headless(ghidra_dir)

    project_dir = work_dir / "ghidra_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    project_name = f"byovd_{sha256[:12]}"

    # removed -noanalysis: auto-analysis is required for decompilation
    cmd = [
        str(analyze_headless),
        str(project_dir),
        project_name,
        "-import", str(sys_path),
        "-postScript", str(EXTRACT_SCRIPT),
        "-scriptPath", str(SCRIPT_DIR),
        "-deleteProject",
        "-analysisTimeoutPerFile", str(timeout),
    ]

    # Ghidra struggles with concurrent locks on the `.ghidra_11.0_PUBLIC` config files and prompts for JDKs.
    env = dict(os.environ)
    env["BYOVD_WORK_DIR"] = str(output_dir)
    env["JAVA_HOME"] = r"C:\Program Files\Microsoft\jdk-21.0.5.11-hotspot"

    # redirect stdout/stderr to files so we can log progress without blocking
    stdout_log = work_dir / "ghidra_stdout.log"
    stderr_log = work_dir / "ghidra_stderr.log"

    log.info("[ghidra] starting analysis of %s (timeout=%ds)", sys_path.name, timeout)
    start_time = time.time()

    try:
        with open(stdout_log, "w") as fout, open(stderr_log, "w") as ferr:
            proc = subprocess.Popen(
                cmd, stdout=fout, stderr=ferr, stdin=subprocess.DEVNULL, env=env,
            )

            # poll and log progress
            while proc.poll() is None:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    proc.kill()
                    result.error = f"ghidra timed out after {elapsed:.0f}s"
                    log.error("[ghidra] %s", result.error)
                    return result

                # log progress every 15s
                if int(elapsed) % 15 == 0 and int(elapsed) > 0:
                    latest_log = ""
                    if stdout_log.exists() and stdout_log.stat().st_size > 0:
                        try:
                            with open(stdout_log, "r", encoding="utf-8", errors="replace") as f:
                                # read last few hundred bytes to find a newline
                                f.seek(0, os.SEEK_END)
                                file_size = f.tell()
                                f.seek(max(0, file_size - 512))
                                lines = f.readlines()
                                if lines:
                                    # get the last non-empty line
                                    valid_lines = [l.strip() for l in lines if l.strip()]
                                    if valid_lines:
                                        latest_log = valid_lines[-1]
                        except Exception:
                            pass
                            
                    if latest_log:
                        # truncate extremely long lines (ghidra logging can be crazy)
                        if len(latest_log) > 100:
                            latest_log = latest_log[:97] + "..."
                        log.info(
                            "[ghidra] %s — running %ds: %s",
                            sys_path.name, elapsed, latest_log
                        )
                    else:
                        log.info(
                            "[ghidra] %s — running %ds (no log output yet)",
                            sys_path.name, elapsed
                        )
                        
                time.sleep(1)

        elapsed = time.time() - start_time
        returncode = proc.returncode

        # read logs for context
        stdout_text = stdout_log.read_text(encoding="utf-8", errors="replace") if stdout_log.exists() else ""
        stderr_text = stderr_log.read_text(encoding="utf-8", errors="replace") if stderr_log.exists() else ""
        result.analysis_log = stdout_text[-3000:]

        if returncode != 0:
            result.error = f"ghidra exited with code {returncode}: {stderr_text[-500:]}"
            log.error("[ghidra] %s failed (code=%d, %.1fs): %s",
                      sys_path.name, returncode, elapsed, stderr_text[-200:])
            return result

        log.info("[ghidra] %s — analysis completed in %.1fs", sys_path.name, elapsed)

        if not cached_result.exists():
            result.error = "ghidra script did not produce ghidra_result.json"
            log.error("[ghidra] %s — %s", sys_path.name, result.error)
            contents = list(output_dir.iterdir()) if output_dir.exists() else []
            log.error("[ghidra] output dir contents: %s", [f.name for f in contents])
            return result

        return _parse_ghidra_result(cached_result, result)
    except Exception as e:
        result.error = f"execution error: {e}"
        log.error("[ghidra] %s", result.error)
        return result
    finally:
        if 'proc' in locals() and proc.poll() is None:
            try:
                proc.kill()
            except BaseException:
                pass


def _parse_ghidra_result(result_json: Path, result: TranslationResult) -> TranslationResult:
    """parse the JSON output from the ghidra extraction script"""
    try:
        data = json.loads(result_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        result.error = f"failed to parse ghidra output: {e}"
        return result

    result.success = data.get("success", False)
    result.error = data.get("error", "")
    result.driver_entry_c = data.get("driver_entry_c", "")
    result.dispatch_function_name = data.get("dispatch_name", "")
    result.dispatch_function_c = data.get("dispatch_c", "")
    result.device_name = data.get("device_name", "")
    result.symbolic_link = data.get("symbolic_link", "")
    result.function_count = data.get("function_count", 0)

    for handler_data in data.get("ioctl_handlers", []):
        code = handler_data.get("code", 0)
        method_idx = handler_data.get("method", 0)
        methods = [BufferMethod.BUFFERED, BufferMethod.IN_DIRECT,
                   BufferMethod.OUT_DIRECT, BufferMethod.NEITHER]

        ioctl = IOCTLCode(raw_code=code)
        ioctl.decode()

        handler = DecompiledHandler(
            ioctl_code=ioctl,
            decompiled_c=handler_data.get("decompiled_c", ""),
            buffer_method=methods[method_idx] if 0 <= method_idx <= 3 else BufferMethod.BUFFERED,
        )
        result.ioctl_handlers.append(handler)

    return result

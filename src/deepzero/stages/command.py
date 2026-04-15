from __future__ import annotations

import os
import subprocess
from pathlib import Path

from deepzero.engine.stage import MapTool, StageContext, StageResult


class GenericCommand(MapTool):
    # runs any external command as a pipeline stage - the universal escape hatch

    def process(self, ctx: StageContext) -> StageResult:
        run_template = ctx.config.get("run", "")
        if not run_template:
            return StageResult(status="failed", error="command tool requires a 'run' config field")

        timeout = ctx.config.get("timeout", 300)
        stdout_to = ctx.config.get("stdout_to", "")
        on_error = ctx.config.get("on_error", "fail")

        output_dir = ctx.sample_dir / "command_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        template_vars = {
            "sample_path": str(ctx.sample_path),
            "sample_dir": str(ctx.sample_dir),
            "output_dir": str(output_dir),
            "filename": ctx.sample_path.name,
            "sample_id": ctx.sample_dir.name,
        }

        for k, v in ctx.config.items():
            if k not in ("run", "timeout", "stdout_to", "on_error", "produces"):
                template_vars[k] = str(v)

        cmd_str = run_template
        for key, val in template_vars.items():
            cmd_str = cmd_str.replace(f"{{{key}}}", val)

        self.log.info("running: %s", cmd_str[:200])

        try:
            import shlex
            cmd_list = shlex.split(cmd_str)
            proc = subprocess.run(cmd_list, shell=False, capture_output=True, timeout=timeout, cwd=str(ctx.sample_dir))
        except subprocess.TimeoutExpired:
            if on_error == "skip":
                return StageResult(status="completed", verdict="skip", data={"command_error": "timeout"})
            return StageResult(status="failed", error=f"command timed out after {timeout}s")
        except OSError as e:
            if on_error == "skip":
                return StageResult(status="completed", verdict="skip", data={"command_error": str(e)})
            return StageResult(status="failed", error=f"command execution error: {e}")

        if stdout_to and proc.stdout:
            stdout_path = ctx.sample_dir / stdout_to
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = stdout_path.with_suffix(".tmp")
            tmp.write_bytes(proc.stdout)
            os.replace(tmp, stdout_path)

        if proc.returncode != 0:
            stderr_text = proc.stderr.decode("utf-8", errors="replace")[:500]
            if on_error == "skip":
                return StageResult(
                    status="completed",
                    verdict="skip",
                    data={"command_error": f"exit code {proc.returncode}: {stderr_text[:200]}"},
                )
            return StageResult(status="failed", error=f"command exited with code {proc.returncode}: {stderr_text}")

        artifacts: dict[str, str] = {}
        if stdout_to:
            artifacts["stdout"] = stdout_to

        produces = ctx.config.get("produces", [])
        if isinstance(produces, str):
            produces = [produces]
        for p in produces:
            artifact_path = ctx.sample_dir / p
            if artifact_path.exists():
                artifacts[Path(p).stem] = p

        return StageResult(
            status="completed",
            verdict="continue",
            artifacts=artifacts,
            data={"command_exit_code": proc.returncode},
        )

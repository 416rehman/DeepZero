from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorResult,
    ProcessorEntry,
)


class GenericCommand(MapProcessor):
    description = (
        "runs any external command as a pipeline stage - the universal escape hatch"
    )

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        run_template = self.config.get("run", "")
        if not run_template:
            return ProcessorResult.fail(
                "command processor requires a 'run' config field"
            )

        timeout = self.config.get("timeout", 300)
        stdout_to = self.config.get("stdout_to", "")
        on_error = self.config.get("on_error", "fail")

        output_dir = entry.sample_dir / "command_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        template_vars = {
            "sample_path": str(entry.source_path),
            "sample_dir": str(entry.sample_dir),
            "output_dir": str(output_dir),
            "filename": entry.source_path.name,
            "sample_id": entry.sample_dir.name,
        }

        for k, v in self.config.items():
            if k not in ("run", "timeout", "stdout_to", "on_error", "produces"):
                template_vars[k] = str(v)

        cmd_str = run_template
        for key, val in template_vars.items():
            cmd_str = cmd_str.replace(f"{{{key}}}", val)

        self.log.info("running: %s", cmd_str[:200])
        cmd_list = shlex.split(cmd_str)

        try:
            returncode, stdout, stderr = asyncio.run(
                self._run_async(cmd_list, timeout, cwd=str(entry.sample_dir))
            )
        except TimeoutError:
            if on_error == "skip":
                return ProcessorResult.filter(f"command timed out after {timeout}s")
            return ProcessorResult.fail(f"command timed out after {timeout}s")
        except OSError as e:
            if on_error == "skip":
                return ProcessorResult.filter(str(e))
            return ProcessorResult.fail(f"command execution error: {e}")

        if stdout_to and stdout:
            stdout_path = entry.sample_dir / stdout_to
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = stdout_path.with_suffix(".tmp")
            tmp.write_bytes(stdout)
            os.replace(tmp, stdout_path)

        if returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")[:500]
            if on_error == "skip":
                return ProcessorResult.filter(
                    f"exit code {returncode}: {stderr_text[:200]}"
                )
            return ProcessorResult.fail(
                f"command exited with code {returncode}: {stderr_text}"
            )

        artifacts: dict[str, str] = {}
        if stdout_to:
            artifacts["stdout"] = stdout_to

        produces_list = self.config.get("produces", [])
        if isinstance(produces_list, str):
            produces_list = [produces_list]
        for p in produces_list:
            artifact_path = entry.sample_dir / p
            if artifact_path.exists():
                artifacts[Path(p).stem] = p

        return ProcessorResult.ok(
            artifacts=artifacts,
            data={"command_exit_code": returncode},
        )

    async def _run_async(
        self, cmd_list: list[str], timeout: int, cwd: str
    ) -> tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(
            cmd_list[0],
            *cmd_list[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode if proc.returncode is not None else -1,
                stdout,
                stderr,
            )
        except asyncio.TimeoutError:
            if proc.returncode is None:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError as kill_exc:
                    raise RuntimeError(
                        "Failed to cleanly kill the command process"
                    ) from kill_exc
            raise TimeoutError()

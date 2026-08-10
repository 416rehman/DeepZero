from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
)
from deepzero.engine.state import atomic_replace


def _split_command(template: str) -> list[str]:
    """split a `run` template into arguments the way its own platform reads it.

    shlex parses backslash as an escape, which is right on POSIX and wrong on
    Windows, where it separates directories: `C:\\Tools\\x.exe` comes back as
    `C:Toolsx.exe` and the command cannot be found. Windows is parsed in
    non-POSIX mode instead, where a backslash is an ordinary character, and the
    quotes that mode leaves attached are removed here so an argument reaches the
    program the way it was written.
    """
    if os.name != "nt":
        return shlex.split(template)

    stripped = []
    for token in shlex.split(template, posix=False):
        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
            token = token[1:-1]
        stripped.append(token)
    return stripped


class GenericCommand(MapProcessor):
    description = "runs any external command as a pipeline stage - the universal escape hatch"

    # the exit code is recorded for every sample the command ran on. Anything
    # the command itself wrote is reached by its filename, via `produces`.
    provides = ("command_exit_code",)

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        run_template = self.config.get("run", "")
        if not run_template:
            return ProcessorResult.fail("command processor requires a 'run' config field")

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
            "sample_id": entry.sample_id,
        }

        for k, v in self.config.items():
            if k not in ("run", "timeout", "stdout_to", "on_error", "produces"):
                template_vars[k] = str(v)

        # the template is split into arguments first and the values are put into
        # those arguments afterwards, so a value never has to survive being
        # parsed as shell text. Substituting first and splitting after would hand
        # shlex a path like C:\work\a.sys, whose separators it reads as escapes
        # and removes, leaving the command pointed at C:worka.sys. A value is one
        # argument whatever it contains, so a path with a space in it also
        # arrives whole rather than as two arguments.
        cmd_list = [self._substitute(arg, template_vars) for arg in _split_command(run_template)]
        if not cmd_list:
            return ProcessorResult.fail("command processor 'run' produced no command to execute")

        self.log.info("running: %s", " ".join(cmd_list)[:200])

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
            atomic_replace(tmp, stdout_path)

        if returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")[:500]
            if on_error == "skip":
                return ProcessorResult.filter(f"exit code {returncode}: {stderr_text[:200]}")
            return ProcessorResult.fail(f"command exited with code {returncode}: {stderr_text}")

        artifacts: dict[str, str] = {}
        if stdout_to:
            artifacts["stdout"] = stdout_to

        # `produces:` written with nothing under it parses as null, which should
        # claim no artifacts rather than fail a command that already succeeded
        produces_list = self.config.get("produces") or []
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

    @staticmethod
    def _substitute(argument: str, values: dict[str, str]) -> str:
        for key, val in values.items():
            argument = argument.replace(f"{{{key}}}", val)
        return argument

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
                    raise RuntimeError("Failed to cleanly kill the command process") from kill_exc
            raise TimeoutError()

"""claude code backend - drives the user's locally installed, already-signed-in
`claude` cli in headless mode (`claude -p --output-format json`).

lets deepzero run against a claude code subscription instead of a metered api
key. all subprocess handling lives in CLIAgentBackend; this module only declares
claude-specific argv and output parsing.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, ClassVar

from deepzero.engine.backends.base import BackendError, CLIAgentBackend

log = logging.getLogger("deepzero.llm.claude_code")

# the prompt carries untrusted content (decompiled malware, attacker-controlled
# strings). a completion never needs tools, so deny the ones that could turn a
# prompt injection into code execution or exfiltration.
_DEFAULT_DISALLOWED_TOOLS = (
    "Bash",
    "Edit",
    "Write",
    "NotebookEdit",
    "Read",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Agent",
    "Task",
)


class ClaudeCodeBackend(CLIAgentBackend):
    scheme: ClassVar[str] = "claude-code"
    display_name: ClassVar[str] = "claude code"
    binary_names: ClassVar[tuple[str, ...]] = ("claude",)
    install_hint: ClassVar[str] = "install it and sign in (https://claude.com/claude-code)."
    # never use --bare: it disables oauth/keychain reads, which is exactly the
    # auth this backend exists to use
    subscription_auth_env_blocklist: ClassVar[tuple[str, ...]] = (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    )

    def __init__(self, model: str, **kwargs: Any):
        super().__init__(model, **kwargs)
        self.max_turns = int(kwargs.get("max_turns", 1))
        disallowed = kwargs.get("disallowed_tools", _DEFAULT_DISALLOWED_TOOLS)
        self.disallowed_tools: tuple[str, ...] = tuple(disallowed) if disallowed else ()

    @classmethod
    def extra_search_paths(cls) -> list[Path]:
        home = Path.home()
        paths = [
            home / ".claude" / "local" / "claude",
            home / ".local" / "bin" / "claude",
            home / "bin" / "claude",
        ]
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
            localappdata = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
            for base in (Path(appdata) / "npm", Path(localappdata) / "claude" / "bin"):
                paths += [base / "claude.cmd", base / "claude.exe", base / "claude"]
            paths.append(home / ".local" / "bin" / "claude.exe")
        return paths

    def build_argv(self, system: str) -> tuple[list[str], str]:
        argv = [str(self._binary), "-p", "--output-format", "json"]

        if self.alias:
            argv += ["--model", self.alias]
        if self.max_turns > 0:
            argv += ["--max-turns", str(self.max_turns)]
        if self.disallowed_tools:
            argv += ["--disallowed-tools", ",".join(self.disallowed_tools)]
        # ignore any globally configured mcp servers - a completion needs none,
        # and they would widen the blast radius of injected content
        argv.append("--strict-mcp-config")

        inline_system = ""
        if system:
            if len(system) <= self.max_argv_text:
                argv += ["--append-system-prompt", system]
            else:
                inline_system = system
        return argv, inline_system

    def parse_output(self, returncode: int, stdout: str, stderr: str) -> str:
        payload: dict[str, Any] | None = None
        text = stdout.strip()
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = None

        if payload is None:
            detail = (stderr or stdout or "").strip()[-500:]
            if returncode != 0:
                raise self.classify_error(detail)
            raise BackendError(f"could not parse claude code output: {detail}")

        result = payload.get("result")
        # the cli reports subtype "success" even on failures - is_error is authoritative
        if payload.get("is_error") or returncode != 0:
            detail = result if isinstance(result, str) and result else (stderr or "").strip()
            raise self.classify_error(detail or "unknown error", payload.get("api_error_status"))

        if not isinstance(result, str):
            raise BackendError("claude code returned no result text")

        usage = payload.get("usage") or {}
        log.debug(
            "claude code ok (in=%s out=%s cost=%s session=%s)",
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            payload.get("total_cost_usd"),
            payload.get("session_id"),
        )
        return result

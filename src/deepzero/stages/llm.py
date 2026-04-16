from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import jinja2

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorResult,
    ProcessorEntry,
)

_log = logging.getLogger("deepzero.stages.llm")


class GenericLLM(MapProcessor):
    description = (
        "generic LLM assessment - sends context to an LLM via a jinja2 prompt template"
    )

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        if ctx.llm is None:
            return ProcessorResult.fail("no llm provider configured")

        prompt_ref = self.config.get("prompt", "")
        if not prompt_ref:
            return ProcessorResult.fail("no prompt template configured")

        prompt_text = self._render_prompt(prompt_ref, ctx, entry)

        output_file = self.config.get("output_file", "assessment.md")
        output_path = entry.sample_dir / output_file
        if output_path.exists():
            self.log.info("output already cached: %s", output_path.name)
            content = output_path.read_text(encoding="utf-8", errors="replace")
            return self._make_result(content, output_file)

        max_retries = self.config.get("max_retries", 3)
        backoff_config = self.config.get("backoff", {})

        messages = [{"role": "user", "content": prompt_text}]

        response = ctx.llm.complete(
            messages,
            max_retries=max_retries,
            initial_backoff=backoff_config.get("initial", 2.0),
            max_backoff=backoff_config.get("max", 60.0),
            backoff_decay=backoff_config.get("decay", 0.7),
        )

        tmp = output_path.with_suffix(".tmp")
        tmp.write_text(response, encoding="utf-8")
        os.replace(tmp, output_path)
        self.log.info("response written to %s (%d chars)", output_file, len(response))

        return self._make_result(response, output_file)

    def _make_result(self, content: str, output_file: str) -> ProcessorResult:
        data: dict[str, Any] = {"llm_output_file": output_file}

        classify_by = self.config.get("classify_by", "")
        if classify_by:
            import re

            match = re.search(classify_by, content[:200], re.IGNORECASE)
            if match:
                verdict_text = match.group(0).strip("[]").lower()
                data["classification"] = verdict_text

        return ProcessorResult.ok(
            artifacts={"llm_output": output_file},
            data=data,
        )

    def _render_prompt(
        self, prompt_ref: str, ctx: ProcessorContext, entry: ProcessorEntry
    ) -> str:
        template_path = self._resolve_template(prompt_ref)

        if template_path is not None:
            raw = template_path.read_text(encoding="utf-8")
            template_vars = self._build_template_vars(ctx, entry)

            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(template_path.parent)),
                undefined=jinja2.Undefined,
                autoescape=jinja2.select_autoescape(),
            )
            template = env.from_string(raw)
            return template.render(**template_vars)

        return prompt_ref

    def _build_template_vars(
        self, ctx: ProcessorContext, entry: ProcessorEntry
    ) -> dict[str, Any]:
        template_vars: dict[str, Any] = {
            "sample_name": entry.upstream_data(
                "discover", "filename", entry.source_path.name
            ),
            "sample_path": str(entry.source_path),
            "history": {name: output.data for name, output in entry.history.items()},
            "config": self.config,
        }

        # flatten history data for backward compatibility with existing templates
        for output in entry.history.values():
            for k, v in output.data.items():
                if k not in template_vars:
                    template_vars[k] = v

        # scan sample_dir for artifact files
        for f in entry.sample_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(entry.sample_dir)
            key = str(rel).replace("\\", "/").replace("/", "_").replace(".", "_")

            if f.suffix == ".json":
                try:
                    template_vars[key] = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    _log.debug("skipping unreadable json artifact %s: %s", f.name, exc)
            elif f.suffix in (".c", ".h", ".txt", ".md", ".py", ".yaml", ".yml"):
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    max_tokens = self.config.get("max_context_tokens", 900_000)
                    char_budget = max_tokens * 4
                    if len(content) > char_budget:
                        content = (
                            content[:char_budget]
                            + f"\n... [truncated: {len(content)} -> {char_budget} chars]"
                        )
                    template_vars[key] = content
                except OSError as exc:
                    _log.debug("skipping unreadable text artifact %s: %s", f.name, exc)

        return template_vars

    def _resolve_template(self, ref: str) -> Path | None:
        if "/" in ref or "\\" in ref:
            resolved = (Path.cwd() / ref).resolve()
            if resolved.exists():
                return resolved
            return None

        abs_path = Path(ref)
        if abs_path.is_absolute() and abs_path.exists():
            return abs_path

        return None

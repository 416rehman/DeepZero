from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jinja2

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
    template_key_for_artifact,
)
from deepzero.engine.state import atomic_replace

# which artifacts beside a sample a prompt can read as text. A file whose
# extension is not here is invisible to the prompt however relevant it is, and
# nothing reports that, so the default covers the languages a source pipeline is
# likely to stage rather than only the C a decompiler writes. A pipeline
# producing something else entirely names its own set in `text_extensions`.
# .json is handled separately: it is parsed rather than pasted in.
DEFAULT_TEXT_EXTENSIONS: tuple[str, ...] = (
    ".c",
    ".cc",
    ".cfg",
    ".cjs",
    ".conf",
    ".cpp",
    ".cs",
    ".csv",
    ".css",
    ".cxx",
    ".diff",
    ".go",
    ".h",
    ".hh",
    ".hpp",
    ".htm",
    ".html",
    ".hxx",
    ".ini",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".log",
    ".lua",
    ".md",
    ".mjs",
    ".patch",
    ".php",
    ".pl",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsv",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
)


class GenericLLM(MapProcessor):
    description = "generic LLM assessment - sends context to an LLM via a jinja2 prompt template"

    # the response is also written as an artifact, but its name comes from this
    # stage's own `output_file` config, so it cannot be declared here. A prompt
    # in a later stage reaches it by that filename with the dot folded in.
    provides = ("llm_output_file", "classification")

    def validate(self, ctx: ProcessorContext) -> list[str]:
        errors = []

        prompt_ref = self.config.get("prompt")
        if not prompt_ref:
            errors.append("GenericLLM requires 'prompt' template mapping in config")
        else:
            prompt_path = (Path.cwd() / prompt_ref).resolve()
            if not prompt_path.exists():
                prompt_path = (ctx.pipeline_dir / prompt_ref).resolve()
            if not prompt_path.exists():
                errors.append(f"Prompt template does not exist: {prompt_ref}")

        # structurally validate LLM bindings early - each backend checks its own
        # prerequisites (api keys, cli presence, ...) via the registry
        model = ctx.global_config.get("model")
        if model:
            from deepzero.engine.backends import validate_model_binding

            errors.extend(validate_model_binding(model))

        return errors

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        if ctx.llm is None:
            return ProcessorResult.fail("no llm provider configured for generic_llm")

        prompt_ref = self.config.get("prompt", "")
        prompt_text = self._render_prompt(prompt_ref, ctx, entry)

        output_file = self.config.get("output_file", "assessment.md")
        output_path = entry.sample_dir / output_file
        # an answer already on disk is reused, but only while it is still an answer
        # to this question. An edited prompt or a changed config moves the stage's
        # input digest, and reading the old file back would record a reply to the
        # previous prompt as though the new one had been asked.
        if output_path.exists() and entry.cache_is_valid:
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

        # the model has already been paid for by this point, so an output_file
        # naming a subdirectory must not be what loses the response
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(".tmp")
        tmp.write_text(response, encoding="utf-8")
        atomic_replace(tmp, output_path)
        self.log.info("response written to %s (%d chars)", output_file, len(response))

        return self._make_result(response, output_file)

    def _make_result(self, content: str, output_file: str) -> ProcessorResult:
        data: dict[str, Any] = {"llm_output_file": output_file}

        classify_by = self.config.get("classify_by", "")
        if classify_by:
            import re

            # the verdict is asked for at the top, and reading only the top
            # stops a model discussing the words later in its reasoning from
            # being read as the verdict. A prompt with a longer preamble can say
            # so rather than losing every verdict past the default.
            window = int(self.config.get("classify_window", 200) or 200)
            match = re.search(classify_by, content[:window], re.IGNORECASE)
            if match:
                verdict_text = match.group(0).strip("[]").lower()
                data["classification"] = verdict_text

        return ProcessorResult.ok(
            artifacts={"llm_output": output_file},
            data=data,
        )

    def _render_prompt(self, prompt_ref: str, ctx: ProcessorContext, entry: ProcessorEntry) -> str:
        template_path = self._resolve_template(prompt_ref, ctx)

        if template_path is not None:
            raw = template_path.read_text(encoding="utf-8")
            template_vars = self._build_template_vars(ctx, entry)

            # a prompt that names a value the pipeline never produced would
            # otherwise render as empty and the model would be asked to judge
            # nothing, so an unknown name is an error naming what is available.
            #
            # a prompt is plain text, never a web page: escaping is off because
            # the values interpolated here are source code and decompiler output,
            # and html-escaping them sends the model `hdr-&gt;len` where the file
            # says `hdr->len`. select_autoescape() escapes string templates by
            # default, which is why this has to be said explicitly.
            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(template_path.parent)),
                undefined=jinja2.StrictUndefined,
                autoescape=False,
            )
            template = env.from_string(raw)
            try:
                return template.render(**template_vars)
            except jinja2.UndefinedError as exc:
                available = ", ".join(sorted(template_vars)) or "nothing"
                raise ValueError(
                    f"prompt {template_path.name} uses a value this pipeline does not "
                    f"produce: {exc}. available: {available}"
                ) from exc

        return prompt_ref

    def _text_extensions(self) -> set[str]:
        configured = self.config.get("text_extensions")
        if not configured:
            return set(DEFAULT_TEXT_EXTENSIONS)
        if isinstance(configured, str):
            configured = [configured]
        return {e if str(e).startswith(".") else f".{e}" for e in (str(x) for x in configured)}

    def _build_template_vars(self, ctx: ProcessorContext, entry: ProcessorEntry) -> dict[str, Any]:
        # read once: the history is loaded from disk on each access, so asking
        # for it twice reads every earlier stage's output twice per sample
        history = entry.history

        template_vars: dict[str, Any] = {
            # what the ingest named this sample, which is also the name the
            # report gives it. Deriving it from source_path instead would name a
            # repository after the directory its checkout happens to sit in.
            "sample_name": entry.filename or entry.source_path.name,
            "sample_path": str(entry.source_path),
            "history": {name: output.data for name, output in history.items()},
            "config": self.config,
        }

        # flatten history data for backward compatibility with existing templates
        for output in history.values():
            for k, v in output.data.items():
                if k not in template_vars:
                    template_vars[k] = v

        char_budget = self.config.get("max_context_tokens", 900_000) * 4
        text_extensions = self._text_extensions()

        # scan sample_dir for artifact files
        for f in entry.sample_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(entry.sample_dir)
            key = template_key_for_artifact(rel)
            suffix = f.suffix.lower()

            if suffix == ".json":
                # an artifact far larger than the whole prompt budget cannot be
                # used, and parsing it costs time and memory on every sample
                try:
                    if f.stat().st_size > char_budget:
                        self.log.warning(
                            "skipping %s: %d bytes exceeds the context budget of %d",
                            f.name,
                            f.stat().st_size,
                            char_budget,
                        )
                        continue
                    template_vars[key] = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    self.log.debug("skipping unreadable json artifact %s: %s", f.name, exc)
            elif suffix in text_extensions:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if len(content) > char_budget:
                        content = (
                            content[:char_budget]
                            + f"\n... [truncated: {len(content)} -> {char_budget} chars]"
                        )
                    template_vars[key] = content
                except OSError as exc:
                    self.log.debug("skipping unreadable text artifact %s: %s", f.name, exc)

        return template_vars

    def _resolve_template(self, ref: str, ctx: ProcessorContext | None = None) -> Path | None:
        """find the file a prompt reference names, or None if it names no file.

        A bare filename is resolved the same way a path is, because validate()
        accepts one that exists next to the pipeline. Treating it as inline here
        instead would send the model the filename as the entire request, and the
        run would look like it worked.
        """
        abs_path = Path(ref)
        if abs_path.is_absolute():
            return abs_path if abs_path.exists() else None

        for base in (Path.cwd(), ctx.pipeline_dir if ctx is not None else None):
            if base is None:
                continue
            resolved = (base / ref).resolve()
            if resolved.exists() and resolved.is_file():
                return resolved

        return None

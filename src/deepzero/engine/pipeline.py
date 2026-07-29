from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from deepzero.engine.stage import (
    BulkMapProcessor,
    FailurePolicy,
    GlobalConfig,
    IngestProcessor,
    MapProcessor,
    Processor,
    ReduceProcessor,
    StageSpec,
    resolve_processor_class,
)

log = logging.getLogger("deepzero.pipeline")


def corpus_segment(target: Path) -> str:
    """A stable, filesystem-safe directory segment identifying a corpus (the run
    target). Two different corpora, or the same corpus at two paths, never
    collide; the same resolved path always maps to the same segment, so a rerun
    resumes in place.

    Shape: ``<readable-basename>-<8 hex of sha256(resolved-abspath)>``.
    """
    resolved = target.expanduser().resolve()
    # case-fold on case-insensitive filesystems so C:\X and c:\x agree
    key_src = str(resolved).lower() if os.name == "nt" else str(resolved)
    digest = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:8]
    base = resolved.name or "root"
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:48].strip("._-") or "corpus"
    return f"{base}-{digest}"


class PipelineDefinition:
    # a loaded and validated pipeline ready for execution

    def __init__(
        self,
        name: str,
        description: str,
        model: str,
        settings: dict[str, Any],
        knowledge: dict[str, Any],
        stage_specs: list[StageSpec],
        pipeline_dir: Path,
        raw_yaml: str,
        report: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.model = model
        self.settings = settings
        self.knowledge = knowledge
        self.stage_specs = stage_specs
        self.pipeline_dir = pipeline_dir
        self.raw_yaml = raw_yaml
        # optional presentation hints for `deepzero report` - pipelines that
        # declare nothing still get a useful report
        self.report = report or {}

        # resolved processor instances
        self.ingest_processor: IngestProcessor | None = None
        self.stages: list[tuple[StageSpec, Processor]] = []

        # set once the run target is known (see bind_corpus); each corpus gets
        # its own isolated, resumable run directory under the pipeline.
        self.corpus_key: str | None = None

    @property
    def base_work_dir(self) -> Path:
        """The pipeline's root: ``<work_dir setting>/<pipeline name>``. Holds one
        subdirectory per corpus."""
        raw = self.settings.get("work_dir", "work")
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        return p / self.name

    @property
    def work_dir(self) -> Path:
        """The active run directory. Corpus-scoped once bound, so different
        targets through the same pipeline never share a sample store or report."""
        base = self.base_work_dir
        return base / self.corpus_key if self.corpus_key else base

    def bind_corpus(self, target: Path) -> None:
        """Scope this run's work directory to a specific corpus (run target).
        Must be called before ``work_dir`` is used for a run."""
        self.corpus_key = corpus_segment(target)

    @property
    def max_workers(self) -> int:
        return int(self.settings.get("max_workers", min(4, os.cpu_count() or 1)))

    @property
    def stage_names(self) -> list[str]:
        return [s.name for s in self.stage_specs]

    def to_global_config(self) -> GlobalConfig:
        return {
            "settings": self.settings,
            "knowledge": self.knowledge,
            "model": self.model,
        }


def load_pipeline(
    pipeline_ref: str,
    model_override: str | None = None,
    work_dir_override: str | None = None,
) -> PipelineDefinition:
    pipeline_dir, yaml_path = _resolve_pipeline_path(pipeline_ref)
    raw_yaml = yaml_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw_yaml)

    if not isinstance(data, dict):
        raise ValueError(f"pipeline yaml must be a mapping, got {type(data).__name__}")

    data = _expand_env_vars(data)

    name = data.get("name", pipeline_dir.name)
    description = data.get("description", "")
    model = model_override or data.get("model", "")
    settings = data.get("settings", {})
    knowledge = data.get("knowledge", {})

    if work_dir_override:
        settings["work_dir"] = work_dir_override

    raw_stages = data.get("stages", [])
    if not raw_stages:
        raise ValueError("pipeline must define at least one stage")

    stage_specs = []
    seen_names: set[str] = set()
    for i, raw in enumerate(raw_stages):
        if not isinstance(raw, dict):
            raise ValueError(f"stage {i} must be a mapping, got {type(raw).__name__}")

        stage_name = raw.get("name", f"stage_{i}")
        if stage_name in seen_names:
            raise ValueError(f"duplicate stage name: '{stage_name}'")
        seen_names.add(stage_name)

        processor_ref = raw.get("processor", "")
        if not processor_ref:
            raise ValueError(f"stage '{stage_name}' must have a 'processor' field")

        on_failure_raw = raw.get("on_failure", "skip")
        try:
            on_failure = FailurePolicy(on_failure_raw)
        except ValueError as exc:
            raise ValueError(
                f"stage '{stage_name}': invalid on_failure '{on_failure_raw}', must be skip/retry/abort"
            ) from exc

        spec = StageSpec(
            name=stage_name,
            processor=processor_ref,
            config=raw.get("config", {}),
            parallel=int(raw.get("parallel", 4)),
            on_failure=on_failure,
            max_retries=int(raw.get("max_retries", 0)),
            timeout=int(raw.get("timeout", 0)),
        )
        stage_specs.append(spec)

    pipeline = PipelineDefinition(
        name=name,
        description=description,
        model=model,
        report=data.get("report") or {},
        settings=settings,
        knowledge=knowledge,
        stage_specs=stage_specs,
        pipeline_dir=pipeline_dir,
        raw_yaml=raw_yaml,
    )

    _resolve_processors(pipeline)
    _validate_pipeline_graph(pipeline)

    return pipeline


def _resolve_processors(pipeline: PipelineDefinition) -> None:
    for i, spec in enumerate(pipeline.stage_specs):
        cls = resolve_processor_class(spec.processor)
        instance = cls(spec)

        if i == 0:
            if not isinstance(instance, IngestProcessor):
                raise ValueError(
                    f"first stage '{spec.name}' (processor='{spec.processor}') must be an IngestProcessor. "
                    f"got {cls.__name__}. every pipeline must start with an ingest processor."
                )
            pipeline.ingest_processor = instance
        else:
            if isinstance(instance, IngestProcessor):
                raise ValueError(
                    f"stage '{spec.name}' at position {i} is an IngestProcessor. "
                    "only the first stage can be an ingest processor."
                )
            if not isinstance(instance, (MapProcessor, ReduceProcessor, BulkMapProcessor)):
                raise ValueError(
                    f"stage '{spec.name}' at position {i} must be a MapProcessor, ReduceProcessor, or BulkMapProcessor. "
                    f"got {cls.__name__}."
                )
            pipeline.stages.append((spec, instance))

    log.info(
        "pipeline '%s' loaded: %d stages [%s]",
        pipeline.name,
        len(pipeline.stage_specs),
        " -> ".join(pipeline.stage_names),
    )


def _validate_pipeline_graph(pipeline: PipelineDefinition) -> None:
    errors: list[str] = []

    all_processors = []
    if pipeline.ingest_processor:
        all_processors.append(pipeline.ingest_processor)

    for _, proc in pipeline.stages:
        all_processors.append(proc)
    from deepzero.engine.stage import ProcessorContext

    ctx = ProcessorContext(
        pipeline_dir=pipeline.pipeline_dir,
        global_config={
            "model": pipeline.model,
            "settings": pipeline.settings,
            "knowledge": pipeline.knowledge,
        },
        llm=None,
    )

    # run processor-level validation
    for proc in all_processors:
        problems = proc.validate(ctx)
        for p in problems:
            errors.append(f"processor '{proc.spec.name}': {p}")

    if errors:
        raise ValueError("pipeline validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


def _resolve_pipeline_path(ref: str) -> tuple[Path, Path]:
    ref_path = Path(ref)

    if ref_path.is_file() and ref_path.suffix in (".yaml", ".yml"):
        return ref_path.parent, ref_path

    if ref_path.is_dir():
        yaml_path = ref_path / "pipeline.yaml"
        if yaml_path.exists():
            return ref_path, yaml_path
        yml_path = ref_path / "pipeline.yml"
        if yml_path.exists():
            return ref_path, yml_path
        raise FileNotFoundError(f"no pipeline.yaml found in {ref_path}")

    search_paths = [
        Path.cwd() / "pipelines" / ref,
        Path.home() / ".deepzero" / "pipelines" / ref,
        Path(__file__).parent.parent.parent.parent / "pipelines" / ref,
    ]

    for candidate in search_paths:
        if candidate.is_dir():
            yaml_path = candidate / "pipeline.yaml"
            if yaml_path.exists():
                return candidate, yaml_path
            yml_path = candidate / "pipeline.yml"
            if yml_path.exists():
                return candidate, yml_path
        yaml_file = candidate.with_suffix(".yaml")
        if yaml_file.is_file():
            return yaml_file.parent, yaml_file

    raise FileNotFoundError(
        f"pipeline '{ref}' not found. searched:\n" + "\n".join(f"  - {p}" for p in search_paths)
    )


def _expand_env_vars(obj: Any) -> Any:
    if isinstance(obj, str):
        return _expand_string(obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(v) for v in obj]
    return obj


def _expand_string(s: str) -> str:
    import re

    def _replace(match: re.Match) -> str:
        var = match.group(1)
        if ":-" in var:
            name, default = var.split(":-", 1)
            return os.environ.get(name, default)
        # an unset var expands to empty rather than leaking the literal "${VAR}",
        # which would read as a truthy value downstream and produce confusing
        # errors like "ghidra not found at ${GHIDRA_INSTALL_DIR}"
        return os.environ.get(var, "")

    return re.sub(r"\$\{([^}]+)\}", _replace, s)


# suffixes that mean a prompt value was naming a file rather than being one
_PROMPT_SUFFIXES = frozenset({".j2", ".jinja", ".jinja2", ".md", ".txt", ".tmpl", ".prompt"})


def _check_prompts(pipeline: PipelineDefinition, resolved: dict[str, type]) -> list[str]:
    """report prompt values no earlier stage in this pipeline produces.

    A prompt is rendered from whatever the stages before it recorded, so a name
    none of them produce is only ever going to render as nothing. Reaching the
    model with an empty payload looks like a working run - the verdict comes
    back confident and says nothing - so it is caught here instead.
    """
    import jinja2
    from jinja2 import meta

    from deepzero.engine.stage import ALWAYS_PROVIDED

    problems: list[str] = []
    available = set(ALWAYS_PROVIDED)
    # only ever parses, never renders, but it matches how the prompt is rendered
    # at run time so the two cannot disagree about what the template means
    env = jinja2.Environment(autoescape=jinja2.select_autoescape())

    for spec in pipeline.stage_specs:
        prompt_ref = str((spec.config or {}).get("prompt", "") or "")
        # a value carrying a separator or a template suffix was meant to name a
        # file. Anything else is an inline prompt, which has no names to resolve.
        # A filename that does not resolve is worth reporting either way: the
        # engine would take it for an inline prompt and send the model the
        # filename itself as the entire request.
        named_a_file = bool(prompt_ref) and (
            "/" in prompt_ref
            or "\\" in prompt_ref
            or Path(prompt_ref).suffix.lower() in _PROMPT_SUFFIXES
        )
        if named_a_file:
            path = Path(prompt_ref)
            for candidate in (Path.cwd() / path, pipeline.pipeline_dir / path):
                if candidate.exists():
                    try:
                        source = candidate.read_text(encoding="utf-8")
                    except OSError as exc:
                        problems.append(f"ERROR: {spec.name}: cannot read {path.name}: {exc}")
                        break
                    try:
                        used = meta.find_undeclared_variables(env.parse(source))
                    except jinja2.TemplateSyntaxError as exc:
                        problems.append(f"ERROR: {spec.name}: {path.name} will not parse: {exc}")
                        break
                    unknown = sorted(used - available)
                    if unknown:
                        problems.append(
                            f"ERROR: {spec.name}: {path.name} uses "
                            f"{', '.join(unknown)}, which no earlier stage produces. "
                            f"available here: {', '.join(sorted(available))}"
                        )
                    break
            # a prompt that resolves to nothing is reported by the processor's own
            # validate(), which runs before this and knows what its config means

        cls = resolved.get(spec.name)
        if cls is not None:
            available.update(getattr(cls, "provides", ()))

    return problems


def validate_pipeline(pipeline_ref: str) -> list[str]:
    warnings: list[str] = []

    try:
        pipeline = load_pipeline(pipeline_ref)
    except (ValueError, FileNotFoundError, ImportError, yaml.YAMLError) as e:
        return [f"ERROR: {e}"]

    if not pipeline.model:
        warnings.append("no model configured - stages that need an LLM will fail")

    from deepzero.engine.stage import ProcessorType

    proc_types = []
    resolved: dict[str, type] = {}
    for spec in pipeline.stage_specs:
        try:
            cls = resolve_processor_class(spec.processor)
            stype = getattr(cls, "processor_type", None)
            proc_types.append((spec.name, stype))
            resolved[spec.name] = cls
        except (
            ValueError,
            FileNotFoundError,
            ImportError,
            AttributeError,
            TypeError,
        ) as exc:
            log.debug("processor resolution failed for '%s': %s", spec.name, exc)
            proc_types.append((spec.name, None))

    has_map = any(st == ProcessorType.MAP for _, st in proc_types)
    if not has_map:
        warnings.append("no map processors found - pipeline has no sample processing stages")

    warnings.extend(_check_prompts(pipeline, resolved))

    if not warnings:
        warnings.append("pipeline is valid - no issues found")

    return warnings

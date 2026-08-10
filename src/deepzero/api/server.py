from __future__ import annotations

import asyncio
import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import JSONResponse as JSONResponseType

log = logging.getLogger("deepzero.api")


def _extract_classification(sample, key: str = "classification") -> str:
    """the verdict a stage recorded, under whatever key this pipeline uses.

    A pipeline names the key itself through report.classification_key, so
    assuming "classification" answers correctly only for the pipelines that
    happen to keep the default and returns nothing at all for any other, which
    reads as "no verdict" rather than as a lookup that missed.
    """
    for stage_output in sample.history.values():
        classification = stage_output.data.get(key, "")
        if classification:
            return classification
    return ""


def _is_plain_segment(sample_id: str) -> bool:
    """Whether a sample id addresses one entry inside the sample store.

    The id arrives from the request path, and the store builds a filesystem path
    out of it, so anything carrying a separator or a parent reference would
    reach outside the work directory entirely - on a server the CLI will bind to
    every interface on request.
    """
    return bool(sample_id) and sample_id not in (".", "..") and not set(sample_id) & set("/\\")


def _read_artifact(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def create_app(work_dir: Path, classification_key: str = "classification"):
    try:
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
    except ImportError as exc:
        raise ImportError("starlette required for serve mode: pip install deepzero[serve]") from exc

    from deepzero.engine.state import StateStore

    store = StateStore(work_dir)

    async def _run_sync(fn, *args):
        # run synchronous file I/O in a thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(fn, *args))

    async def health(request: Request) -> JSONResponseType:
        return JSONResponse({"status": "ok", "work_dir": str(work_dir)})

    async def get_runs(request: Request) -> JSONResponseType:
        run_state = await _run_sync(store.load_run)
        if run_state is None:
            return JSONResponse({"runs": []})

        from dataclasses import asdict

        return JSONResponse({"runs": [asdict(run_state)]})

    async def get_run(request: Request) -> JSONResponseType:
        run_state = await _run_sync(store.load_run)
        if run_state is None:
            return JSONResponse({"error": "no run found"}, status_code=404)

        from dataclasses import asdict

        return JSONResponse(asdict(run_state))

    async def get_samples(request: Request) -> JSONResponseType:
        samples = await _run_sync(store.list_samples)

        # filtering. a sample's verdict is where it left the pipeline; its
        # classification is what a stage decided about it. the response carries
        # both, so each filters the field it is named after
        verdict = request.query_params.get("verdict")
        classification_filter = request.query_params.get("classification")
        stage = request.query_params.get("stage")
        status_filter = request.query_params.get("status")

        results = []
        for s in samples:
            # classification lives in the stage data dicts, not a top-level attribute
            classification = _extract_classification(s, classification_key)

            if verdict and s.verdict != verdict:
                continue
            if classification_filter and classification != classification_filter:
                continue
            if stage and s.current_stage != stage:
                continue
            if status_filter:
                if not any(st.status == status_filter for st in s.history.values()):
                    continue

            results.append(
                {
                    "sample_id": s.sample_id,
                    "filename": s.filename,
                    "current_stage": s.current_stage,
                    "classification": classification,
                    "verdict": s.verdict,
                    "error": s.error,
                }
            )

        return JSONResponse({"samples": results, "total": len(results)})

    async def get_sample(request: Request) -> JSONResponseType:
        sample_id = request.path_params["sample_id"]
        if not _is_plain_segment(sample_id):
            return JSONResponse({"error": "invalid sample id"}, status_code=400)

        state = await _run_sync(store.load_sample, sample_id)

        if state is None:
            return JSONResponse({"error": f"sample {sample_id} not found"}, status_code=404)

        from deepzero.engine.state import sample_to_dict

        return JSONResponse(sample_to_dict(state))

    async def get_sample_artifact(request: Request) -> JSONResponseType:
        sample_id = request.path_params["sample_id"]
        artifact_name = request.path_params["name"]
        if not _is_plain_segment(sample_id):
            return JSONResponse({"error": "invalid sample id"}, status_code=400)

        state = await _run_sync(store.load_sample, sample_id)

        if state is None:
            return JSONResponse({"error": "sample not found"}, status_code=404)

        sample_dir = store.sample_dir(sample_id, create=False)

        # find artifact path from state
        for stage_state in state.history.values():
            for aname, apath in stage_state.artifacts.items():
                if aname == artifact_name:
                    full_path = sample_dir / apath
                    if full_path.exists():
                        content = await _run_sync(_read_artifact, full_path)
                        return JSONResponse({"artifact": artifact_name, "content": content})

        return JSONResponse({"error": f"artifact '{artifact_name}' not found"}, status_code=404)

    routes = [
        Route("/api/health", health),
        Route("/api/runs", get_runs),
        Route("/api/run", get_run),
        Route("/api/samples", get_samples),
        Route("/api/samples/{sample_id}", get_sample),
        Route("/api/samples/{sample_id}/artifacts/{name}", get_sample_artifact),
    ]

    return Starlette(routes=routes)

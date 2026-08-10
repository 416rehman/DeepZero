from __future__ import annotations

import http.client
import json
import os
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
    StageSpec,
)

LOLDRIVERS_URL = "https://www.loldrivers.io/api/drivers.json"
LOLDRIVERS_CACHE_FILE = "loldrivers.io.json"


def _user_agent() -> str:
    # taken from the installed package rather than written out here, where it
    # went stale against every release that did not think to update it
    try:
        return f"deepzero/{version('deepzero')}"
    except PackageNotFoundError:
        return "deepzero"


@dataclass
class LoldriversFilterConfig:
    # a copy of the database to read instead of fetching one. relative paths
    # resolve against the working directory, then against the pipeline directory
    db_path: str = ""
    cache_ttl_days: int = 7


class LoldriversFilter(MapProcessor):
    description = (
        "excludes samples whose sha256 matches a known entry in the loldrivers.io database"
    )
    Config = LoldriversFilterConfig

    # whether the database was actually consulted for this sample. Without it a
    # run where the database could not be fetched is indistinguishable from one
    # where nothing matched, and every known-vulnerable driver in the corpus
    # would be reported as new.
    provides = ("loldrivers_checked",)

    def __init__(self, spec: StageSpec):
        super().__init__(spec)
        self._known_hashes: set[str] = set()
        # setup() is handed the global config rather than a context, so the
        # directory a relative db_path may resolve against is kept from validate()
        self._pipeline_dir: Path | None = None

    def validate(self, ctx: ProcessorContext) -> list[str]:
        self._pipeline_dir = ctx.pipeline_dir
        # a db_path that resolves to nothing is a typo, not a request to go to
        # the network: say so before the run rather than quietly downloading a
        # different database than the one that was asked for
        if self.config.db_path and self._configured_db() is None:
            return [f"db_path does not exist: {self.config.db_path}"]
        return []

    def setup(self, global_config: dict[str, Any]) -> None:
        db_path = self._resolve_db()
        if db_path is not None and db_path.exists():
            self._load_db(db_path)
        if not self._known_hashes:
            self.log.warning(
                "no loldrivers database available, so nothing will be excluded here - "
                "set db_path to a local copy to filter without network access"
            )

    def _configured_db(self) -> Path | None:
        # resolved the same way every other path-taking config in this project
        # is: absolute as given, otherwise against the working directory and
        # then against the pipeline directory
        raw_path = (self.config.db_path or "").strip()
        if not raw_path:
            return None
        if Path(raw_path).is_absolute():
            candidates = [Path(raw_path)]
        else:
            candidates = [Path.cwd() / raw_path]
            if self._pipeline_dir is not None:
                candidates.append(self._pipeline_dir / raw_path)
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return None

    def _resolve_db(self) -> Path | None:
        configured = self._configured_db()
        if configured is not None:
            return configured
        if self.config.db_path:
            self.log.info("db_path '%s' not found, will auto-download", self.config.db_path)

        cached = self.cache_dir / LOLDRIVERS_CACHE_FILE
        ttl = self.config.cache_ttl_days

        if cached.exists():
            age_days = (time.time() - cached.stat().st_mtime) / 86400
            if age_days < ttl:
                self.log.info("using cached db (%.1f days old)", age_days)
                return cached
            self.log.info("cached db is %.1f days old (ttl=%d), refreshing", age_days, ttl)

        return self._download(cached)

    def _download(self, dest: Path) -> Path | None:
        self.log.info("downloading loldrivers database from %s", LOLDRIVERS_URL)

        from urllib.parse import urlparse

        parsed = urlparse(LOLDRIVERS_URL)
        if parsed.scheme != "https":
            self.log.warning("refusing to fetch non-https url: %s", LOLDRIVERS_URL)
            return None

        conn = None
        try:
            conn = http.client.HTTPSConnection(parsed.netloc, timeout=30)
            conn.request("GET", parsed.path, headers={"User-Agent": _user_agent()})
            resp = conn.getresponse()
            if resp.status != 200:
                self.log.warning("download failed, HTTP %d", resp.status)
                return None
            data = resp.read()

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            self.log.info("saved %d bytes to %s", len(data), dest)
            return dest
        except (OSError, ValueError, http.client.HTTPException) as e:
            self.log.warning("download failed (%s): %s", type(e).__name__, e)
            return None
        finally:
            # a response left unread on an error path holds the socket open for
            # the rest of the run
            if conn is not None:
                conn.close()

    def _load_db(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            count = 0
            if isinstance(data, list):
                for entry in data:
                    for sample in entry.get("KnownVulnerableSamples", []):
                        sha = sample.get("SHA256", "")
                        if sha:
                            self._known_hashes.add(sha.lower())
                            count += 1
            self.log.info("loaded %d known hashes from %s", count, path.name)
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
            self.log.warning("failed to parse db: %s", e)

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        if not self._known_hashes:
            # the run goes on: a database that could not be fetched is no reason
            # to lose a corpus. But every sample records that it passed this
            # stage unchecked, so a report cannot read "not known vulnerable"
            # into what is really "not looked up".
            return ProcessorResult.ok(data={"loldrivers_checked": False})

        sha = ""
        for output in entry.history.values():
            if "sha256" in output.data:
                sha = str(output.data["sha256"]).lower()
                break

        if sha and sha in self._known_hashes:
            return ProcessorResult.filter(
                "already in loldrivers.io database", data={"loldrivers_checked": True}
            )

        if not sha:
            # nothing upstream recorded a hash, so the comparison never happened
            self.log.debug("%s has no sha256 recorded, nothing to look up", entry.filename)
            return ProcessorResult.ok(data={"loldrivers_checked": False})

        return ProcessorResult.ok(data={"loldrivers_checked": True})

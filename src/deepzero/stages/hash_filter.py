from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from deepzero.engine.stage import (
    MapProcessor,
    ProcessorContext,
    ProcessorEntry,
    ProcessorResult,
    StageSpec,
)


class HashExclude(MapProcessor):
    description = (
        "hash-based exclusion filter - skips samples whose hash matches a known set, "
        "and optionally drops repeats of a hash already seen in this run"
    )

    def __init__(self, spec: StageSpec):
        super().__init__(spec)
        self._exclude_hashes: set[str] = set()
        # the exclusion list is fixed before any sample is touched, but this one
        # is built as the run goes, and a Map runs across a thread pool. Testing
        # membership and adding are two separate steps, so without this lock two
        # threads carrying the same hash can both find it absent and both pass,
        # which is silently the opposite of what dedup was asked to do.
        self._seen_hashes: set[str] = set()
        self._seen_lock = threading.Lock()

    def _resolve_hash_file(self) -> Path | None:
        hash_file = str(self.config.get("hash_file", "") or "")
        if not hash_file:
            return None
        path = Path(hash_file)
        return path if path.is_absolute() else Path.cwd() / path

    def validate(self, ctx: ProcessorContext) -> list[str]:
        # a hash_file that is not there excludes nothing at all, and the run
        # still completes, so it has to be reported before the run rather than
        # left as one warning in the log of a corpus that came back untouched
        path = self._resolve_hash_file()
        if path is not None and not path.exists():
            return [f"hash_file does not exist: {path}"]
        return []

    def setup(self, global_config: dict[str, Any]) -> None:
        # inline hashes. `hashes:` written with nothing under it parses as null,
        # which should exclude nothing rather than abort the run before it starts
        inline = self.config.get("hashes") or []
        for h in inline:
            self._exclude_hashes.add(str(h).strip().lower())

        # hash file (one per line)
        path = self._resolve_hash_file()
        if path is not None:
            if path.exists():
                from_file = 0
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines:
                    h = line.strip().lower()
                    if h and not h.startswith("#"):
                        self._exclude_hashes.add(h)
                        from_file += 1
                self.log.info("loaded %d hashes from %s", from_file, path.name)
            else:
                self.log.warning("hash_file not found: %s", path)

        if self._exclude_hashes:
            self.log.info("excluding %d known hashes", len(self._exclude_hashes))

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        hash_field = self.config.get("hash_field", "sha256")
        dedup = self.config.get("dedup", False)

        sample_hash = ""
        for output in entry.history.values():
            if hash_field in output.data:
                sample_hash = str(output.data[hash_field]).lower()
                break

        if not sample_hash:
            return ProcessorResult.ok()

        if dedup:
            with self._seen_lock:
                first = sample_hash not in self._seen_hashes
                self._seen_hashes.add(sample_hash)
            if not first:
                return ProcessorResult.filter(f"duplicate {hash_field}")

        if sample_hash in self._exclude_hashes:
            return ProcessorResult.filter("hash in exclusion list")

        return ProcessorResult.ok()

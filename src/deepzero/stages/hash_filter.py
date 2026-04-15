from __future__ import annotations

from pathlib import Path
from typing import Any

from deepzero.engine.stage import MapTool, StageContext, StageResult, StageSpec


class HashExclude(MapTool):
    # generic hash-based exclusion filter - skips samples whose hash matches a known set

    def __init__(self, spec: StageSpec):
        super().__init__(spec)
        self._exclude_hashes: set[str] = set()
        self._seen_hashes: set[str] = set()

    def setup(self, global_config: dict[str, Any]) -> None:
        config = self.spec.config

        # inline hashes
        inline = config.get("hashes", [])
        for h in inline:
            self._exclude_hashes.add(str(h).strip().lower())

        # hash file (one per line)
        hash_file = config.get("hash_file", "")
        if hash_file:
            path = Path(hash_file)
            if not path.is_absolute():
                path = Path.cwd() / path
            if path.exists():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines:
                    h = line.strip().lower()
                    if h and not h.startswith("#"):
                        self._exclude_hashes.add(h)
                self.log.info("loaded %d hashes from %s", len(self._exclude_hashes), path.name)
            else:
                self.log.warning("hash_file not found: %s", path)

        if self._exclude_hashes:
            self.log.info("excluding %d known hashes", len(self._exclude_hashes))

    def process(self, ctx: StageContext) -> StageResult:
        config = ctx.config
        hash_field = config.get("hash_field", "sha256")
        dedup = config.get("dedup", False)

        # find the hash in upstream history
        sample_hash = ""
        for output in ctx.history.values():
            if hash_field in output.data:
                sample_hash = str(output.data[hash_field]).lower()
                break

        if not sample_hash:
            return StageResult(status="completed", verdict="continue")

        # dedup check
        if dedup:
            if sample_hash in self._seen_hashes:
                return StageResult(
                    status="completed", verdict="skip",
                    data={"reject_reason": f"duplicate {hash_field}"},
                )
            self._seen_hashes.add(sample_hash)

        # exclusion check
        if sample_hash in self._exclude_hashes:
            return StageResult(
                status="completed", verdict="skip",
                data={"reject_reason": "hash in exclusion list"},
            )

        return StageResult(status="completed", verdict="continue")

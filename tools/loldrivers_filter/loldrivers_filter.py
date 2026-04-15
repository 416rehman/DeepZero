from __future__ import annotations

import http.client
import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any

from deepzero.engine.stage import MapTool, StageContext, StageResult, StageSpec

LOLDRIVERS_URL = "https://www.loldrivers.io/api/drivers.json"
LOLDRIVERS_CACHE_FILE = "loldrivers.io.json"


class LoldriversFilter(MapTool):
    # skips samples whose sha256 matches a known entry in the loldrivers.io database

    def __init__(self, spec: StageSpec):
        super().__init__(spec)
        self._known_hashes: set[str] = set()

    def setup(self, global_config: dict[str, Any]) -> None:
        db_path = self._resolve_db()
        if db_path is not None and db_path.exists():
            self._load_db(db_path)

    def _resolve_db(self) -> Path | None:
        db_path_raw = self.spec.config.get("db_path", "")

        if db_path_raw:
            db_path = Path(db_path_raw)
            if db_path.is_absolute() and db_path.exists():
                return db_path
            self.log.info("db_path '%s' not found, will auto-download", db_path_raw)

        cached = self.cache_dir / LOLDRIVERS_CACHE_FILE
        ttl = self.spec.config.get("cache_ttl_days", 7)

        if cached.exists():
            age_days = (time.time() - cached.stat().st_mtime) / 86400
            if age_days < ttl:
                self.log.info("using cached db (%.1f days old)", age_days)
                return cached
            self.log.info("cached db is %.1f days old (ttl=%d), refreshing", age_days, ttl)

        return self._download(cached)

    def _download(self, dest: Path) -> Path | None:
        self.log.info("downloading loldrivers database from %s", LOLDRIVERS_URL)

        # only allow https to prevent file:/ or custom scheme abuse (B310)
        from urllib.parse import urlparse
        parsed = urlparse(LOLDRIVERS_URL)
        if parsed.scheme != "https":
            self.log.warning("refusing to fetch non-https url: %s", LOLDRIVERS_URL)
            return None

        try:
            conn = http.client.HTTPSConnection(parsed.netloc, timeout=30)
            conn.request("GET", parsed.path, headers={"User-Agent": "deepzero/0.2"})
            resp = conn.getresponse()
            if resp.status != 200:
                self.log.warning("download failed, HTTP %d", resp.status)
                return None
            data = resp.read()
            conn.close()
            
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            self.log.info("saved %d bytes to %s", len(data), dest)
            return dest
        except (OSError, ValueError, http.client.HTTPException) as e:
            self.log.warning("download failed (%s): %s", type(e).__name__, e)
            return None

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

    def process(self, ctx: StageContext) -> StageResult:
        if not self._known_hashes:
            return StageResult(status="completed", verdict="continue")

        # find sha256 from upstream history
        sha = ""
        for output in ctx.history.values():
            if "sha256" in output.data:
                sha = str(output.data["sha256"]).lower()
                break

        if sha and sha in self._known_hashes:
            return StageResult(
                status="completed", verdict="skip",
                data={"reject_reason": "already in loldrivers.io database"},
            )

        return StageResult(status="completed", verdict="continue")

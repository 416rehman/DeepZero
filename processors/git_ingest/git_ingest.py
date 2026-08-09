from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from deepzero.engine.stage import IngestProcessor, ProcessorContext, Sample

# what one file's extension says the file is written in. a source pipeline
# narrows this with `languages` or `extensions` when it only cares about some
# of them, or replaces it entirely with a mapping of its own.
DEFAULT_LANGUAGES: dict[str, tuple[str, ...]] = {
    "c": (".c", ".h"),
    "cpp": (".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"),
    "csharp": (".cs",),
    "go": (".go",),
    "java": (".java",),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "kotlin": (".kt", ".kts"),
    "lua": (".lua",),
    "objectivec": (".m", ".mm"),
    "php": (".php",),
    "python": (".py", ".pyi"),
    "ruby": (".rb",),
    "rust": (".rs",),
    "scala": (".scala",),
    "shell": (".sh", ".bash"),
    "sql": (".sql",),
    "swift": (".swift",),
    "typescript": (".ts", ".tsx"),
}

# the file whose presence says a repository declares third-party dependencies,
# which is what a later stage needs to decide whether supply chain checks apply
DEPENDENCY_MANIFESTS = (
    "package.json",
    "go.mod",
    "requirements.txt",
    "pom.xml",
    "Cargo.toml",
    "Gemfile",
    "composer.json",
)

# directories that hold code nobody in this repository wrote, plus build output
DEFAULT_EXCLUDES = (".git", "node_modules", "vendor", "dist", "build", "testdata")

# git@host:owner/name.git - a url urlparse cannot read because it has no scheme
_SCP_LIKE = re.compile(r"^(?P<user>[\w.\-+]+)@(?P<host>[\w.\-]+):(?P<path>.+)$")

# owner/name with nothing else, the short form a hand-written manifest uses
_SHORTHAND = re.compile(r"^[\w.\-]+/[\w.\-]+$")

# how many files to walk before asking whether the run is still wanted
_SHUTDOWN_CHECK_FILES = 2000


@dataclass(frozen=True)
class _RepoRef:
    host: str = ""
    owner: str = ""
    name: str = ""


@dataclass
class _Checkout:
    # the tree to hand downstream as the sample's source_path
    path: Path
    # what the manifest asked for, empty when the checkout was already on disk
    url: str = ""
    ref: str = ""
    # "cloned", "reused" or "directory" - how this tree came to be here
    origin: str = "directory"


class GitIngest(IngestProcessor):
    description = (
        "turns git repositories into samples, from a directory of checkouts or a manifest of urls"
    )
    version = "1.0"

    # host, owner and ref are only recorded when they can be derived: a checkout
    # with no origin remote, or a manifest naming a local path, has no host to
    # report. A prompt should tolerate any of them being empty.
    provides = (
        "repo_url",
        "repo_host",
        "repo_owner",
        "repo_name",
        "repo_full_name",
        "commit_sha",
        "default_branch",
        "ref",
        "checkout_source",
        "total_files",
        "source_files",
        "total_loc",
        "languages",
        "primary_language",
        "dependency_manifests",
        "has_dependency_manifest",
    )

    @dataclass
    class Config:
        # which languages to count. a list of names selects from the built-in
        # map; a mapping of name -> extensions counts something it does not know.
        languages: list[str] | dict[str, list[str]] = field(default_factory=list)
        # count only these extensions. one an unknown language uses is counted
        # under its own bare name, so `[".zig"]` reports a "zig" breakdown.
        extensions: list[str] = field(default_factory=list)
        # false clones full history, which a pipeline that reads commits needs
        shallow: bool = True
        clone_depth: int = 1
        # where clones live. relative paths resolve against the working
        # directory; empty puts them under this stage's own cache.
        cache_dir: str = ""
        # fetch existing clones instead of using them as they are. off by
        # default so a rerun costs no network at all.
        refresh: bool = False
        exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
        # a file larger than this is still counted as a file of its language,
        # but its lines are not read - generated bundles are not worth the io
        max_file_bytes: int = 2_000_000
        clone_timeout: int = 900

    def validate(self, ctx: ProcessorContext) -> list[str]:
        errors = []
        if not shutil.which("git"):
            errors.append("git not found in PATH - install git to clone or read repositories")
        if self.config.shallow and int(self.config.clone_depth or 0) < 1:
            errors.append("clone_depth must be at least 1 when shallow is true")
        if not self._language_map():
            errors.append("no languages left to count - check the languages/extensions config")
        return errors

    def process(self, ctx: ProcessorContext, target: Path) -> list[Sample]:
        # a directory is a corpus that is already on disk, a file is a list of
        # repositories to fetch. both are real paths, which is what keeps the
        # run resumable and scoped to one corpus.
        cloned = 0
        if target.is_dir():
            checkouts = self._checkouts_from_directory(target)
        elif target.is_file():
            checkouts, cloned = self._checkouts_from_manifest(ctx, target)
        else:
            self.log.error("target does not exist: %s", target)
            return []

        if not checkouts:
            return []

        start = time.monotonic()
        # cloning already advanced the bar once per manifest entry, so reading
        # extends the total rather than restarting it behind the count
        ctx.progress.update(total=cloned + len(checkouts), description="reading checkouts...")

        # the engine keys samples by id, so two trees that are the same
        # repository have to be collapsed here or one of them disappears
        # without anything saying so
        samples: dict[str, Sample] = {}
        for checkout in checkouts:
            if self._interrupted(ctx):
                break
            sample = self._describe(ctx, checkout)
            ctx.progress.update(amount=1, description=sample.filename)
            first = samples.get(sample.sample_id)
            if first is not None:
                self.log.warning(
                    "%s is the same repository as %s, reading it once",
                    checkout.path.name,
                    first.source_path.name,
                )
                continue
            samples[sample.sample_id] = sample

        self.log.info(
            "ingest complete: %d repositories in %.1fs",
            len(samples),
            time.monotonic() - start,
        )
        return list(samples.values())

    # -- discovering checkouts --

    def _checkouts_from_directory(self, target: Path) -> list[_Checkout]:
        # a target that is itself a checkout is one repository, not a container
        if (target / ".git").exists():
            return [_Checkout(path=target)]

        try:
            children = sorted(p for p in target.iterdir() if p.is_dir())
        except OSError as exc:
            self.log.error("cannot list %s: %s", target, exc)
            return []

        checkouts = []
        for child in children:
            if child.name.startswith("."):
                continue
            if not (child / ".git").exists():
                # still worth reading: a source drop counts the same, it just
                # has no commit or url to report
                self.log.debug("%s has no .git, reading it as a plain source tree", child.name)
            checkouts.append(_Checkout(path=child))

        if not checkouts:
            self.log.warning("no repository directories under %s", target)
        else:
            self.log.info("found %d repository directories in %s", len(checkouts), target)
        return checkouts

    def _checkouts_from_manifest(
        self, ctx: ProcessorContext, manifest: Path
    ) -> tuple[list[_Checkout], int]:
        """clone everything the manifest lists, and say how many it tried."""
        entries = self._read_manifest(manifest)
        if not entries:
            self.log.error("manifest %s lists no repositories", manifest)
            return [], 0

        cache_root = self._cache_root()
        try:
            cache_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.log.error("cannot create clone cache %s: %s", cache_root, exc)
            return [], 0

        self.log.info("manifest lists %d repositories, cloning into %s", len(entries), cache_root)
        ctx.progress.update(total=len(entries), description="cloning repositories...")

        checkouts = []
        attempted = 0
        for url, ref in entries:
            if self._interrupted(ctx):
                break
            attempted += 1
            checkout = self._ensure_clone(ctx, url, ref, self._dest_for(url))
            ctx.progress.update(amount=1, description=url)
            if checkout is not None:
                checkouts.append(checkout)

        if attempted < len(entries):
            self.log.warning("stopped after %d of %d repositories", attempted, len(entries))
        failed = attempted - len(checkouts)
        if failed > 0:
            # one unreachable repository is not a reason to lose the rest
            self.log.warning("%d of %d repositories could not be cloned", failed, attempted)
        return checkouts, attempted

    def _read_manifest(self, manifest: Path) -> list[tuple[str, str]]:
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.log.error("cannot read manifest %s: %s", manifest, exc)
            return []

        raw = self._parse_yaml(text) if _looks_like_yaml(manifest, text) else _parse_lines(text)

        # the same repository listed twice is one sample, and the first spelling
        # of it wins so the order of the manifest is preserved
        seen: set[str] = set()
        entries: list[tuple[str, str]] = []
        for entry, ref in raw:
            url = _normalize_repo(entry)
            if not url:
                continue
            key = _identity(_parse_repo_url(url), url, Path(url))
            if key in seen:
                self.log.debug("manifest lists %s more than once, keeping the first", url)
                continue
            seen.add(key)
            entries.append((url, ref))
        return entries

    def _parse_yaml(self, text: str) -> list[tuple[str, str]]:
        try:
            doc: Any = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            self.log.error("manifest is not valid yaml: %s", exc)
            return []

        if doc is None:
            # an empty manifest is empty, not malformed
            return []
        if isinstance(doc, dict):
            doc = doc.get("repos") or doc.get("repositories") or []
        if not isinstance(doc, list):
            self.log.error("yaml manifest must be a list, or a mapping with a 'repos' key")
            return []

        entries = []
        for item in doc:
            if isinstance(item, str):
                entries.append((item.strip(), ""))
            elif isinstance(item, dict):
                url = str(item.get("url") or item.get("repo") or "").strip()
                ref = str(item.get("ref") or item.get("branch") or "").strip()
                if url:
                    entries.append((url, ref))
                else:
                    self.log.warning("manifest entry has no url: %s", item)
            else:
                self.log.warning("ignoring manifest entry of unexpected type: %r", item)
        return entries

    # -- cloning --

    def _cache_root(self) -> Path:
        configured = (self.config.cache_dir or "").strip()
        if configured:
            return (Path.cwd() / configured).resolve()
        return self.cache_dir / "checkouts"

    def _dest_for(self, url: str) -> Path:
        ref = _parse_repo_url(url)
        identity = _identity(ref, url, Path(url))
        # readable enough to recognise in the cache, hashed so that two owners
        # with the same repository name cannot land in the same directory
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{ref.owner}-{ref.name}".strip("-")).strip("-")
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
        return self._cache_root() / f"{slug[:60] or 'repo'}-{digest}"

    def _ensure_clone(
        self, ctx: ProcessorContext, url: str, ref: str, dest: Path
    ) -> _Checkout | None:
        if (dest / ".git").exists():
            if self.config.refresh:
                self._refresh(ctx, dest, ref)
            elif ref and not self._is_on_ref(dest, ref):
                # an existing clone is used exactly as it stands, so a manifest
                # whose pin moved since the clone was made needs refresh: true
                # before the tree matches what it now asks for
                self.log.warning(
                    "%s is not on %s and refresh is off, reading the tree as it stands",
                    dest.name,
                    ref,
                )
            return _Checkout(path=dest, url=url, ref=ref, origin="reused")

        if dest.exists() and _has_contents(dest):
            # cloning over this would mean deleting a tree this processor did
            # not create, so leave it alone and say why the repository is missing
            self.log.warning("skipping %s: %s already exists and is not a git checkout", url, dest)
            return None

        # git creates the destination itself, so a directory that is not there
        # yet is one this processor owns and may remove if the clone breaks
        owned = not dest.exists()

        args = ["clone", "--quiet"]
        if self.config.shallow:
            args += ["--depth", str(max(1, int(self.config.clone_depth or 1)))]
        if ref:
            args += ["--branch", ref]
        args += ["--", url, str(dest)]

        self.log.info("cloning %s", url)
        ok, detail = self._run_git_network(ctx, args, cwd=None)
        if ok:
            return _Checkout(path=dest, url=url, ref=ref, origin="cloned")

        self.log.warning("clone failed for %s: %s", url, detail or "git reported no reason")
        if owned and dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return None

    def _is_on_ref(self, dest: Path, ref: str) -> bool:
        # resolved locally, so checking a pin costs no network on a rerun
        code, wanted = self._git(
            ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=dest
        )
        if code != 0 or not wanted:
            return False
        return wanted == self._git(["rev-parse", "HEAD"], cwd=dest)[1]

    def _refresh(self, ctx: ProcessorContext, dest: Path, ref: str) -> None:
        args = ["fetch", "--quiet"]
        if self.config.shallow:
            args += ["--depth", str(max(1, int(self.config.clone_depth or 1)))]
        args.append("origin")
        if ref:
            args.append(ref)

        ok, detail = self._run_git_network(ctx, args, cwd=dest)
        if not ok:
            # a stale checkout still analyses, so a failed fetch is not fatal
            self.log.warning(
                "fetch failed for %s (%s), using the tree already on disk", dest.name, detail
            )
            return

        code, _ = self._git(["reset", "--hard", "-q", "FETCH_HEAD"], cwd=dest, timeout=120)
        if code != 0:
            self.log.warning("could not move %s onto the fetched head", dest.name)

    # -- describing one checkout --

    def _describe(self, ctx: ProcessorContext, checkout: _Checkout) -> Sample:
        path = checkout.path
        url = checkout.url or self._origin_url(path)
        ref = _parse_repo_url(url)
        identity = _identity(ref, url, path)

        full_name = "/".join(p for p in (ref.owner, ref.name) if p) or path.name
        data: dict[str, Any] = {
            "repo_url": url,
            "repo_host": ref.host,
            "repo_owner": ref.owner,
            "repo_name": ref.name or path.name,
            "repo_full_name": full_name,
            "commit_sha": self._repo_git(path, ["rev-parse", "HEAD"]),
            "default_branch": self._default_branch(path),
            "checkout_source": checkout.origin,
        }
        if checkout.ref:
            data["ref"] = checkout.ref
        data.update(self._scan_tree(ctx, path))

        # keyed on what the repository is rather than where it happens to sit,
        # so a rerun - and the same repository reached through a manifest
        # instead of a directory - keeps the same sample
        sample_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return Sample(sample_id=sample_id, source_path=path, filename=full_name, data=data)

    def _origin_url(self, path: Path) -> str:
        return self._repo_git(path, ["config", "--get", "remote.origin.url"])

    def _default_branch(self, path: Path) -> str:
        out = self._repo_git(path, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
        if out:
            return out.split("/", 1)[-1]
        # a shallow clone often has no origin/HEAD, and the branch it checked
        # out is the default branch by construction
        out = self._repo_git(path, ["rev-parse", "--abbrev-ref", "HEAD"])
        return out if out != "HEAD" else ""

    def _scan_tree(self, ctx: ProcessorContext, root: Path) -> dict[str, Any]:
        ext_to_lang = self._language_map()
        excludes = [str(p) for p in (self.config.exclude or []) if p]
        # never walk into .git whatever the config says: it is storage, not source
        if ".git" not in excludes:
            excludes.append(".git")
        max_bytes = max(0, int(self.config.max_file_bytes or 0))

        total_files = 0
        source_files = 0
        total_loc = 0
        languages: dict[str, int] = {}
        manifests: set[str] = set()
        since_check = 0

        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            dirnames[:] = sorted(d for d in dirnames if not _excluded(_join(rel_dir, d), excludes))

            for name in sorted(filenames):
                if _excluded(_join(rel_dir, name), excludes):
                    continue
                total_files += 1
                if name in DEPENDENCY_MANIFESTS:
                    manifests.add(name)

                language = ext_to_lang.get(Path(name).suffix.lower())
                if language is None:
                    continue
                source_files += 1
                languages[language] = languages.get(language, 0) + 1
                total_loc += _count_lines(Path(dirpath) / name, max_bytes)

            since_check += len(filenames)
            if since_check >= _SHUTDOWN_CHECK_FILES:
                since_check = 0
                if self._interrupted(ctx):
                    # the engine discards an interrupted ingest, so stopping
                    # here cannot leave half-counted numbers in the run
                    break

        primary = ""
        if languages:
            # ties broken by name so the same tree always names the same language
            primary = sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        return {
            "total_files": total_files,
            "source_files": source_files,
            "total_loc": total_loc,
            "languages": dict(sorted(languages.items())),
            "primary_language": primary,
            "dependency_manifests": sorted(manifests),
            "has_dependency_manifest": bool(manifests),
        }

    def _language_map(self) -> dict[str, str]:
        configured = self.config.languages
        if isinstance(configured, dict) and configured:
            by_language = {
                str(name): tuple(str(e) for e in exts) for name, exts in configured.items()
            }
        else:
            by_language = dict(DEFAULT_LANGUAGES)
            wanted = [str(n).lower() for n in (configured or [])]
            if wanted:
                unknown = [n for n in wanted if n not in by_language]
                if unknown:
                    self.log.warning(
                        "unknown languages in config, ignoring: %s", ", ".join(unknown)
                    )
                by_language = {n: by_language[n] for n in wanted if n in by_language}

        ext_to_lang: dict[str, str] = {}
        for language, extensions in by_language.items():
            for ext in extensions:
                ext = ext if ext.startswith(".") else f".{ext}"
                ext_to_lang[ext.lower()] = language

        wanted_exts = [str(e) for e in (self.config.extensions or [])]
        if wanted_exts:
            narrowed = {}
            for ext in wanted_exts:
                ext = (ext if ext.startswith(".") else f".{ext}").lower()
                # an extension the built-in map has never heard of is counted
                # under its own name rather than dropped
                narrowed[ext] = ext_to_lang.get(ext, ext.lstrip("."))
            return narrowed
        return ext_to_lang

    # -- running git --

    def _interrupted(self, ctx: ProcessorContext) -> bool:
        return ctx.shutdown_event is not None and ctx.shutdown_event.is_set()

    def _repo_git(self, path: Path, args: list[str]) -> str:
        """read something from a checkout, or nothing when the tree is not one.

        git searches every parent of the directory it is handed, so a plain
        source tree that happens to sit inside somebody's checkout would report
        that checkout's remote and revision as its own. Since the identity a
        sample is keyed on comes from those answers, every such tree in a corpus
        would also collapse onto one sample. A tree with no `.git` of its own is
        therefore not asked.
        """
        if not (path / ".git").exists():
            return ""
        code, out = self._git(args, cwd=path)
        return out if code == 0 else ""

    def _git(self, args: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str]:
        """run a git command that answers immediately, e.g. reading a ref."""
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=_git_env(),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.log.debug("git %s failed: %s", " ".join(args), exc)
            return 1, ""
        return proc.returncode, (proc.stdout or "").strip()

    def _run_git_network(
        self, ctx: ProcessorContext, args: list[str], cwd: Path | None
    ) -> tuple[bool, str]:
        """run a git command that talks to a server, watching for shutdown.

        Cloning is the one part of ingest that can take minutes, so it is polled
        rather than waited on: Ctrl+C stops the fetch instead of being queued
        behind it. Returns whether it worked and the tail of what git said.
        """
        timeout = max(0, int(self.config.clone_timeout or 0))
        # git writes progress to stderr; a file rather than a pipe means a
        # chatty server cannot fill a buffer nobody is draining and deadlock
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errfile:
            try:
                proc = subprocess.Popen(
                    ["git", *args],
                    cwd=str(cwd) if cwd is not None else None,
                    stdout=subprocess.DEVNULL,
                    stderr=errfile,
                    stdin=subprocess.DEVNULL,
                    env=_git_env(),
                )
            except OSError as exc:
                return False, str(exc)

            deadline = time.monotonic() + timeout if timeout else None
            while True:
                try:
                    proc.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if self._interrupted(ctx):
                    _terminate(proc)
                    return False, "interrupted"
                if deadline is not None and time.monotonic() > deadline:
                    _terminate(proc)
                    return False, f"timed out after {timeout}s"

            errfile.seek(0)
            detail = errfile.read()[-500:].strip()

        return proc.returncode == 0, detail


# -- module helpers --


def _git_env() -> dict[str, str]:
    # an unattended run must never stop at a credential prompt: a repository it
    # cannot read should fail the clone and be skipped, not hang the pipeline
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
    return env


def _terminate(proc: subprocess.Popen) -> None:
    proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _looks_like_yaml(manifest: Path, text: str) -> bool:
    if manifest.suffix.lower() in (".yaml", ".yml"):
        return True
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped.startswith("- ") or stripped.startswith("repos:")
    return False


def _parse_lines(text: str) -> list[tuple[str, str]]:
    entries = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # a trailing comment only counts after whitespace, so a url carrying a
        # fragment is left as it was written
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
        if line:
            entries.append((line, ""))
    return entries


def _normalize_repo(entry: str) -> str:
    text = entry.strip()
    if not text:
        return ""
    if "://" in text or _SCP_LIKE.match(text):
        return text
    if Path(text).exists():
        # a local repository is a perfectly good clone source
        return text
    if _SHORTHAND.match(text):
        return f"https://github.com/{text}.git"
    return text


def _parse_repo_url(url: str) -> _RepoRef:
    text = (url or "").strip()
    if not text:
        return _RepoRef()

    scp = _SCP_LIKE.match(text)
    if scp:
        host, path = scp.group("host"), scp.group("path")
    elif "://" in text:
        parsed = urlparse(text)
        host, path = parsed.hostname or "", parsed.path
    else:
        # a local path has a directory name and nothing else to derive
        return _RepoRef(name=Path(text).name.removesuffix(".git"))

    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return _RepoRef(host=host)
    # everything above the repository is the owner, so a gitlab subgroup keeps
    # its full path instead of being cut down to its last segment
    return _RepoRef(host=host, owner="/".join(parts[:-1]), name=parts[-1].removesuffix(".git"))


def _identity(ref: _RepoRef, url: str, path: Path) -> str:
    if ref.owner and ref.name:
        return f"{ref.host}/{ref.owner}/{ref.name}".strip("/").lower()
    if url:
        return url.strip().rstrip("/").removesuffix(".git").lower()
    return path.name.lower()


def _has_contents(directory: Path) -> bool:
    try:
        return any(directory.iterdir())
    except OSError:
        # unreadable is not empty, and is certainly not ours to overwrite
        return True


def _join(rel_dir: str, name: str) -> str:
    return f"{rel_dir}/{name}" if rel_dir else name


def _excluded(rel_path: str, patterns: list[str]) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    for raw in patterns:
        pattern = raw.rstrip("/")
        if fnmatch(name, pattern) or fnmatch(rel_path, pattern):
            return True
        if fnmatch(rel_path, f"*/{pattern}"):
            return True
    return False


def _count_lines(path: Path, max_bytes: int) -> int:
    # non-blank lines: a crude measure, but a stable one that needs no parser
    # per language and is comparable across every repository in the corpus
    try:
        if max_bytes and path.stat().st_size > max_bytes:
            return 0
        data = path.read_bytes()
    except OSError:
        return 0
    return sum(1 for line in data.splitlines() if line.strip())

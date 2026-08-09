from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from deepzero.engine.stage import ProcessorContext, StageSpec
from processors.git_ingest.git_ingest import GitIngest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _make_repo(root: Path, name: str, files: dict[str, str], origin: str = "") -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    for rel, body in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "test"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    if origin:
        _git(["remote", "add", "origin", origin], repo)
    return repo


def _commit(repo: Path, rel: str, body: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "more"], repo)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    _make_repo(
        root,
        "alpha",
        {
            "src/main.py": "import os\n\n\ndef f():\n    return 1\n",
            "src/util.py": "x = 1\n",
            "requirements.txt": "requests\n",
            "node_modules/junk/a.py": "vendored = 1\n",
            "README.md": "hi\n",
        },
        origin="https://github.com/acme/alpha.git",
    )
    _make_repo(
        root,
        "beta",
        {"cmd/main.go": "package main\n\nfunc main() {}\n", "go.mod": "module beta\n"},
        origin="git@github.com:acme/beta.git",
    )
    return root


def _make_tool(config: dict | None = None) -> GitIngest:
    return GitIngest(StageSpec(name="discover", processor="git_ingest", config=config or {}))


class _RecordingProgress:
    """the progress contract as a dashboard sees it: a total, and steps toward it."""

    def __init__(self) -> None:
        self.total: int | None = None
        self.done = 0
        self.over_total = False

    def update(self, amount: int = 0, total: int | None = None, description: str | None = None):
        self.done += amount
        if total is not None:
            self.total = total
        if self.total is not None and self.done > self.total:
            self.over_total = True


def _ctx(
    tmp_path: Path,
    shutdown: threading.Event | None = None,
    progress: _RecordingProgress | None = None,
) -> ProcessorContext:
    ctx = ProcessorContext(
        pipeline_dir=tmp_path, global_config={}, llm=None, shutdown_event=shutdown
    )
    if progress is not None:
        ctx.progress = progress
    return ctx


class TestGitIngestDirectory:
    def test_reads_every_checkout(self, tmp_path, corpus):
        samples = _make_tool().process(_ctx(tmp_path), corpus)
        assert {s.data["repo_name"] for s in samples} == {"alpha", "beta"}
        assert all(s.source_path.is_dir() for s in samples)

    def test_records_repository_identity(self, tmp_path, corpus):
        samples = _make_tool().process(_ctx(tmp_path), corpus)
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        assert alpha.data["repo_host"] == "github.com"
        assert alpha.data["repo_owner"] == "acme"
        assert alpha.data["repo_full_name"] == "acme/alpha"
        assert alpha.data["default_branch"] == "main"
        assert len(alpha.data["commit_sha"]) == 40
        assert alpha.data["checkout_source"] == "directory"

    def test_scp_style_remote_is_parsed(self, tmp_path, corpus):
        samples = _make_tool().process(_ctx(tmp_path), corpus)
        beta = next(s for s in samples if s.data["repo_name"] == "beta")
        assert beta.data["repo_host"] == "github.com"
        assert beta.data["repo_owner"] == "acme"

    def test_counts_source_and_skips_excluded_directories(self, tmp_path, corpus):
        samples = _make_tool().process(_ctx(tmp_path), corpus)
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        # node_modules and .git are excluded, so only 4 files remain
        assert alpha.data["total_files"] == 4
        assert alpha.data["languages"] == {"python": 2}
        assert alpha.data["primary_language"] == "python"
        assert alpha.data["source_files"] == 2
        assert alpha.data["total_loc"] == 4

    def test_records_dependency_manifests(self, tmp_path, corpus):
        samples = _make_tool().process(_ctx(tmp_path), corpus)
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        assert alpha.data["dependency_manifests"] == ["requirements.txt"]
        assert alpha.data["has_dependency_manifest"] is True

    def test_sample_ids_are_stable_across_runs(self, tmp_path, corpus):
        first = _make_tool().process(_ctx(tmp_path), corpus)
        second = _make_tool().process(_ctx(tmp_path), corpus)
        assert {s.sample_id for s in first} == {s.sample_id for s in second}

    def test_a_copy_under_another_name_is_the_same_repository(self, tmp_path, corpus):
        # a resumed run must not re-analyse a repository because the clone
        # landed somewhere else, so the id follows the origin remote and not
        # the directory it happens to sit in
        shutil.copytree(corpus / "alpha", tmp_path / "alpha-again")
        first = _make_tool().process(_ctx(tmp_path), corpus / "alpha")
        second = _make_tool().process(_ctx(tmp_path), tmp_path / "alpha-again")
        assert first[0].sample_id == second[0].sample_id

    def test_two_repositories_sharing_a_directory_name_stay_apart(self, tmp_path):
        # a fork and its upstream are both called "alpha" on disk, and merging
        # them would drop one repository's findings onto the other
        for owner in ("acme", "forker"):
            _make_repo(
                tmp_path / owner,
                "alpha",
                {"a.py": "x = 1\n"},
                origin=f"https://github.com/{owner}/alpha.git",
            )
        upstream = _make_tool().process(_ctx(tmp_path), tmp_path / "acme" / "alpha")
        fork = _make_tool().process(_ctx(tmp_path), tmp_path / "forker" / "alpha")
        assert upstream[0].sample_id != fork[0].sample_id

    def test_a_directory_with_no_git_is_read_as_a_source_drop(self, tmp_path, corpus):
        # an unpacked tarball has code worth auditing but no revision to report
        (corpus / "gamma" / "src").mkdir(parents=True)
        (corpus / "gamma" / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        samples = _make_tool().process(_ctx(tmp_path), corpus)
        gamma = next(s for s in samples if s.data["repo_name"] == "gamma")
        assert gamma.data["commit_sha"] == ""
        assert gamma.data["source_files"] == 1

    def test_source_drops_inside_a_checkout_are_not_that_checkout(self, tmp_path):
        # git searches every parent for a repository, so a corpus unpacked
        # inside somebody's working tree would otherwise report that tree's
        # remote and revision as its own - and since the sample id is derived
        # from them, every drop in the corpus would collapse onto one sample
        outer = _make_repo(
            tmp_path, "outer", {"a.py": "x = 1\n"}, origin="https://github.com/acme/outer.git"
        )
        for name in ("libfoo", "libbar"):
            (outer / "drops" / name).mkdir(parents=True)
            (outer / "drops" / name / "app.py").write_text("x = 1\n", encoding="utf-8")

        samples = _make_tool().process(_ctx(tmp_path), outer / "drops")
        assert {s.data["repo_name"] for s in samples} == {"libfoo", "libbar"}
        assert len({s.sample_id for s in samples}) == 2
        assert all(s.data["commit_sha"] == "" for s in samples)
        assert all(s.data["repo_url"] == "" for s in samples)
        assert all(s.data["default_branch"] == "" for s in samples)

    def test_two_checkouts_of_one_repository_become_one_sample(self, tmp_path, corpus):
        # the engine keys samples by id, so a mirror sitting beside the original
        # has to be collapsed here or one of the two vanishes uncounted
        shutil.copytree(corpus / "alpha", corpus / "alpha-mirror")
        samples = _make_tool().process(_ctx(tmp_path), corpus)
        assert {s.data["repo_name"] for s in samples} == {"alpha", "beta"}
        assert len(samples) == len({s.sample_id for s in samples}) == 2

    def test_hidden_directories_are_not_repositories(self, tmp_path, corpus):
        (corpus / ".cache").mkdir()
        samples = _make_tool().process(_ctx(tmp_path), corpus)
        assert {s.data["repo_name"] for s in samples} == {"alpha", "beta"}

    def test_a_file_that_is_not_utf8_is_still_counted(self, tmp_path):
        # a real corpus has cp1252 sources in it, and a decode error while
        # counting lines would cost the whole repository
        repo = _make_repo(tmp_path / "corpus", "legacy", {"ok.py": "x = 1\n"})
        (repo / "latin.py").write_bytes(b"# caf\xe9\nvalue = 1\n")
        samples = _make_tool().process(_ctx(tmp_path), repo)
        assert samples[0].data["source_files"] == 2
        assert samples[0].data["total_loc"] == 3

    def test_target_that_is_itself_a_checkout(self, tmp_path, corpus):
        samples = _make_tool().process(_ctx(tmp_path), corpus / "alpha")
        assert len(samples) == 1
        assert samples[0].data["repo_full_name"] == "acme/alpha"

    def test_missing_target(self, tmp_path):
        assert _make_tool().process(_ctx(tmp_path), tmp_path / "nope") == []


class TestGitIngestConfig:
    def test_languages_narrows_what_is_counted(self, tmp_path, corpus):
        samples = _make_tool({"languages": ["go"]}).process(_ctx(tmp_path), corpus)
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        assert alpha.data["languages"] == {}
        assert alpha.data["primary_language"] == ""

    def test_a_language_mapping_counts_unknown_extensions(self, tmp_path, corpus):
        samples = _make_tool({"languages": {"docs": [".md"]}}).process(_ctx(tmp_path), corpus)
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        assert alpha.data["primary_language"] == "docs"

    def test_extensions_narrow_to_named_suffixes(self, tmp_path, corpus):
        samples = _make_tool({"extensions": [".md"]}).process(_ctx(tmp_path), corpus)
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        assert alpha.data["languages"] == {"md": 1}

    def test_exclude_globs_replace_the_defaults(self, tmp_path, corpus):
        # the config replaces the list rather than adding to it, so node_modules
        # is walked now that nothing names it and the vendored file counts
        samples = _make_tool({"exclude": ["*.md"]}).process(_ctx(tmp_path), corpus)
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        assert alpha.data["languages"] == {"python": 3}
        # .git holds far more than one file, so a count of exactly four says it
        # was pruned even though the config no longer lists it
        assert alpha.data["total_files"] == 4

    def test_max_file_bytes_stops_lines_being_read(self, tmp_path, corpus):
        samples = _make_tool({"max_file_bytes": 1}).process(_ctx(tmp_path), corpus)
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        assert alpha.data["source_files"] == 2
        assert alpha.data["total_loc"] == 0

    def test_validate_reports_an_unusable_depth(self, tmp_path):
        problems = _make_tool({"clone_depth": 0}).validate(_ctx(tmp_path))
        assert any("clone_depth" in p for p in problems)


class TestGitIngestManifest:
    def _manifest(self, tmp_path: Path, name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_clones_every_listed_repository(self, tmp_path, corpus):
        manifest = self._manifest(
            tmp_path,
            "repos.txt",
            f"# a comment\n{(corpus / 'alpha').as_posix()}  # trailing\n\n"
            f"{(corpus / 'beta').as_posix()}\n",
        )
        cache = tmp_path / "cache"
        samples = _make_tool({"cache_dir": str(cache)}).process(_ctx(tmp_path), manifest)
        assert len(samples) == 2
        assert all(s.data["checkout_source"] == "cloned" for s in samples)
        assert all(cache in s.source_path.parents for s in samples)
        assert all(s.data["commit_sha"] for s in samples)

    def test_a_repository_listed_twice_is_one_sample(self, tmp_path, corpus):
        listed = (corpus / "alpha").as_posix()
        manifest = self._manifest(tmp_path, "repos.txt", f"{listed}\n{listed}\n")
        samples = _make_tool({"cache_dir": str(tmp_path / "cache")}).process(
            _ctx(tmp_path), manifest
        )
        assert len(samples) == 1

    def test_a_failed_clone_does_not_end_the_run(self, tmp_path, corpus):
        manifest = self._manifest(
            tmp_path,
            "repos.txt",
            f"{(corpus / 'alpha').as_posix()}\n{(tmp_path / 'nothing-here').as_posix()}\n",
        )
        processor = _make_tool({"cache_dir": str(tmp_path / "cache")})
        samples = processor.process(_ctx(tmp_path), manifest)
        assert len(samples) == 1
        # the partial clone it created is cleaned up, nothing is left behind
        assert not processor._dest_for((tmp_path / "nothing-here").as_posix()).exists()

    def test_a_rerun_reuses_the_clone_as_it_stands(self, tmp_path, corpus):
        manifest = self._manifest(tmp_path, "repos.txt", f"{(corpus / 'alpha').as_posix()}\n")
        cache = str(tmp_path / "cache")
        first = _make_tool({"cache_dir": cache}).process(_ctx(tmp_path), manifest)
        _commit(corpus / "alpha", "src/extra.py", "y = 2\n")
        second = _make_tool({"cache_dir": cache}).process(_ctx(tmp_path), manifest)
        assert second[0].data["checkout_source"] == "reused"
        assert second[0].sample_id == first[0].sample_id
        # refresh is off by default, and the revision standing still is what
        # says the rerun went nowhere near the remote
        assert second[0].data["commit_sha"] == first[0].data["commit_sha"]

    def test_refresh_moves_a_reused_clone_onto_the_new_commit(self, tmp_path, corpus):
        manifest = self._manifest(tmp_path, "repos.txt", f"{(corpus / 'alpha').as_posix()}\n")
        cache = str(tmp_path / "cache")
        first = _make_tool({"cache_dir": cache}).process(_ctx(tmp_path), manifest)
        _commit(corpus / "alpha", "src/extra.py", "y = 2\n")
        second = _make_tool({"cache_dir": cache, "refresh": True}).process(_ctx(tmp_path), manifest)
        assert second[0].data["commit_sha"] != first[0].data["commit_sha"]
        # the tree moved with the revision, not just the ref
        assert second[0].data["source_files"] == first[0].data["source_files"] + 1

    def test_a_path_with_spaces_is_cloned(self, tmp_path):
        repo = _make_repo(tmp_path / "elsewhere", "my repo", {"a.py": "x = 1\n"})
        manifest = self._manifest(tmp_path, "repos.txt", f"{repo.as_posix()}\n")
        samples = _make_tool({"cache_dir": str(tmp_path / "cache")}).process(
            _ctx(tmp_path), manifest
        )
        assert len(samples) == 1
        assert samples[0].data["checkout_source"] == "cloned"
        assert samples[0].data["source_files"] == 1

    def test_a_tree_it_did_not_create_is_never_removed(self, tmp_path, corpus):
        manifest = self._manifest(tmp_path, "repos.txt", f"{(corpus / 'alpha').as_posix()}\n")
        processor = _make_tool({"cache_dir": str(tmp_path / "cache")})
        dest = processor._dest_for((corpus / "alpha").as_posix())
        dest.mkdir(parents=True)
        (dest / "precious.txt").write_text("keep me", encoding="utf-8")

        assert processor.process(_ctx(tmp_path), manifest) == []
        assert (dest / "precious.txt").read_text(encoding="utf-8") == "keep me"

    def test_a_pin_the_reused_clone_is_not_on_is_reported(self, tmp_path, corpus, caplog):
        # the clone is reused untouched, so a manifest whose pin moved since it
        # was made would otherwise record a ref the tree is not actually on
        cache = str(tmp_path / "cache")
        listed = (corpus / "alpha").as_posix()
        first = _make_tool({"cache_dir": cache}).process(
            _ctx(tmp_path), self._manifest(tmp_path, "repos.txt", f"{listed}\n")
        )
        pinned = self._manifest(tmp_path, "repos.yaml", f"repos:\n  - url: {listed}\n    ref: v2\n")
        with caplog.at_level("WARNING"):
            second = _make_tool({"cache_dir": cache}).process(_ctx(tmp_path), pinned)

        assert second[0].data["commit_sha"] == first[0].data["commit_sha"]
        assert any("v2" in record.getMessage() for record in caplog.records)

    def test_progress_never_counts_past_its_own_total(self, tmp_path, corpus):
        # cloning and reading are two passes over the same repositories, and a
        # second total that restarted below the count already reported would
        # leave the dashboard showing a finished bar with work still to do
        manifest = self._manifest(
            tmp_path,
            "repos.txt",
            f"{(corpus / 'alpha').as_posix()}\n{(corpus / 'beta').as_posix()}\n",
        )
        progress = _RecordingProgress()
        _make_tool({"cache_dir": str(tmp_path / "cache")}).process(
            _ctx(tmp_path, progress=progress), manifest
        )
        assert not progress.over_total
        assert progress.done == progress.total == 4

    def test_yaml_mapping_with_a_repos_key(self, tmp_path, corpus):
        manifest = self._manifest(
            tmp_path,
            "repos.yaml",
            f"repos:\n  - url: {(corpus / 'alpha').as_posix()}\n    ref: main\n"
            f"  - {(corpus / 'beta').as_posix()}\n",
        )
        samples = _make_tool({"cache_dir": str(tmp_path / "cache")}).process(
            _ctx(tmp_path), manifest
        )
        assert len(samples) == 2
        alpha = next(s for s in samples if s.data["repo_name"] == "alpha")
        beta = next(s for s in samples if s.data["repo_name"] == "beta")
        assert alpha.data["ref"] == "main"
        # nothing pinned beta, so no revision is claimed for it
        assert "ref" not in beta.data

    def test_yaml_list_without_a_key(self, tmp_path, corpus):
        manifest = self._manifest(
            tmp_path,
            "repos.list",
            f"- {(corpus / 'alpha').as_posix()}\n- {(corpus / 'beta').as_posix()}\n",
        )
        samples = _make_tool({"cache_dir": str(tmp_path / "cache")}).process(
            _ctx(tmp_path), manifest
        )
        assert len(samples) == 2

    def test_shorthand_expands_to_github(self, tmp_path):
        processor = _make_tool()
        entries = processor._read_manifest(
            self._manifest(tmp_path, "repos.txt", "psf/requests\n"),
        )
        assert entries == [("https://github.com/psf/requests.git", "")]

    def test_shutdown_stops_before_cloning(self, tmp_path, corpus):
        listed = (corpus / "alpha").as_posix()
        manifest = self._manifest(tmp_path, "repos.txt", f"{listed}\n")
        event = threading.Event()
        event.set()
        processor = _make_tool({"cache_dir": str(tmp_path / "cache")})
        assert processor.process(_ctx(tmp_path, shutdown=event), manifest) == []
        # returning nothing is not enough: a Ctrl+C has to be seen before the
        # fetch starts, not after minutes of cloning nobody is waiting for
        assert not processor._dest_for(listed).exists()

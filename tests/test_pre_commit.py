import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[1] / ".pre-commit-config.yaml"
MANIFEST = """\
[project]
name = "lock-check-fixture"
version = "1.0.0"
requires-python = ">=3.11"
"""

pytestmark = pytest.mark.skipif(
    not shutil.which("git") or not shutil.which("uv"),
    reason="Git and uv are required to exercise the pre-commit hook",
)


def run(repo: Path, *command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=repo, check=check, capture_output=True, text=True, timeout=30
    )


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("PRE_COMMIT_HOME", str(tmp_path / "pre-commit-cache"))
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.setenv("UV_OFFLINE", "true")
    monkeypatch.setenv("UV_PYTHON", sys.executable)
    monkeypatch.delenv("UV_PROJECT", raising=False)
    monkeypatch.delenv("UV_WORKING_DIR", raising=False)

    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "git", "init", "--quiet", "--template=")
    run(repo, "git", "config", "user.name", "Test Author")
    run(repo, "git", "config", "user.email", "test@example.test")
    (repo / "pyproject.toml").write_text(MANIFEST, encoding="utf-8")
    (repo / "README.md").write_text("# Test project\n", encoding="utf-8")
    run(repo, "uv", "lock")
    shutil.copyfile(CONFIG, repo / CONFIG.name)
    run(repo, "git", "add", "pyproject.toml", "uv.lock", "README.md", CONFIG.name)
    run(repo, "git", "commit", "-m", "Initial state")
    return repo


def test_lock_update_must_be_staged_with_version_bump(repository: Path) -> None:
    manifest = repository / "pyproject.toml"
    manifest.write_text(MANIFEST.replace("1.0.0", "1.0.1"), encoding="utf-8")
    run(repository, "git", "add", manifest.name)
    run(repository, "uv", "lock")
    lockfile = repository / "uv.lock"
    unstaged_lock = lockfile.read_bytes()

    result = run(repository, sys.executable, "-m", "pre_commit", "run", check=False)

    assert result.returncode == 1
    assert "Run uv lock" in result.stdout
    assert lockfile.read_bytes() == unstaged_lock

    run(repository, "git", "add", lockfile.name)
    result = run(repository, sys.executable, "-m", "pre_commit", "run", check=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert lockfile.read_bytes() == unstaged_lock


@pytest.mark.parametrize("inherit_outdated_lock", [False, True])
def test_documentation_commit_checks_inherited_lock(
    repository: Path, *, inherit_outdated_lock: bool
) -> None:
    manifest = repository / "pyproject.toml"
    bumped_manifest = MANIFEST.replace("1.0.0", "1.0.1")
    manifest.write_text(bumped_manifest, encoding="utf-8")
    if inherit_outdated_lock:
        run(repository, "git", "commit", "-am", "Inherit an outdated lock")
    readme = repository / "README.md"
    readme.write_text("# Updated documentation\n", encoding="utf-8")
    run(repository, "git", "add", readme.name)

    result = run(repository, sys.executable, "-m", "pre_commit", "run", check=False)

    assert result.returncode == int(inherit_outdated_lock), result.stdout + result.stderr
    assert manifest.read_text(encoding="utf-8") == bumped_manifest


def test_lockfile_must_be_tracked(repository: Path) -> None:
    run(repository, "git", "rm", "--cached", "uv.lock")

    result = run(repository, sys.executable, "-m", "pre_commit", "run", check=False)

    assert result.returncode == 1
    assert "Run uv lock" in result.stdout
    assert (repository / "uv.lock").is_file()


def test_metadata_change_can_keep_valid_lock(repository: Path) -> None:
    manifest = repository / "pyproject.toml"
    manifest.write_text(MANIFEST + 'description = "Updated description"\n', encoding="utf-8")
    run(repository, "git", "add", manifest.name)

    result = run(repository, sys.executable, "-m", "pre_commit", "run", check=False)

    assert result.returncode == 0, result.stdout + result.stderr


def test_automatic_merge_cannot_commit_an_outdated_lock(repository: Path) -> None:
    run(repository, "git", "switch", "-c", "outdated-lock")
    manifest = repository / "pyproject.toml"
    manifest.write_text(MANIFEST.replace("1.0.0", "1.0.1"), encoding="utf-8")
    run(repository, "git", "commit", "-am", "Leave the lock outdated on another branch")
    run(repository, "git", "switch", "-")
    run(repository, sys.executable, "-m", "pre_commit", "install")

    result = run(repository, "git", "merge", "--no-ff", "--no-edit", "outdated-lock", check=False)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Run uv lock" in result.stdout + result.stderr


def test_uv_project_overrides_cannot_validate_a_different_lock(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_project = repository.parent / "other-project"
    other_project.mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(repository / name, other_project / name)
    manifest = repository / "pyproject.toml"
    manifest.write_text(MANIFEST.replace("1.0.0", "1.0.1"), encoding="utf-8")
    run(repository, "git", "add", manifest.name)
    monkeypatch.setenv("UV_PROJECT", str(other_project))
    monkeypatch.setenv("UV_WORKING_DIR", str(other_project))

    result = run(repository, sys.executable, "-m", "pre_commit", "run", check=False)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Run uv lock" in result.stdout

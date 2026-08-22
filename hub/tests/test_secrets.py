"""Credentials and business data must not reach the repository.

Eleven per-connector ingest keys were pushed to GitHub before
`hub/memory/sources.json` was ignored. They were dead by the time anyone
looked, but only because the connectors owning them had been deleted — nothing
in the project stopped the next one. These tests are that something.
"""
import importlib.util
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUARD = ROOT / "hub" / "scripts" / "check_secrets.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_secrets", GUARD)
    assert spec and spec.loader, f"cannot load {GUARD}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_repository_carries_no_credentials():
    """The guard, run for real over every tracked file."""
    r = subprocess.run([sys.executable, str(GUARD)], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("label,sample", [
    ("ingest key", "cx_" + "A" * 30),
    ("github pat", "ghp_" + "A" * 36),
    ("anthropic", "sk-ant-" + "A" * 24),
    ("telegram token", "1234567890:AA" + "A" * 33),
])
def test_each_credential_shape_is_caught(guard, label, sample):
    """A guard that matches nothing passes every commit and protects nothing."""
    assert guard.SECRET_RE.search(sample), label


@pytest.mark.parametrize("benign", [
    "cx_short", "sk-ant", "connector_id = 12345",
    "https://pos.example.com/api/v1/sales?date=today",
])
def test_ordinary_code_is_not_flagged(guard, benign):
    """False positives get a guard switched off, which is worse than no guard."""
    assert not guard.SECRET_RE.search(benign)


@pytest.mark.parametrize("path", [
    "hub/.env", "hub/memory/sources.json", "hub/memory/hub_store.json",
])
def test_runtime_state_is_untracked_but_still_on_disk(path):
    """Untracked, not deleted: the hub reads these at runtime."""
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", path],
                             cwd=ROOT, capture_output=True)
    assert tracked.returncode != 0, f"{path} is tracked"
    assert (ROOT / path).exists(), f"{path} vanished from disk"


def test_the_placeholder_exemption_is_not_a_back_door(guard):
    """Files that name the shapes are exempt only for obvious fakes. A real key
    pasted into the checker or its tests must still stop the commit.

    The high-entropy samples are assembled here rather than written as literals,
    so this file never contains a credential-shaped string of its own — a test
    for a leak guard must not be the leak.
    """
    fake = "cx_" + "7mQr2VtKp9LsXd4Ye1Nb" + "6Uh3Wg8Zc5Aj"
    pat = "ghp_" + "3Kd9Xm2Qw7Rt5Yv8Bn1P" + "l4Gs6Hz0Jf2Ce"
    assert not guard.is_placeholder(fake), "a real-looking ingest key slipped through"
    assert not guard.is_placeholder(pat), "a real-looking PAT slipped through"
    for obvious in ("cx_" + "A" * 30, "ghp_" + "A" * 36, "1234567890:AA" + "A" * 33):
        assert guard.is_placeholder(obvious), obvious


def test_new_business_documents_cannot_be_added():
    """Routine reports and uploads are the CEO's data, not source."""
    ignored = subprocess.run(
        ["git", "check-ignore", "hub/docs_store/FlowerVending/probe.md"],
        cwd=ROOT, capture_output=True)
    assert ignored.returncode == 0, "hub/docs_store/ is not ignored"

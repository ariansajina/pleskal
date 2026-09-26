"""Tests for scripts/download_translation_model.py.

The script runs at Docker build time, outside Django, so it's loaded from its
path rather than imported as a package.
"""

import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "download_translation_model.py"


@pytest.fixture
def downloader():
    spec = importlib.util.spec_from_file_location("download_model", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _package(prefix: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{prefix}model/model.bin", b"weights")
        zf.writestr(f"{prefix}model/config.json", b"{}")
        zf.writestr(f"{prefix}bpe.model", b"#version: 0.2\n")
        zf.writestr(f"{prefix}metadata.json", b"{}")
        zf.writestr(f"{prefix}stanza/da/tokenize/ddt.pt", b"unused")
        zf.writestr(f"{prefix}README.md", b"")
    return buf.getvalue()


def test_extracts_model_and_bpe_only(downloader, tmp_path):
    data = _package(downloader.PACKAGE_DIR)
    dest = tmp_path / "models" / "da_en"
    with (
        patch.object(downloader, "MODEL_SHA256", hashlib.sha256(data).hexdigest()),
        patch.object(
            downloader.urllib.request, "urlopen", return_value=io.BytesIO(data)
        ) as urlopen,
    ):
        downloader.download(dest)

    request = urlopen.call_args.args[0]
    assert request.get_header("User-agent")
    assert (dest / "model" / "model.bin").read_bytes() == b"weights"
    assert (dest / "bpe.model").exists()
    assert (dest / "metadata.json").exists()
    assert not (dest / "stanza").exists()
    assert not (dest / "README.md").exists()


def test_replaces_existing_model(downloader, tmp_path):
    data = _package(downloader.PACKAGE_DIR)
    dest = tmp_path / "da_en"
    (dest / "stale").mkdir(parents=True)
    with (
        patch.object(downloader, "MODEL_SHA256", hashlib.sha256(data).hexdigest()),
        patch.object(
            downloader.urllib.request, "urlopen", return_value=io.BytesIO(data)
        ),
    ):
        downloader.download(dest)
    assert not (dest / "stale").exists()
    assert (dest / "model" / "model.bin").exists()


def test_checksum_mismatch_aborts(downloader, tmp_path):
    data = _package(downloader.PACKAGE_DIR)
    dest = tmp_path / "da_en"
    with (
        patch.object(
            downloader.urllib.request, "urlopen", return_value=io.BytesIO(data)
        ),
        pytest.raises(SystemExit, match="Checksum mismatch"),
    ):
        downloader.download(dest)
    assert not dest.exists()

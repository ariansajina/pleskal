#!/usr/bin/env python
"""
Download the Danish → English translation model used by events/translation.py.

The model is the Argos Translate da→en package: a CTranslate2 model plus
subword-nmt BPE codes. Only those two parts are extracted (the package also
ships a stanza sentence splitter, which pleskal doesn't use). The download is
checked against a pinned SHA-256, so a changed upstream file fails loudly
rather than silently swapping the model.

Run at Docker build time (see Dockerfile) and once locally for development:

  python scripts/download_translation_model.py [DEST]

DEST defaults to models/translate-da_en, matching the TRANSLATION_MODEL_DIR
default in config/settings.py. Standard library only, so it runs before (or
without) the project's dependencies.
"""

import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

MODEL_URL = "https://argos-net.com/v1/translate-da_en-1_9.argosmodel"
MODEL_SHA256 = "cf0e4ddc78a6cc4c9093fcd8b5f22285fc5d0a8fe8650940cdc913da6295c585"
PACKAGE_DIR = "translate-da_en-1_9/"
# Package members to extract, relative to PACKAGE_DIR.
KEEP = ("model/", "bpe.model", "metadata.json")
DEFAULT_DEST = Path(__file__).resolve().parent.parent / "models" / "translate-da_en"


def download(dest: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "model.zip"
        print(f"Downloading {MODEL_URL} ...")
        # The host rejects urllib's default User-Agent.
        request = urllib.request.Request(  # noqa: S310
            MODEL_URL, headers={"User-Agent": "pleskal-model-download/1.0"}
        )
        with (
            urllib.request.urlopen(request, timeout=120) as resp,  # noqa: S310
            open(archive, "wb") as out,
        ):
            shutil.copyfileobj(resp, out)

        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            sys.exit(f"Checksum mismatch: expected {MODEL_SHA256}, got {digest}")

        staging = Path(tmp) / "out"
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                relative = name.removeprefix(PACKAGE_DIR)
                if name.endswith("/") or not relative.startswith(KEEP):
                    continue
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))

        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(staging, dest)
    print(f"Translation model installed at {dest}")


if __name__ == "__main__":
    download(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DEST)

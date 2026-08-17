"""Build release artifacts, a small CycloneDX SBOM, and SHA-256 checksums."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def web_archive(tag: str) -> Path:
    source = ROOT / "web" / "dist"
    if not source.is_dir():
        raise SystemExit("web/dist is missing; run npm ci && npm run build first")
    destination = RELEASE / f"open3d-web-{tag}.tar.gz"
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=Path("web") / path.relative_to(source))
    return destination


def sbom() -> Path:
    components = [{"type": "library", "name": "open3d-artist", "version": "0.1.0a1", "purl": "pkg:pypi/open3d-artist@0.1.0a1"}]
    lock = ROOT / "web" / "package-lock.json"
    if lock.is_file():
        data = json.loads(lock.read_text(encoding="utf-8"))
        for package_path, value in sorted(data.get("packages", {}).items()):
            if not package_path or not value.get("version"):
                continue
            name = package_path.rsplit("/node_modules/", 1)[-1].removeprefix("node_modules/")
            components.append({"type": "library", "name": name, "version": value["version"], "scope": "required" if package_path in {"node_modules/three", "node_modules/@phosphor-icons/web"} else "optional"})
    destination = RELEASE / "open3d-sbom.json"
    destination.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "metadata": {"component": components[0]}, "components": components}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def main() -> int:
    tag = os.environ.get("RELEASE_TAG", "dev")
    RELEASE.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(RELEASE)], cwd=ROOT, check=True)
    web_archive(tag)
    sbom()
    checksum_path = RELEASE / "SHA256SUMS"
    files = sorted(path for path in RELEASE.iterdir() if path.is_file() and path.name != checksum_path.name)
    checksum_path.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in files), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

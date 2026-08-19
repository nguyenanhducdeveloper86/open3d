"""Build clean release artifacts, app sources, SBOM, and SHA-256 checksums."""

from __future__ import annotations

import hashlib
import gzip
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"
APP_SOURCES = (
    (ROOT / "open3d_artist", "*.py"),
    (ROOT / "examples" / "watering-can", "asset.yaml"),
    (ROOT / "examples" / "production-qualification", "*"),
    (ROOT / "tools" / "production_fixture", "*.py"),
    (ROOT / "workers" / "unity", "*"),
    (ROOT / "web" / "dist", "*"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive(destination: Path, files: list[tuple[Path, Path]], epoch: int, generated: dict[Path, bytes] | None = None) -> Path:
    with destination.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed, tarfile.open(fileobj=compressed, mode="w") as output:
        for path, name in sorted(files, key=lambda item: item[1].as_posix()):
            info = output.gettarinfo(str(path), arcname=name.as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = epoch
            info.mode = 0o644
            with path.open("rb") as handle:
                output.addfile(info, handle)
        for name, data in sorted((generated or {}).items(), key=lambda item: item[0].as_posix()):
            info = tarfile.TarInfo(name.as_posix())
            info.size, info.mode, info.mtime = len(data), 0o644, epoch
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            output.addfile(info, BytesIO(data))
    return destination


def web_archive(tag: str, epoch: int) -> Path:
    source = ROOT / "web" / "dist"
    files = [(path, Path("web") / path.relative_to(source)) for path in source.rglob("*") if path.is_file()]
    if not files:
        raise SystemExit("web/dist is missing; run npm ci && npm run build first")
    return archive(RELEASE / f"open3d-web-{tag}.tar.gz", files, epoch)


def app_archive(tag: str, version: str, epoch: int) -> Path:
    prefix = Path(f"open3d-artist-app-{tag}")
    files = []
    for source, pattern in APP_SOURCES:
        files.extend((path, prefix / path.relative_to(ROOT)) for path in source.rglob(pattern) if path.is_file() and "__pycache__" not in path.parts)
    files.extend((ROOT / name, prefix / name) for name in ("README.md", "LICENSE", "pyproject.toml"))
    metadata = json.dumps({
        "artifact": "open3d-artist-app-source",
        "approval": "LOCAL_ONLY_NOT_APPROVED",
        "release_tag": tag,
        "version": version,
        "wheel_scope": "Python core only; use this bundle for production recipes, tools, Unity worker, and built viewer.",
    }, indent=2, sort_keys=True).encode() + b"\n"
    return archive(RELEASE / f"open3d-artist-app-{tag}.tar.gz", files, epoch, {prefix / "RELEASE-METADATA.json": metadata})


def normalize_sdist(path: Path, epoch: int) -> None:
    with tarfile.open(path, "r:gz") as source:
        files = {Path(member.name): source.extractfile(member).read() for member in source.getmembers() if member.isfile()}
    temporary = path.with_suffix(".tmp")
    archive(temporary, [], epoch, files)
    temporary.replace(path)


def sbom(version: str) -> Path:
    components = [{"type": "library", "name": "open3d-artist", "version": version, "purl": f"pkg:pypi/open3d-artist@{version}"}]
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
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if tag != f"v{version}":
        raise SystemExit(f"RELEASE_TAG must be v{version}, got {tag!r}")
    epoch = int(subprocess.check_output(["git", "log", "-1", "--format=%ct"], cwd=ROOT, text=True).strip())
    shutil.rmtree(RELEASE, ignore_errors=True)
    RELEASE.mkdir()
    env = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch)}
    subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(RELEASE)], cwd=ROOT, env=env, check=True)
    normalize_sdist(RELEASE / f"open3d_artist-{version}.tar.gz", epoch)
    web_archive(tag, epoch)
    app_archive(tag, version, epoch)
    sbom(version)
    checksum_path = RELEASE / "SHA256SUMS"
    files = sorted(path for path in RELEASE.iterdir() if path.is_file() and path.name != checksum_path.name)
    checksum_path.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in files), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

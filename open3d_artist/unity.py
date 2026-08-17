"""Batch Unity validator adapter. Unity and import packages remain user-supplied."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .project import ProjectError
from .workers import ProcessResult, _inside, run_limited


class UnityValidator:
    def __init__(self, unity_project: str | Path, *, unity: str = "unity-editor", validator_script: str | Path | None = None):
        self.project = Path(unity_project).resolve()
        self.unity = unity
        self.validator_script = Path(validator_script or Path(__file__).parents[1] / "workers/unity/Editor/Open3DValidator.cs").resolve()

    def command(self, input_asset: str | Path, output_report: str | Path) -> list[str]:
        if not (self.project / "Assets").is_dir():
            raise ProjectError(f"Unity project must contain Assets: {self.project}")
        asset = _inside(self.project, input_asset, label="Unity input asset", must_exist=True)
        report = _inside(self.project, output_report, label="Unity report")
        try:
            asset_arg = asset.relative_to(self.project).as_posix()
        except ValueError as exc:
            raise ProjectError("Unity input asset must be inside the Unity project") from exc
        return [
            self.unity,
            "-batchmode", "-nographics", "-quit",
            "-projectPath", str(self.project),
            "-executeMethod", "Open3DValidator.Run",
            "-open3dInput", asset_arg,
            "-open3dOutput", str(report),
        ]

    def run(self, input_asset: str | Path, output_report: str | Path, *, timeout: float = 600) -> dict[str, Any]:
        if shutil.which(self.unity) is None and not Path(self.unity).is_file():
            return {"status": "UNAVAILABLE", "reason": f"Unity executable not found: {self.unity}"}
        command = self.command(input_asset, output_report)
        result = run_limited(command, cwd=self.project, timeout=timeout)
        report_path = _inside(self.project, output_report, label="Unity report")
        report: dict[str, Any] = {}
        if report_path.is_file():
            try:
                import json

                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                report = {"status": "FAIL", "error": "Unity report is invalid JSON"}
        return {"status": "PASS" if result.status == "PASS" and result.returncode == 0 and report.get("status") == "PASS" else "FAIL", "process": {"status": result.status, "returncode": result.returncode, "duration_ms": result.duration_ms, "output": result.output}, "report": report}

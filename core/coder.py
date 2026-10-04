from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


MAX_REPAIR_ROUNDS = 3
MAX_FILE_BYTES = 1_000_000
PROTECTED_NAMES = {".git", ".venv", "venv", "__pycache__", ".env", ".khula_backups", ".ssh", ".aws"}


def _npm_command(*arguments: str) -> list[str]:
    if os.name == "nt":
        return ["cmd.exe", "/d", "/c", "npm " + " ".join(arguments)]
    return ["npm", *arguments]


def resolve_project_path(project_root: Path, relative_path: str) -> Path:
    root = project_root.resolve()
    raw = Path(relative_path)
    if raw.is_absolute() or not relative_path.strip() or any(part in {"..", ""} for part in raw.parts):
        raise ValueError(f"Unsafe project-relative path: {relative_path!r}")
    if any(part.lower() in PROTECTED_NAMES for part in raw.parts):
        raise ValueError(f"Edits to protected paths are not allowed: {relative_path!r}")
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes the selected project: {relative_path!r}") from exc
    return target


def parse_file_plan(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    plan = json.loads(text.strip())
    if not isinstance(plan, dict) or not isinstance(plan.get("files"), list):
        raise ValueError("Gemini response must contain a JSON object with a files list.")
    if len(plan["files"]) > 40:
        raise ValueError("Refusing a plan containing more than 40 files.")
    for item in plan["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
            raise ValueError("Each planned file needs string path and content fields.")
        if len(item["content"].encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"Generated file is too large: {item['path']}")
    return plan


def detect_checks(project_root: Path) -> list[list[str]]:
    root = project_root.resolve()
    solutions = sorted(root.glob("*.sln")) + sorted(root.glob("*.slnx"))
    projects = sorted(root.glob("*.csproj"))
    if solutions or projects:
        target = solutions[0] if solutions else projects[0]
        return [["dotnet", "build", str(target), "--nologo"]]

    package_json = root / "package.json"
    if package_json.is_file():
        try:
            scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, json.JSONDecodeError):
            scripts = {}
        if "build" in scripts:
            return [_npm_command("run", "build")]
        if "test" in scripts:
            return [_npm_command("test")]
        return []

    pyproject = root / "pyproject.toml"
    if pyproject.is_file() or any(root.glob("*.py")) or (root / "tests").is_dir():
        checks = [[sys.executable, "-m", "compileall", "-q", "."]]
        if (root / "tests").is_dir() and shutil.which("pytest"):
            checks.append([sys.executable, "-m", "pytest", "-q"])
        return checks
    return []


class AutonomousCoder:
    def __init__(self, brain) -> None:
        self.brain = brain

    def run(self, task: str, project_root: Path) -> str:
        root = project_root.resolve()
        if not root.is_dir():
            raise ValueError("Select an existing project folder before starting a coding task.")

        summary = ""
        diagnostics = ""
        for attempt in range(MAX_REPAIR_ROUNDS + 1):
            raw_plan = self.brain.generate_file_plan(task, root, diagnostics)
            plan = parse_file_plan(raw_plan)
            self._apply_plan(root, plan)
            summary = str(plan.get("summary", "Code updated."))
            checks = detect_checks(root)
            if not checks:
                raise ValueError("No supported build/test target found. Add a .sln/.csproj, package.json, Python files, or tests folder.")
            diagnostics = self._run_checks(root, checks)
            if not diagnostics:
                return f"{summary + chr(10) if summary else ''}Build/tests passed on attempt {attempt + 1}."
            if attempt == MAX_REPAIR_ROUNDS:
                break
        return f"Could not get a clean build after {MAX_REPAIR_ROUNDS} repair rounds.\n\n{diagnostics[-12000:]}"

    def _apply_plan(self, root: Path, plan: dict[str, Any]) -> None:
        files = plan["files"]
        if not files:
            raise ValueError("Gemini returned no files to change.")
        backup_root = root / ".khula_backups" / str(int(time.time()))
        for item in files:
            destination = resolve_project_path(root, item["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_file():
                relative = destination.relative_to(root)
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
            temporary = destination.with_name(destination.name + ".khula-tmp")
            temporary.write_text(item["content"], encoding="utf-8", newline="")
            os.replace(temporary, destination)

    def _run_checks(self, root: Path, checks: list[list[str]]) -> str:
        outputs: list[str] = []
        for command in checks:
            if not shutil.which(command[0]):
                return f"Required build tool not found: {command[0]}"
            try:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    shell=False,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return f"Timed out after 120 seconds: {' '.join(command)}\n{exc.stdout or ''}\n{exc.stderr or ''}"
            output = (completed.stdout + "\n" + completed.stderr).strip()
            outputs.append(f"$ {' '.join(command)}\n{output}")
            if completed.returncode:
                return "\n\n".join(outputs)[-16000:]
        return ""

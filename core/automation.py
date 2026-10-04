from __future__ import annotations

import os
import subprocess
from pathlib import Path


APPLICATIONS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "vscode": ["code"],
}
SHORTCUTS = {
    "ctrl+c": ("ctrl", "c"),
    "ctrl+v": ("ctrl", "v"),
    "ctrl+x": ("ctrl", "x"),
    "ctrl+z": ("ctrl", "z"),
    "ctrl+y": ("ctrl", "y"),
    "ctrl+s": ("ctrl", "s"),
    "ctrl+f": ("ctrl", "f"),
    "alt+tab": ("alt", "tab"),
}


class DesktopAutomation:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.resolve()
        self.screenshot_dir = self.data_root / "data" / "screenshots"

    def open_application(self, name: str) -> str:
        key = name.strip().lower()
        command = APPLICATIONS.get(key)
        if command is None:
            return f"Application not allowlisted: {key}. Available: {', '.join(APPLICATIONS)}"
        try:
            subprocess.Popen(command, shell=False, close_fds=True)
        except OSError as exc:
            return f"Could not start {key}: {exc}"
        return f"Started {key}."

    def list_processes(self, limit: int = 40) -> str:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("Install psutil to list running processes.") from exc
        rows = []
        for process in psutil.process_iter(["pid", "name"]):
            try:
                rows.append(f"{process.info['pid']:>7}  {process.info['name'] or 'unknown'}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        rows.sort(key=str.casefold)
        return "Running processes (partial list):\n" + "\n".join(rows[:limit])

    def list_files(self, project_root: Path, limit: int = 100) -> str:
        root = project_root.resolve()
        ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", ".khula_backups"}
        files = []
        for current, directories, names in os.walk(root):
            directories[:] = [name for name in directories if name.lower() not in ignored]
            for name in names:
                if name.lower() == ".env" or name.lower().startswith(".env."):
                    continue
                path = Path(current, name)
                try:
                    path.resolve().relative_to(root)
                except ValueError:
                    continue
                files.append(path.relative_to(root).as_posix())
        files.sort(key=str.casefold)
        if not files:
            return "No project files found."
        suffix = "\n... (list truncated)" if len(files) > limit else ""
        return "Project files:\n" + "\n".join(files[:limit]) + suffix

    def open_project_file(self, project_root: Path, relative_path: str) -> str:
        root = project_root.resolve()
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            return "Only relative paths inside the selected project can be opened."
        target = (root / candidate).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return "That path resolves outside the selected project."
        if not target.is_file():
            return "Project file not found. Use /files to list project files."
        try:
            if os.name == "nt":
                os.startfile(str(target))
            else:
                subprocess.Popen(["xdg-open", str(target)], shell=False)
        except OSError as exc:
            return f"Could not open file: {exc}"
        return f"Opened {target.relative_to(root).as_posix()}."

    def send_shortcut(self, shortcut: str) -> str:
        keys = SHORTCUTS.get(shortcut.strip().lower())
        if keys is None:
            return f"Shortcut not allowlisted. Available: {', '.join(SHORTCUTS)}"
        try:
            import pyautogui
        except ImportError as exc:
            raise RuntimeError("Install pyautogui to send keyboard shortcuts.") from exc
        pyautogui.hotkey(*keys)
        return f"Sent {shortcut.strip().lower()}."

    def capture_screen(self) -> Path:
        try:
            import pyautogui
        except ImportError as exc:
            raise RuntimeError("Install pyautogui and Pillow to capture the screen.") from exc
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        target = self.screenshot_dir / "latest.png"
        image = pyautogui.screenshot()
        image.save(target)
        return target

    def open_project_folder(self, path: Path) -> None:
        resolved = path.resolve()
        if os.name == "nt":
            os.startfile(str(resolved))
        else:
            subprocess.Popen(["xdg-open", str(resolved)], shell=False)

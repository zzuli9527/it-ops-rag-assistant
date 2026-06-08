from __future__ import annotations

from pathlib import Path

import yaml


class PromptManager:
    def __init__(self, prompts_dir: Path) -> None:
        self.prompts_dir = prompts_dir
        versions_file = prompts_dir / "_versions.yaml"
        if versions_file.exists():
            self.versions = yaml.safe_load(versions_file.read_text(encoding="utf-8")) or {}
        else:
            self.versions = {}

    def load(self, name: str) -> str:
        version = self.versions.get(name, "v1")
        path = self.prompts_dir / name / f"{version}.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")


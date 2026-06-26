"""Agent Skill loader — discovers and loads pluggable skill packs from filesystem.

Skills follow the format:
  skills/<skill_name>/
    SKILL.md          # Frontmatter (YAML) + workflow instructions
    scripts/           # Python scripts
    resources/         # Data files, templates, models
"""

import importlib.util
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger


@dataclass
class Skill:
    """A loaded Agent Skill ready for execution."""
    name: str
    description: str
    path: str
    workflow: str            # Complete SKILL.md body (instructions for the LLM)
    scripts: dict = field(default_factory=dict)    # name -> callable
    resources: dict = field(default_factory=dict)  # name -> file path
    metadata: dict = field(default_factory=dict)   # YAML frontmatter


class SkillLoader:
    """Scans the skills/ directory and loads available skills."""

    def __init__(self, skills_dir: Optional[str] = None):
        if skills_dir is None:
            skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
        self.skills_dir = Path(skills_dir).resolve()
        self._skills: dict[str, Skill] = {}
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return

        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir() and not skill_dir.name.startswith("_"):
                try:
                    skill = self._load_skill(skill_dir)
                    self._skills[skill.name] = skill
                    logger.info(f"Loaded skill: {skill.name}")
                except Exception as e:
                    logger.error(f"Failed to load skill {skill_dir.name}: {e}")

    def _load_skill(self, skill_dir: Path) -> Skill:
        md_path = skill_dir / "SKILL.md"
        if not md_path.exists():
            raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

        content = md_path.read_text(encoding="utf-8")
        metadata, workflow = _parse_frontmatter(content)

        # Load scripts
        scripts_dir = skill_dir / "scripts"
        scripts = {}
        if scripts_dir.exists():
            for py_file in scripts_dir.glob("*.py"):
                mod_name = py_file.stem
                spec = importlib.util.spec_from_file_location(f"skill_{skill_dir.name}_{mod_name}", str(py_file))
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    # Find callable functions
                    for attr_name in dir(mod):
                        if callable(getattr(mod, attr_name)) and not attr_name.startswith("_"):
                            scripts[attr_name] = getattr(mod, attr_name)

        # Load resources
        resources_dir = skill_dir / "resources"
        resources = {}
        if resources_dir.exists():
            for res_file in resources_dir.iterdir():
                resources[res_file.name] = str(res_file)

        return Skill(
            name=metadata.get("name", skill_dir.name),
            description=metadata.get("description", ""),
            path=str(skill_dir),
            workflow=workflow,
            scripts=scripts,
            resources=resources,
            metadata=metadata,
        )

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get_skills_for_prompt(self) -> str:
        """Format all available skills as a prompt for the LLM."""
        lines = ["## 可用技能 (Agent Skills)\n"]
        for skill in self._skills.values():
            lines.append(f"### {skill.name}")
            lines.append(f"描述: {skill.description}")
            lines.append(f"工作流:\n{skill.workflow[:500]}...")
            lines.append("")
        return "\n".join(lines)

    def reload(self):
        self._skills.clear()
        self._load_all()


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md."""
    metadata = {}
    body = content
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if match:
        try:
            metadata = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            pass
        body = content[match.end():]
    return metadata, body.strip()

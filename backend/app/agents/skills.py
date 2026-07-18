"""
Skills loader — Agent Skills spec (SKILL.md) on strands-agents 1.x.

The installed Strands release has no native ``AgentSkills`` plugin yet, so this
module implements the same progressive-disclosure contract described in the
Strands docs:

- each skill is a directory under ``app/agents/skills/<name>/`` holding a
  ``SKILL.md`` with YAML frontmatter (``name``, ``description``) and a markdown
  instruction body;
- only the name + description are injected into an agent's system prompt (an
  ``<available_skills>`` block);
- the full instruction body is loaded on demand when the agent calls the
  ``load_skill`` tool.

When the SDK ships its own plugin, swap ``skills_prompt_block``/``load_skill``
for ``AgentSkills`` — the SKILL.md files are already in the spec's format.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import structlog
import yaml
from strands import tool

log = structlog.get_logger()

SKILLS_DIR = Path(__file__).parent / "skills"


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    instructions: str


def _parse_skill_md(text: str) -> SkillMeta | None:
    """Parse SKILL.md: ``---`` YAML frontmatter + markdown body."""
    if not text.startswith("---"):
        return None
    try:
        _, frontmatter, body = text.split("---", 2)
        meta = yaml.safe_load(frontmatter) or {}
        return SkillMeta(
            name=str(meta.get("name", "")).strip(),
            description=str(meta.get("description", "")).strip(),
            instructions=body.strip(),
        )
    except (ValueError, yaml.YAMLError) as e:
        log.warning("skill_md_parse_failed", error=str(e)[:120])
        return None


@lru_cache(maxsize=1)
def load_all_skills() -> dict[str, SkillMeta]:
    """Discover every skill directory containing a valid SKILL.md."""
    skills: dict[str, SkillMeta] = {}
    if not SKILLS_DIR.is_dir():
        return skills
    for skill_file in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        parsed = _parse_skill_md(skill_file.read_text(encoding="utf-8"))
        if parsed and parsed.name:
            skills[parsed.name] = parsed
    log.info("skills_loaded", count=len(skills), names=list(skills))
    return skills


def skills_prompt_block(skill_names: list[str]) -> str:
    """Build the <available_skills> system-prompt block for an agent's skills."""
    catalog = load_all_skills()
    entries = [catalog[n] for n in skill_names if n in catalog]
    if not entries:
        return ""
    lines = ["<available_skills>"]
    for s in entries:
        lines.append(
            f"  <skill><name>{s.name}</name>"
            f"<description>{s.description}</description></skill>"
        )
    lines.append("</available_skills>")
    lines.append(
        "When a task matches an available skill, call load_skill with its name "
        "first and follow the returned instructions."
    )
    return "\n".join(lines)


@tool
def load_skill(name: str) -> dict:
    """Load the full instructions for an available skill by name."""
    skill = load_all_skills().get(name)
    if skill is None:
        return {
            "error": f"Unknown skill: {name!r}. Available: {list(load_all_skills())}"
        }
    return {"name": skill.name, "instructions": skill.instructions}

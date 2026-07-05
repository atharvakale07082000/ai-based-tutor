"""
Loads YAML prompt files from the prompts/ directory.

All LLM-facing prompts live in these YAML files — there are no inline prompt
strings in the agent/generation code. Callers render a prompt by naming the file
and the key path to the template, then pass the runtime values as kwargs.

Templates use Python str.format syntax: ``{placeholder}`` for values supplied at
render time, and doubled braces ``{{`` / ``}}`` for literal JSON braces in the
template body. Returned dicts are deep-copied on each call so callers can mutate
them freely.
"""

import copy
from functools import lru_cache
from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def _load_raw(name: str) -> dict:
    path = _PROMPTS_DIR / f"{name}.yaml"
    with path.open() as f:
        return yaml.safe_load(f)


def load_prompt(name: str) -> dict:
    """Return a deep copy of the named prompt file (without .yaml extension)."""
    return copy.deepcopy(_load_raw(name))


def get_section(name: str, *path: str):
    """Return the raw value at ``path`` inside prompts/<name>.yaml (str, dict, list...)."""
    node = load_prompt(name)
    for key in path:
        node = node[key]
    return node


def render_prompt(name: str, *path: str, **kwargs) -> str:
    """Render the template at prompts/<name>.yaml -> ``path`` with ``kwargs``.

    ``path`` walks nested keys, e.g. render_prompt("interview_scorer", "analyze_answers").
    None values are rendered as empty strings; literal braces in the template must be
    doubled (``{{`` / ``}}``).
    """
    template = get_section(name, *path)
    if not isinstance(template, str):
        raise TypeError(f"{name}:{'.'.join(path)} is not a string template")
    return template.format_map({k: ("" if v is None else v) for k, v in kwargs.items()})


def get_system_prompt(name: str, **kwargs) -> str:
    """Load prompts/<name>.yaml and format system.base with kwargs."""
    return render_prompt(name, "system", "base", **kwargs)


def get_quiz_limits() -> dict:
    return load_prompt("quiz_generator")["limits"]


def get_doubt_limits() -> dict:
    return load_prompt("doubt_solver")["limits"]


def get_curriculum_config() -> dict:
    return load_prompt("curriculum")


def get_guardrails_config() -> dict:
    return load_prompt("guardrails")

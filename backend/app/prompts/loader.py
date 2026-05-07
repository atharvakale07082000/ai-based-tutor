"""
Loads YAML prompt files from the prompts/ directory.
Returned dicts are deep-copied on each call so callers can mutate them freely.
"""
import copy
from pathlib import Path
from functools import lru_cache
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


def get_system_prompt(name: str, **kwargs) -> str:
    """Load prompts/<name>.yaml and format system.base with kwargs."""
    data = load_prompt(name)
    template: str = data["system"]["base"]
    return template.format_map({k: (v or "") for k, v in kwargs.items()})


def get_bloom_prompt(topic: str, bloom_level: str) -> str:
    """Return the quiz generator prompt for a specific Bloom level, formatted with topic."""
    data = load_prompt("quiz_generator")
    template: str = data["bloom_prompts"].get(bloom_level, data["bloom_prompts"]["understand"])
    return template.format(topic=topic)


def get_quiz_limits() -> dict:
    return load_prompt("quiz_generator")["limits"]


def get_doubt_limits() -> dict:
    return load_prompt("doubt_solver")["limits"]


def get_curriculum_config() -> dict:
    return load_prompt("curriculum")


def get_guardrails_config() -> dict:
    return load_prompt("guardrails")

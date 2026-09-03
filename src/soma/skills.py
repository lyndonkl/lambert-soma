"""Skills — soma wires the SDK's skill system and audits it (ladder PR-07).

soma ships NO skills (same rule as archetypes: content is yours).
Sources are the SDK's own conventions — project `.agents/skills/`,
user `~/.agents/skills/` — and an archetype mounts one by listing its
name under `skills:`.

The audit is the reason this PR exists: skill files are prompt-and-
command content that gets injected into cells, so before anything
mounts them a human reviews the audit report (the build-plan's gate).
Checks, each with the reason it exists:

- render-time execution: a !`cmd` block runs a shell command the
  moment the skill text is rendered — before any model call. Flagged
  hard: that is code execution hiding in documentation.
- always-on skills (no trigger): loaded into EVERY prompt of every
  cell that mounts them — a token bomb and a standing-instruction
  risk. Flagged for review, not forbidden.
- shell-risk lint: destructive or exfiltration-shaped commands in the
  content (rm -rf, curl|sh, sudo, force-push, eval ...). A cell
  following instructions is a cell; the instructions deserve lint.
- oversized always-on content: permanent context should be small.
"""

from __future__ import annotations

import re
from pathlib import Path

RENDER_EXEC_RE = re.compile(r"!`[^`]+`")
SHELL_RISK_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("recursive delete", re.compile(r"\brm\s+(-\w*[rf]\w*\s+)+")),
    ("pipe-to-shell", re.compile(r"\b(curl|wget)\b[^\n|]*\|\s*(ba|z)?sh\b")),
    ("sudo", re.compile(r"\bsudo\b")),
    ("eval", re.compile(r"\beval\b")),
    ("force push", re.compile(r"git\s+push[^\n]*(-f\b|--force)")),
    ("world-writable chmod", re.compile(r"chmod\s+(-\w+\s+)*777")),
    ("decode-and-run", re.compile(r"base64\s+(-d|--decode)[^\n|]*\|")),
    ("device write", re.compile(r">\s*/dev/(sd|disk|null 2>&1 && rm)")),
)
ALWAYS_ON_SIZE_LIMIT = 6000  # chars of permanent context per skill


def load_skills(project_dir: Path | None = None) -> dict:
    """Every skill an archetype could mount here: project + user library.

    The user dir is resolved at call time (the SDK freezes its own
    user-dir constant at import time, which breaks testing and any
    HOME change); project skills win on name clashes.
    """
    from openhands.sdk.skills import load_available_skills
    from openhands.sdk.skills.skill import load_skills_from_dir

    merged: dict = {}
    repo, knowledge, agent = load_skills_from_dir(Path.home() / ".agents" / "skills")
    for group in (repo, knowledge, agent):
        merged.update(group)
    merged.update(
        load_available_skills(
            project_dir or Path.cwd(), include_user=False, include_project=True
        )
    )
    return merged


def audit_skills(project_dir: Path | None = None) -> list[tuple[bool | None, str]]:
    """Doctor-style findings. (ok, msg); ok=None is review-worthy, False is a stop."""
    checks: list[tuple[bool | None, str]] = []
    skills = load_skills(project_dir)
    if not skills:
        checks.append((None, "no skills found (project .agents/skills, ~/.agents/skills)"))
        return checks
    for name in sorted(skills):
        skill = skills[name]
        content = skill.content or ""
        where = skill.source or "?"
        hits = RENDER_EXEC_RE.findall(content)
        if hits:
            checks.append((False, (
                f"skill '{name}': render-time execution {hits[:3]} — runs shell "
                f"commands when the text is rendered, before any model call ({where})")))
        if skill.trigger is None and not skill.is_agentskills_format:
            checks.append((None, (
                f"skill '{name}': always-on (no trigger) — injected into every "
                f"prompt of any cell that mounts it; confirm it deserves that ({where})")))
            if len(content) > ALWAYS_ON_SIZE_LIMIT:
                checks.append((None, (
                    f"skill '{name}': {len(content)} chars of permanent context "
                    f"(> {ALWAYS_ON_SIZE_LIMIT}) — a token bomb")))
        for label, pattern in SHELL_RISK_PATTERNS:
            if pattern.search(content):
                checks.append((None, (
                    f"skill '{name}': contains {label} — fine if intended; "
                    f"a reviewer should say so ({where})")))
        if not any(m for ok, m in checks if f"'{name}'" in m):
            checks.append((True, f"skill '{name}': clean ({where})"))
    return checks

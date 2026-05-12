"""Smoke tests for the .claude/ course-requirement artifacts.

These don't test app logic — they catch typos and missing files in the
skills + MCP + commands setup so a broken config shows up in CI rather
than during the Week 16 demo.
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CLAUDE_DIR = PROJECT / ".claude"


def test_settings_json_parses():
    settings_path = CLAUDE_DIR / "settings.json"
    assert settings_path.exists(), ".claude/settings.json missing"
    data = json.loads(settings_path.read_text())
    # MCP server registered.
    assert "mcpServers" in data
    assert "askcsv-samples" in data["mcpServers"]


def test_skills_present():
    for name in ("analyst-persona", "chart-picker"):
        skill_md = CLAUDE_DIR / "skills" / name / "SKILL.md"
        assert skill_md.exists(), f"missing skill: {name}"
        body = skill_md.read_text()
        assert body.startswith("---"), f"{name} SKILL.md missing frontmatter"
        assert f"name: {name}" in body, f"{name} SKILL.md frontmatter missing name"


def test_commands_present():
    for cmd in ("ralph.md", "seed-tests.md"):
        cmd_path = CLAUDE_DIR / "commands" / cmd
        assert cmd_path.exists(), f"missing command: {cmd}"
        assert cmd_path.read_text().startswith("---"), f"{cmd} missing frontmatter"

#!/usr/bin/env python3
################################################################################
# File: test_claude_render.py
# Path: {PROJECT_ROOT}/tests/test_claude_render.py
# Created by: Ryan Severe
# Created: 2026-11-13
# Last Updated: 2026-11-13
# Description: Tests for Claude Code as a render target - rules, skills and agents -
#              and for the tool table Copilot, Cursor and Claude Code share. Covers
#              rule scope rendering, the skill root, agent frontmatter, a fake
#              fourth tool, drift on a rendered file and the local settings ignore.
################################################################################
# ===========================================================================
#
#
#            "~,
#                *m,
#                   *9m;
#                       *%pg
#                          "YRWu
#                              *9$&w
#                                  *R$&w
#   ;j]@@W;                   *w,      79&&w;
#   :|*%MT"                     7&&w,      ?78BWw
# . ,|*       -p     ~            *R$$$gw,     '*MU@m,
#            =W/?*%NMWgw             *T&$F ,@w;     "*4[%m,
#              7R$$$$$$$$g          yg$$Gg$@@Hh!j ,w     "*w|j=,
#       ..     ]K@ww[T$Fff            >*MB&&@@Hh ]hk{!!~^     "*v'
#          '|;, *M@@&&$P                 $$&@HHH\  ` ;w,,   ,~""
#            "|jj]]%@F"                  ]$@@H, ;*M%P)a$$C  c
#           . :|j[M"                     ]@@HHr TfR4&$NE*,/~<'
#             `!||j]@@@A`                ]@@Hh~ *TT"" "* ^ r  '~
#                *ojKM"                  l@Hh~  "*|"'   /        `
#                                        @HHkC ,;!"
#                                       ]HHhr/|!"'
#                                       #Hhr!||"
#                             ,@r       hkr!||'
#                                      [k{|!"
#                                     (r!!"        r
#                                     !!"        r
#                                      ";      /
#                                             '
#                                            '
# ===========================================================================


from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sync  # noqa: E402

SHA = "abc1234"
EXAMPLE = sync.ROOT / "examples" / "profile"
MANIFEST = sync.load_profile(EXAMPLE)
DEFAULTS = MANIFEST.get("defaults") or {}
EXERCISES = ["rules/**", "agents/**", "skills/**", "examples/profile/**"]


def plan_for(profile_dir: Path = EXAMPLE, manifest: dict = MANIFEST) -> sync.Plan:
    return sync.build_plan("t", {"estate": True}, DEFAULTS, SHA, manifest,
                           profile_dir=profile_dir)


def plan_for_defaults(defaults: dict) -> sync.Plan:
    return sync.build_plan("t", {"estate": True}, defaults, SHA, MANIFEST, profile_dir=EXAMPLE)


def frontmatter(text: str) -> str:
    return text.split("---\n", 2)[1] if text.startswith("---\n") else ""


class ClaudeRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = plan_for()

    def test_always_on_rule_has_no_paths_and_no_frontmatter(self):
        text = self.plan[".claude/rules/estate.md"]
        self.assertTrue(text.startswith("<!-- generated from "), text[:60])
        self.assertNotIn("paths:", text)

    def test_scoped_rule_has_a_paths_list(self):
        text = self.plan[".claude/rules/python.md"]
        self.assertTrue(text.startswith('---\npaths:\n  - "**/*.py"\n---\n'), text[:80])

    def test_on_demand_rule_is_not_rendered(self):
        self.assertIn(".github/rules/personal.md", self.plan)
        self.assertNotIn(".claude/rules/personal.md", self.plan)

    def test_conventions_are_not_rendered(self):
        conventions = {"description": "d"}
        self.assertIsNone(sync.render_claude_rule(conventions, "b", SHA))

    def test_no_claude_md(self):
        self.assertNotIn("CLAUDE.md", self.plan)
        self.assertFalse([p for p in self.plan if p.endswith("CLAUDE.md")])

    def test_copilot_and_cursor_rules_are_unchanged(self):
        meta = {"description": "d", "scope": "**/*.py"}
        self.assertEqual(sync.TOOLS[0].rule(meta, "b", SHA), sync.render_copilot(meta, "b", SHA))
        self.assertEqual(sync.TOOLS[1].rule(meta, "b", SHA), sync.render_cursor(meta, "b", SHA))
        self.assertIsNone(sync.TOOLS[0].rule({"description": "d"}, "b", SHA))


class RuleTools(unittest.TestCase):
    """A rule's optional tools: key limits which rows of TOOLS render it."""

    def setUp(self):
        sync.set_stamp_source(MANIFEST)

    def rendered(self, **meta) -> sync.Plan:
        plan = sync.Plan()
        sync.add_rules(plan, "x", {"description": "d", "alwaysApply": True, **meta}, "b", SHA)
        return plan

    def test_a_claude_only_rule_renders_to_claude_alone(self):
        self.assertEqual(list(self.rendered(tools=["claude"])), [".claude/rules/x.md"])

    def test_a_rule_without_tools_renders_to_every_tool(self):
        self.assertEqual(
            set(self.rendered()),
            {t.rule_path.format(id="x") for t in sync.TOOLS})

    def test_an_unknown_tool_name_is_refused(self):
        with self.assertRaises(sync.SyncError) as caught:
            self.rendered(tools=["claude", "emacs"])
        self.assertIn("emacs", str(caught.exception))

    def test_tools_on_an_on_demand_rule_is_refused(self):
        with self.assertRaises(sync.SyncError):
            self.rendered(tools=["claude"], alwaysApply=False)

    def test_the_claude_code_rule_renders_for_claude_only(self):
        defaults = {**DEFAULTS, "tier2": list(DEFAULTS.get("tier2", [])) + ["claude-code"]}
        plan = plan_for_defaults(defaults)
        self.assertIn(".claude/rules/claude-code.md", plan)
        self.assertNotIn(".cursor/rules/claude-code.mdc", plan)
        self.assertNotIn(".github/instructions/claude-code.instructions.md", plan)
        self.assertFalse([p for p in plan if "claude-code" in p and not p.startswith(".claude/")])

    def test_the_claude_code_rule_quotes_the_reply_marker_exactly(self):
        sys.path.insert(0, str(sync.ROOT / "responses"))
        import claude
        text = (sync.RULES_DIR / "spec-claude-code.md").read_text(encoding="utf-8")
        self.assertIn(claude.REPLY_MARKER, text)
        # Every mention of the marker is the whole constant, never a paraphrase of it.
        self.assertEqual(text.count(claude.REPLY_MARKER), text.upper().count("REPLY STARTS HERE"))


class ClaudeSkills(unittest.TestCase):
    def test_skill_renders_with_assets_identically_to_the_other_roots(self):
        plan = plan_for()
        claude = {k.split("/", 2)[2]: v for k, v in plan.items()
                  if k.startswith(".claude/skills/")}
        github = {k.split("/", 2)[2]: v for k, v in plan.items()
                  if k.startswith(".github/skills/")}
        self.assertTrue(claude)
        self.assertEqual(claude, github)
        self.assertTrue(any(name.endswith("/SKILL.md") for name in claude))
        self.assertTrue(any(not name.endswith("/SKILL.md") for name in claude), "no asset")


class ClaudeAgents(unittest.TestCase):
    def setUp(self):
        sync.set_stamp_source(MANIFEST)
        self.warnings: list[str] = []

    def render(self, **meta) -> str:
        return sync.render_claude_agent({"name": "x", "description": "d", **meta}, "body", SHA,
                                        self.warnings.append)

    def test_tools_map_deduplicated_in_first_seen_order(self):
        head = frontmatter(self.render(tools=["read", "search", "edit", "execute",
                                              "execute/runInTerminal", "agent"]))
        self.assertIn("tools: Read, Grep, Glob, Edit, Write, Bash, PowerShell, Agent\n", head)
        self.assertEqual(self.warnings, [])

    def test_subsumed_terminal_tools_are_silent(self):
        head = frontmatter(self.render(tools=["read", "execute/getTerminalOutput",
                                              "execute/killTerminal", "execute/testFailure"]))
        self.assertIn("tools: Read\n", head)
        self.assertEqual(self.warnings, [])

    def test_unmapped_tool_is_dropped_with_a_warning_naming_agent_and_tool(self):
        head = frontmatter(self.render(tools=["read", "web"]))
        self.assertIn("tools: Read\n", head)
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("x", self.warnings[0])
        self.assertIn("'web'", self.warnings[0])

    def test_omitted_tools_stay_omitted(self):
        self.assertNotIn("tools:", frontmatter(self.render()))

    def test_agents_key_is_not_rendered_and_does_not_warn(self):
        head = frontmatter(self.render(tools=["read"], agents=["Explore"]))
        self.assertNotIn("agents:", head)
        self.assertEqual(self.warnings, [])

    def test_model_defaults_to_inherit_and_is_rendered_when_set(self):
        self.assertIn("model: inherit\n", frontmatter(self.render()))
        self.assertIn("model: sonnet\n", frontmatter(self.render(model="sonnet")))

    def test_field_order(self):
        head = frontmatter(self.render(tools=["read"]))
        keys = [line.split(":")[0] for line in head.splitlines() if not line.startswith(" ")]
        self.assertEqual(keys, ["name", "description", "tools", "model"])

    def test_an_all_unmapped_tool_list_refuses(self):
        with self.assertRaises(sync.SyncError):
            self.render(tools=["web"])

    def test_copilot_agent_ignores_model(self):
        meta = {"name": "x", "description": "d", "tools": ["read"], "model": "sonnet"}
        copilot = sync.TOOLS[0].agent(meta, "b", SHA, self.warnings.append)
        self.assertEqual(copilot, sync.render_agent(meta, "b", SHA))
        self.assertNotIn("model", copilot)

    def test_plan_has_claude_agents_for_interactive_roles_without_an_agents_warning(self):
        plan = plan_for()
        self.assertIn(".claude/agents/coder.md", plan)
        self.assertIn("model: sonnet\n", frontmatter(plan[".claude/agents/coder.md"]))
        self.assertIn("model: inherit\n", frontmatter(plan[".claude/agents/auditor.md"]))
        self.assertFalse([w for w in plan.warnings if "agents:" in w], plan.warnings)
        self.assertFalse([p for p in plan if p.startswith(".cursor/agents")])

    def test_core_models_follow_the_split(self):
        for name, model in (("coder", "sonnet"), ("test-writer", "sonnet"),
                            ("fact-keeper", "sonnet"), ("auditor", "inherit"),
                            ("qa", "inherit"), ("design-partner", "inherit")):
            with self.subTest(agent=name):
                meta, _ = sync.load_doc(sync.AGENTS_DIR / name / "definition.md", "name")
                self.assertEqual(meta["model"], model)

    def test_an_invalid_model_is_refused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "profile"
        shutil.copytree(EXAMPLE, folder)
        agent = folder / "seeds" / "agents" / "odd" / "definition.md"
        agent.parent.mkdir(parents=True)
        agent.write_text("---\nname: odd\ndescription: d\nmodel: gpt\n---\nbody\n",
                         encoding="utf-8", newline="\n")
        with self.assertRaises(sync.SyncError) as caught:
            plan_for(folder)
        self.assertIn("model", str(caught.exception))


class ToolTable(unittest.TestCase):
    def test_a_fourth_tool_is_a_table_row_only(self):
        fake = sync.Tool(
            "fake", ".fake/rules/{id}.txt",
            lambda meta, body, sha: f"rule:{meta['id'] if 'id' in meta else 'x'}",
            ".fake/skills", ".fake/agents/{name}.txt",
            lambda meta, body, sha, warn: f"agent:{meta['name']}")
        with mock.patch.object(sync, "TOOLS", sync.TOOLS + (fake,)):
            plan = plan_for()
        self.assertIn(".fake/rules/estate.txt", plan)
        self.assertIn(".fake/rules/python.txt", plan)
        self.assertTrue([p for p in plan if p.startswith(".fake/skills/") and
                         p.endswith("/SKILL.md")])
        self.assertEqual(plan[".fake/agents/coder.txt"], "agent:coder")

    def test_every_row_names_distinct_output(self):
        paths = [t.rule_path for t in sync.TOOLS]
        self.assertEqual(len(set(paths)), len(paths))

    def test_owned_paths_cover_the_claude_directories(self):
        for sub in ("rules", "skills", "agents"):
            self.assertIn(f".claude/{sub}/", sync.SELF_RENDERED)
            self.assertIn(f".claude/{sub}", sync.RENDER_DIRS)
        self.assertNotIn(".claude/", sync.SELF_RENDERED)


def init_repo(test: unittest.TestCase) -> Path:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    repo = Path(tmp.name)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True, env=env,
                   capture_output=True, timeout=60)
    return repo


class ClaudeOwnership(unittest.TestCase):
    IDENT = {"name": "n", "email": "n@example.invalid"}

    def test_check_reports_drift_on_a_hand_edited_rule(self):
        repo = init_repo(self)
        plan = plan_for()
        with mock.patch("builtins.print"):
            sync.emit(repo, plan, True, ident=self.IDENT)
            self.assertEqual(sync.emit(repo, plan, False, ident=self.IDENT), 0)
            rule = repo / ".claude" / "rules" / "estate.md"
            rule.write_text(rule.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
            self.assertGreaterEqual(sync.emit(repo, plan, False, ident=self.IDENT), 1)

    def test_orphaned_claude_files_are_found(self):
        repo = init_repo(self)
        plan = plan_for()
        with mock.patch("builtins.print"):
            sync.emit(repo, plan, True, ident=self.IDENT)
        smaller = {k: v for k, v in plan.items() if k != ".claude/rules/python.md"
                   and k != ".claude/agents/coder.md"}
        self.assertEqual(sync.find_orphans(repo, smaller),
                         [".claude/agents/coder.md", ".claude/rules/python.md"])

    def test_local_settings_is_ignored_and_never_touched(self):
        repo = init_repo(self)
        local = repo / ".claude" / "settings.local.json"
        local.parent.mkdir(parents=True)
        local.write_text('{"permissions": {}}\n', encoding="utf-8")
        plan = plan_for()
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_claude_local_ignored(repo, write=False), 1)
            self.assertEqual(sync.ensure_claude_local_ignored(repo, write=True), 1)
            self.assertEqual(sync.ensure_claude_local_ignored(repo, write=True), 0)
            sync.emit(repo, plan, True, ident=self.IDENT)
        self.assertNotIn(".claude/settings.local.json", plan)
        self.assertEqual(sync.find_orphans(repo, plan), [])
        self.assertEqual(sync.find_foreign(repo, plan), [])
        self.assertEqual(local.read_text(encoding="utf-8"), '{"permissions": {}}\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        found = subprocess.run(["git", "check-ignore", "-q", ".claude/settings.local.json"],
                               cwd=repo, env=env, timeout=60)
        self.assertEqual(found.returncode, 0)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
################################################################################
# File: test_sync.py
# Path: {PROJECT_ROOT}/tests/test_sync.py
# Created by: Ryan Severe
# Created: 2026-09-26
# Last Updated: 2026-11-10
# Description: Tests for sync.py - the renderer that decides what every AI
#              session in the estate reads. Covers build_plan over every real
#              manifest target, exclude validation, the hand-owned guard, stamp
#              placement, frontmatter shape, the stamp's source-input list,
#              the generated issue-key table, orphan versus foreign detection,
#              Cursor hook rendering, and the --rollout command against
#              temporary repositories.
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

import contextlib
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sync  # noqa: E402

SHA = "abc1234"
EXAMPLE = sync.ROOT / "examples" / "profile"
MANIFEST = sync.load_profile(EXAMPLE)
# The stamp a render from MANIFEST writes; sync.STAMP_MARKER is any stamp's shape.
MARK = f"generated from {MANIFEST['source']['repo']}@"

# What sync.py renders from. It reads these as data, which coverage cannot see.
RENDER_SOURCES = ["actions/**", "agents/**", "context/**", "githooks/**", "rules/**",
                  "skills/**", "tickets/**", "workflows/**", "profile.yaml", "profile.lock",
                  "consent.py",
                  "responses/**", "gate_report.py", "prime.py", "gh_passthrough.py", "hooks/**",
                  "capabilities/**", "opqueue/**", "exchange/**"]
EXERCISES = RENDER_SOURCES
DEFAULTS = MANIFEST.get("defaults") or {}


# A skill for a test profile to bind tracker.query to; the core ships no tracker skill.
TRACKER = "skills/example-tracker/procedure.md"
TRACKER_TEXT = "---\nname: example-tracker\ndescription: d\n---\nbody\n"


def build_plan(*args, profile_dir: Path = EXAMPLE, **kwargs) -> sync.Plan:
    """sync.build_plan against the example profile unless a test names its own."""
    return sync.build_plan(*args, profile_dir=profile_dir, **kwargs)


def example_copy(test: unittest.TestCase, gates: tuple[str, ...] = ()) -> Path:
    """A copy of examples/profile, seeds included, with a trivial gate seeded per name."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    folder = Path(tmp.name) / "profile"
    shutil.copytree(EXAMPLE, folder)
    for name in gates:
        gate = folder / "seeds" / "githooks" / "gates" / f"{name}.sh"
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text("exit 0\n", encoding="utf-8")
    return folder


def locked_example(test: unittest.TestCase) -> Path:
    """A copy of examples/profile with every gate consented on. The example ships with no
    lock, so whoever copies it runs `consent.py --init` themselves."""
    folder = example_copy(test)
    path = folder / "profile.yaml"
    features = lock_all_on(folder)
    if features:
        path.write_text(sync.consent.replace_features_block(
            path.read_text(encoding="utf-8"),
            sync.consent.render_features_block(features["gates"])), encoding="utf-8")
    return folder


def lock_all_on(folder: Path) -> dict:
    """Write a lock consenting every gate `folder` knows, and return its features: value.
    With no gate there is nothing to pin, so no lock and an empty value."""
    known = sync.consent.known_gates(folder)
    if not known:
        return {}
    features = {"gates": {name: True for name in known}}
    (folder / sync.consent.LOCK_NAME).write_text(sync.consent.render_lock(features),
                                                 encoding="utf-8")
    return features


def live_targets() -> dict[str, dict]:
    return {name: cfg or {} for name, cfg in (MANIFEST.get("targets") or {}).items()
            if not (cfg or {}).get("skip")}


def own_drops(profile: Path, entries: list) -> list:
    """The drops from a test's own seeds. The core's seeds drop too under a partial binding,
    and test_core_seeds_render_with_pointers_and_drop_when_unbound pins those."""
    return [entry for entry in entries if Path(entry[0]).is_relative_to(profile)]


class BuildPlan(unittest.TestCase):
    def test_every_target_renders(self):
        self.assertTrue(live_targets(), "manifest has no live targets; the loop below is vacuous")
        for name, cfg in live_targets().items():
            with self.subTest(target=name):
                plan = build_plan(name, cfg, DEFAULTS, SHA, MANIFEST)
                self.assertIn("AGENTS.md", plan)
                self.assertTrue(any(k.startswith(".github/skills/") for k in plan))

    def test_self_config_renders(self):
        plan = build_plan("example-profile", sync.self_config(MANIFEST), DEFAULTS, SHA, MANIFEST)
        self.assertIn(".github/instructions/estate.instructions.md", plan)

    def test_prime_script_reaches_every_target(self):
        """/prime calls .github/scripts/prime.py from whichever repo it is in."""
        for name, cfg in live_targets().items():
            with self.subTest(target=name):
                plan = build_plan(name, cfg, DEFAULTS, SHA, MANIFEST)
                self.assertIn("def prime_one", plan.get(".github/scripts/prime.py", ""))

    def test_cleanup_reaches_every_target(self):
        """Intent: `.github/scripts/cleanup.py` exists, rendered into every target."""
        for name, cfg in live_targets().items():
            with self.subTest(target=name):
                plan = build_plan(name, cfg, DEFAULTS, SHA, MANIFEST)
                self.assertIn("def apply", plan.get(".github/scripts/cleanup.py", ""))

    def test_unmatched_exclude_raises_and_names_only_the_typo(self):
        real = (DEFAULTS.get("tier1") or DEFAULTS.get("tier2"))[0]
        with self.assertRaises(sync.SyncError) as caught:
            build_plan("t", {"exclude": [real, "no-such-rule"]}, DEFAULTS, SHA, MANIFEST)
        self.assertIn("no-such-rule", str(caught.exception))
        self.assertNotIn(f"'{real}'", str(caught.exception))

    def test_a_real_exclusion_drops_the_rule(self):
        real = (DEFAULTS.get("tier1") or DEFAULTS.get("tier2"))[0]
        plan = build_plan("t", {"exclude": [real]}, DEFAULTS, SHA, MANIFEST)
        self.assertFalse(any(f"/{real}." in k for k in plan))

    def test_hand_owned_paths_are_refused(self):
        with mock.patch.object(sync, "NEVER_WRITE", sync.NEVER_WRITE | {"AGENTS.md"}):
            with self.assertRaises(sync.SyncError):
                build_plan("t", {}, DEFAULTS, SHA, MANIFEST)

    def test_skills_land_in_both_roots_identically(self):
        plan = build_plan("t", {}, DEFAULTS, SHA, MANIFEST)
        cursor = {k.split("/", 1)[1]: v for k, v in plan.items() if k.startswith(".cursor/skills/")}
        github = {k.split("/", 1)[1]: v for k, v in plan.items() if k.startswith(".github/skills/")}
        self.assertTrue(cursor)
        self.assertEqual(cursor, github)

    def test_no_skill_renders_where_opencode_looks(self):
        """Intent: OpenCode is the factory's tool, and it loads
        .agents/skills/ even with OPENCODE_DISABLE_PROJECT_CONFIG set, so a skill there
        hands interactive procedures to a headless role."""
        plan = build_plan("t", {}, DEFAULTS, SHA, MANIFEST)
        self.assertFalse([k for k in plan if k.startswith(".agents/")])

    def test_the_source_tree_s_old_agents_skills_are_not_a_dirty_tree(self):
        """Intent: the self-render deletes the old .agents/skills/ as
        orphans, and without this the dirty check refuses the render that follows."""
        self.assertIn(".agents/skills/", sync.SELF_RENDERED)

    def test_estate_map_is_opt_in(self):
        """A work repo must never receive the personal estate map by omission."""
        plan = build_plan("t", {}, DEFAULTS, SHA, MANIFEST)
        self.assertNotIn(".github/instructions/estate.instructions.md", plan)

    def test_repo_list_follows_the_estate_opt_in(self):
        """The repo list names the personal repos, so it follows the map."""
        opted = build_plan("t", {"estate": True}, DEFAULTS, SHA, MANIFEST)
        default = build_plan("t", {}, DEFAULTS, SHA, MANIFEST)
        rendered = json.loads(opted[sync.REPO_LIST])
        rendered.pop("_generated")
        self.assertEqual(rendered, sync.repo_list(MANIFEST))
        self.assertNotIn(sync.REPO_LIST, default)

    def test_the_repo_list_carries_the_stamp(self):
        """Intent: unstamped, the rendered-only gate read it as hand-written and every
        rollout that changed it ran each target's full test suite."""
        plan = build_plan("t", {"estate": True}, DEFAULTS, SHA, MANIFEST)
        head = "\n".join(plan[sync.REPO_LIST].splitlines()[:40])
        self.assertRegex(head, r"generated from [^ @]+@[0-9a-f]{7}")
        self.assertIn(f"{MARK}{SHA}", json.loads(plan[sync.REPO_LIST])["_generated"])

    def test_core_seeds_render_with_pointers_and_drop_when_unbound(self):
        """Intent: with every capability bound the core seeds point at the
        profile's skills; with none bound design-partner is not rendered, the others lose only
        their guarded sections, and every drop is listed."""
        agent = ".github/agents/design-partner.agent.md"
        sitrep = ".github/prompts/sitrep.prompt.md"
        handoff = ".github/skills/handoff/SKILL.md"
        profile = example_copy(self)
        tracker = profile / "seeds" / TRACKER
        tracker.parent.mkdir(parents=True)
        tracker.write_text(TRACKER_TEXT, encoding="utf-8", newline="\n")
        every = {cap: {"skill": "example-tracker"} for cap in sync.known_capabilities()}
        bound = build_plan("t", {}, DEFAULTS, SHA, {**MANIFEST, "capabilities": every},
                           profile_dir=profile)
        for path in (agent, sitrep, handoff):
            with self.subTest(bound=path):
                self.assertIn("the `example-tracker` skill", bound[path])
        bare = build_plan("t", {}, DEFAULTS, SHA, {**MANIFEST, "capabilities": {}})
        self.assertNotIn(agent, bare)
        self.assertIn("## Step 3", bare[sitrep])
        self.assertNotIn("## Step 2", bare[sitrep])
        self.assertNotIn("| A milestone |", bare[handoff])
        self.assertIn("git status -sb", bare[handoff])
        self.assertEqual([(p.parts[-2], caps) for p, caps in bare.dropped],
                         [("design-partner", ["tracker.create", "tracker.edit", "tracker.status"])])
        self.assertEqual(sorted(p.parent.name for p, _, _ in bare.dropped_sections),
                         ["context", "context", "handoff"])

    def test_repo_list_replaces_the_file_beside_the_ticket_tool(self):
        """Intent: the core renders the repo list at a profile path, and the
        ticket tool's old copy is no longer rendered."""
        plan = build_plan("t", {"estate": True}, DEFAULTS, SHA, MANIFEST)
        self.assertEqual(sync.REPO_LIST, ".github/profile/repos.json")
        self.assertNotIn(".github/scripts/tickets/estate.json", plan)
        self.assertIn(".github/profile", sync.RENDER_DIRS)

    def test_repo_list_lists_every_live_target_by_github_name(self):
        data = sync.repo_list(MANIFEST)
        names = {r["name"]: r["github"] for r in data["repos"]}
        self.assertEqual(set(names) - {MANIFEST["source"]["repo"]}, set(live_targets()))
        self.assertEqual(data["owner"], MANIFEST["source"]["owner"])

    def test_repo_list_refuses_a_profile_with_no_owner(self):
        """Intent: unknown is not zero - no owner means no GitHub name, never a guessed one."""
        with self.assertRaises(sync.SyncError):
            sync.repo_list({**MANIFEST, "source": {**MANIFEST["source"], "owner": ""}})

    def test_sync_imports_nothing_from_the_ticket_tool(self):
        """Intent: the core renders the ticket tool and never imports it."""
        text = (sync.ROOT / "sync.py").read_text(encoding="utf-8")
        self.assertNotIn("import estate", text)
        self.assertNotIn("sys.path.insert(0, str(TICKETS_DIR))", text)

    def test_response_checker_renders_as_one_directory(self):
        """The entry point imports its shape core and adapters as siblings,
        so every module lands beside it, and the single-file path is gone."""
        plan = build_plan("t", {}, DEFAULTS, SHA, MANIFEST)
        rendered = {k for k in plan if k.startswith(".github/scripts/responses/")}
        expected = {f".github/scripts/responses/{p.name}"
                    for p in sync.RESPONSES_DIR.glob("*.py")}
        self.assertIn(".github/scripts/responses/check_response.py", rendered)
        self.assertEqual(rendered, expected)
        self.assertNotIn(".github/scripts/check_response.py", plan)

    def test_exchange_tool_renders_into_every_target(self):
        """Intent: the exchange skill's append tool renders into every target, under
        `.github/scripts/exchange/`."""
        expected = {f".github/scripts/exchange/{p.name}" for p in sync.EXCHANGE_DIR.glob("*.py")}
        self.assertIn(".github/scripts/exchange/exchange.py", expected)
        for name, cfg in live_targets().items():
            with self.subTest(target=name):
                plan = build_plan(name, cfg, DEFAULTS, SHA, MANIFEST)
                rendered = {k for k in plan if k.startswith(".github/scripts/exchange/")}
                self.assertEqual(rendered, expected)
                shebang, marker = plan[".github/scripts/exchange/exchange.py"].splitlines()[:2]
                self.assertEqual(shebang, "#!/usr/bin/env python3")
                self.assertTrue(sync.is_stamped(marker), marker)


class RenderAsset(unittest.TestCase):
    def setUp(self):
        sync.set_stamp_source(MANIFEST)

    def asset(self, suffix: str, content: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False,
                                             encoding="utf-8", newline="\n")
        handle.write(content)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(path.unlink)
        return path

    def test_shebang_stays_on_line_one(self):
        lines = sync.render_asset(self.asset(".py", "#!/usr/bin/env python3\nprint(1)\n"), SHA).splitlines()
        self.assertEqual(lines[0], "#!/usr/bin/env python3")
        self.assertIn(f"{MARK}{SHA}", lines[1])
        self.assertEqual(lines[2], "print(1)")

    def test_no_shebang_stamps_line_one(self):
        lines = sync.render_asset(self.asset(".sh", "echo hi\n"), SHA).splitlines()
        self.assertIn(f"{MARK}{SHA}", lines[0])
        self.assertEqual(lines[1], "echo hi")

    def test_unstampable_format_is_verbatim(self):
        body = '{"a": 1}\n'
        self.assertEqual(sync.render_asset(self.asset(".json", body), SHA), body)

    def test_markdown_asset_is_stamped_on_line_one(self):
        # Intent: every target's no-change-docs gate refuses an unstamped .md.
        lines = sync.render_asset(self.asset(".md", "# Boundary values\n"), SHA).splitlines()
        self.assertEqual(lines[0], sync.stamp(SHA))
        self.assertIn("# Boundary values", lines)

    def test_markdown_asset_frontmatter_stays_on_line_one(self):
        body = "---\ntitle: x\n---\n# Body\n"
        lines = sync.render_asset(self.asset(".md", body), SHA).splitlines()
        self.assertEqual(lines[:3], ["---", "title: x", "---"])
        self.assertEqual(lines[3], sync.stamp(SHA))
        self.assertIn("# Body", lines)

    def test_markdown_asset_stamp_is_where_the_gate_reads(self):
        # The gate's stamped() reads only the first 40 lines - .githooks/lib/stamp.sh.
        head = "\n".join(sync.render_asset(self.asset(".md", "# x\n"), SHA).splitlines()[:40])
        self.assertTrue(sync.is_stamped(head))


class RenderPrompt(unittest.TestCase):
    def setUp(self):
        sync.set_stamp_source(MANIFEST)

    def test_a_prompt_without_mode_renders_without_one(self):
        """Intent: no default mode; a rendered mode: agent switches the chat off its role agent and it stays switched."""
        head = sync.render_prompt({"description": "d"}, "body", SHA).split("\n---", 1)[0]
        self.assertNotIn("mode:", head)

    def test_a_prompt_that_sets_mode_keeps_it(self):
        """Intent: only the default is dropped; a source that names an agent still pins it."""
        head = sync.render_prompt({"mode": "ask", "description": "d"}, "body", SHA).split("\n---", 1)[0]
        self.assertIn("mode: ask", head)

    def test_no_shipped_prompt_pins_an_agent(self):
        """Intent: no rendered prompt carries mode:, in any target."""
        for name, cfg in live_targets().items():
            plan = build_plan(name, cfg, DEFAULTS, SHA, MANIFEST)
            for path, text in plan.items():
                if path.startswith(".github/prompts/"):
                    with self.subTest(target=name, prompt=path):
                        self.assertNotIn("\nmode:", "\n" + text.split("\n---", 1)[0])


class ProbeCapacity(unittest.TestCase):
    """`sync.py --probe-capacity`: the sanctioned way to see what a rollout would push at."""

    def stored(self) -> tuple[int, str]:
        result = subprocess.run(("git", "config", "--get", "rollout.parallel"), cwd=sync.ROOT,
                                capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout

    def test_it_reports_and_writes_nothing(self):
        """Intent: a read-only check, so running it must leave the clone's git config as it found it."""
        before = self.stored()
        result = subprocess.run((sys.executable, "sync.py", "--profile", str(EXAMPLE),
                                 "--probe-capacity"), cwd=sync.ROOT,
                                capture_output=True, text=True, timeout=120,
                                env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cores:", result.stdout)
        self.assertIn("at a time", result.stdout)
        self.assertEqual(self.stored(), before, "--probe-capacity changed git config")

    def test_it_says_when_capacity_cannot_be_read(self):
        """Intent: unreadable capacity falls back to the manifest default."""
        out = io.StringIO()
        with mock.patch("os.cpu_count", return_value=None), \
                mock.patch.object(sys, "argv", ["sync.py", "--profile", str(EXAMPLE),
                                                "--probe-capacity"]), \
                contextlib.redirect_stdout(out):
            code = sync.main()
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("could not be read", out.getvalue())
        self.assertIn(str(MANIFEST["rollout"]["parallel_default"]), out.getvalue())


class MainArgv(unittest.TestCase):
    """`sync.main(argv)`: toolboxctl's render step calls it in-process, with its own arguments."""

    def test_it_parses_the_argv_it_is_given_rather_than_sys_argv(self):
        """Intent: sync.main gains an argv parameter passed to
        parse_args. A sys.argv argparse would refuse proves the given argv is what was parsed."""
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["sync.py", "--no-such-flag"]), \
                contextlib.redirect_stdout(out):
            code = sync.main(["--profile", str(EXAMPLE), "--probe-capacity"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("at a time", out.getvalue())


class RenderAgent(unittest.TestCase):
    """A role without edit must not regain writing through a tool set or a subagent."""

    WRITES = {"execute", "execute/createAndRunTask", "execute/runNotebookCell"}

    def setUp(self):
        sync.set_stamp_source(MANIFEST)

    @staticmethod
    def roles() -> dict[str, dict]:
        return {p.parent.name: sync.load_doc(p, "name", "description")[0]
                for p in sorted(sync.AGENTS_DIR.glob("*/definition.md"))}

    def test_the_agents_allowlist_is_rendered(self):
        """Intent: the allowlist is only enforced if it reaches the rendered file."""
        head = sync.render_agent({"name": "x", "description": "d", "tools": ["read", "agent"],
                                  "agents": ["Explore"]}, "body", SHA).split("\n---", 1)[0]
        self.assertIn('agents: ["Explore"]', head)

    def test_a_role_without_edit_gets_no_indirect_writer(self):
        """Intent: the execute tool set brings createAndRunTask and
        runNotebookCell, which write files; a role without edit names its execute tools one by one."""
        for name, meta in self.roles().items():
            tools = set(meta.get("tools") or [])
            if "edit" not in tools:
                with self.subTest(role=name):
                    self.assertFalse(tools & self.WRITES, f"{name} can write through {tools & self.WRITES}")

    def test_a_role_without_edit_cannot_delegate_to_one_with_it(self):
        """Intent: a subagent named by agentName runs with that agent's
        tools, and omitting `agents` permits every agent (VS Code subagents documentation)."""
        roles = self.roles()
        writers = {n for n, m in roles.items() if "edit" in (m.get("tools") or [])}
        for name, meta in roles.items():
            tools = meta.get("tools") or []
            if "edit" in tools or "agent" not in tools:
                continue
            with self.subTest(role=name):
                allowed = meta.get("agents")
                self.assertIsNotNone(allowed, f"{name} has agent and no allowlist, so it may run any agent")
                self.assertFalse(set(allowed) & writers, f"{name} may delegate to {set(allowed) & writers}")


class Frontmatter(unittest.TestCase):
    """applyTo '**' versus anything else decides whether a rule loads at all."""

    META = {"description": "d", "name": "n"}

    def setUp(self):
        sync.set_stamp_source(MANIFEST)

    def test_copilot_star_scope_is_resident(self):
        self.assertIn("applyTo: '**'", sync.render_copilot({**self.META, "scope": "*"}, "b", SHA))

    def test_copilot_glob_scope_is_kept(self):
        out = sync.render_copilot({**self.META, "scope": "**/*.py"}, "b", SHA)
        self.assertIn("applyTo: '**/*.py'", out)

    def test_cursor_scoped_rule_has_globs_and_is_not_always(self):
        out = sync.render_cursor({**self.META, "scope": "**/*.py"}, "b", SHA)
        self.assertIn("globs: **/*.py", out)
        self.assertIn("alwaysApply: false", out)

    def test_cursor_always_rule_has_no_globs(self):
        out = sync.render_cursor({**self.META, "scope": "**/*.py", "alwaysApply": True}, "b", SHA)
        self.assertNotIn("globs:", out)
        self.assertIn("alwaysApply: true", out)

    def test_skill_carries_name_and_description(self):
        out = sync.render_skill(self.META, "b", SHA)
        self.assertTrue(out.startswith("---\nname: n\ndescription: >-\n  d\n---\n"))


class SourceSha(unittest.TestCase):
    """The stamp is the last commit touching the inputs. An input it does not
    list changes rendered output without moving the stamp."""

    def stamp_inputs(self) -> list[str]:
        calls = []

        def fake_run(*args, cwd=None):
            calls.append(args)
            return "" if args[:2] == ("git", "status") else SHA

        with mock.patch.object(sync, "run", side_effect=fake_run), \
                mock.patch("builtins.print"):
            sync.source_sha(fetch=False, profile_dir=EXAMPLE)
        log = next(c for c in calls if c[:2] == ("git", "log"))
        return list(log[log.index("--") + 1:])

    def test_every_file_build_plan_reads_is_a_stamp_input(self):
        read: set[Path] = set()
        original = Path.read_text

        def spy(self, *args, **kwargs):
            read.add(self.resolve())
            return original(self, *args, **kwargs)

        with mock.patch.object(Path, "read_text", spy):
            for name, cfg in live_targets().items():
                build_plan(name, cfg, DEFAULTS, SHA, MANIFEST)
            build_plan("example-profile", sync.self_config(MANIFEST), DEFAULTS, SHA, MANIFEST)

        inputs = [(sync.ROOT / p).resolve() for p in self.stamp_inputs()]
        uncovered = sorted(
            p.relative_to(sync.ROOT).as_posix() for p in read
            if p.is_relative_to(sync.ROOT)
            and not any(p == i or p.is_relative_to(i) for i in inputs)
        )
        self.assertTrue(read, "spy saw no reads; the check would pass vacuously")
        self.assertEqual(uncovered, [], "rendered from, but not in the stamp's input list")

    def test_dirty_tree_refuses(self):
        with mock.patch.object(sync, "run", return_value=" M rules/prescriptions.md"):
            with self.assertRaises(sync.SyncError):
                sync.source_sha(fetch=False, profile_dir=EXAMPLE)


class IssueKeys(unittest.TestCase):
    def test_table_matches_manifest(self):
        table = sync.issue_keys(MANIFEST)
        for name, cfg in live_targets().items():
            if cfg.get("key"):
                with self.subTest(target=name):
                    self.assertRegex(table, rf"\| {name}\s+\| `{cfg['key']}-<n>` \|")

    def test_skipped_target_is_omitted(self):
        manifest = {"targets": {"kept": {"key": "k"}, "gone": {"key": "g", "skip": True}}}
        table = sync.issue_keys(manifest)
        self.assertIn("`k-<n>`", table)
        self.assertNotIn("`g-<n>`", table)


class OrphansAndForeign(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        rules = self.repo / ".github" / "instructions"
        rules.mkdir(parents=True)
        (rules / "kept.instructions.md").write_text(f"<!-- {sync.STAMP_MARKER}x -->\n", encoding="utf-8")
        (rules / "old.instructions.md").write_text(f"<!-- {sync.STAMP_MARKER}x -->\n", encoding="utf-8")
        (rules / "mine.instructions.md").write_text("hand written\n", encoding="utf-8")
        hooks = self.repo / ".githooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text(f"# {sync.STAMP_MARKER}x\n", encoding="utf-8")
        self.plan = {".github/instructions/kept.instructions.md": ""}

    def test_stamped_file_outside_the_plan_is_an_orphan(self):
        self.assertEqual(sync.find_orphans(self.repo, self.plan),
                         [".githooks/pre-commit", ".github/instructions/old.instructions.md"])

    def test_a_removed_skill_is_orphaned_from_agents_skills(self):
        """Intent: the copies already rendered there are removed, so a
        factory role in that repo is not handed them."""
        old = self.repo / ".agents" / "skills" / "gone" / "SKILL.md"
        old.parent.mkdir(parents=True)
        old.write_text(f"<!-- {sync.STAMP_MARKER}x -->\n", encoding="utf-8")
        self.assertIn(".agents/skills/gone/SKILL.md", sync.find_orphans(self.repo, self.plan))

    def test_unstamped_file_is_foreign_never_orphan(self):
        self.assertEqual(sync.find_foreign(self.repo, self.plan),
                         [".github/instructions/mine.instructions.md"])

    def test_retired_unstampable_file_is_an_orphan(self):
        """A file that cannot carry a stamp is retired by path."""
        retired = self.repo / sync.RETIRED[0]
        retired.parent.mkdir(parents=True)
        retired.write_text("{}\n", encoding="utf-8")
        self.assertIn(sync.RETIRED[0], sync.find_orphans(self.repo, self.plan))

    def test_the_old_estate_file_is_removed(self):
        """Intent: estate.json is JSON with no stamp, so without this
        every estate repo keeps a copy the ticket tool no longer reads, and nothing says so."""
        old = ".github/scripts/tickets/estate.json"
        (self.repo / old).parent.mkdir(parents=True)
        (self.repo / old).write_text("{}\n", encoding="utf-8")
        self.assertIn(old, sync.find_orphans(self.repo, self.plan))

    def test_retired_path_back_in_the_plan_is_kept(self):
        retired = self.repo / sync.RETIRED[0]
        retired.parent.mkdir(parents=True)
        retired.write_text("{}\n", encoding="utf-8")
        self.assertNotIn(sync.RETIRED[0],
                         sync.find_orphans(self.repo, {**self.plan, sync.RETIRED[0]: ""}))

    def test_absent_retired_path_is_not_reported(self):
        self.assertFalse(set(sync.RETIRED) & set(sync.find_orphans(self.repo, self.plan)))


class CursorHooks(unittest.TestCase):
    """Agent hooks render into .cursor/, merged into one hooks.json, fail closed."""

    GUARD = ('event: shell.before\nkind: permission\n'
             'run: ["{python}", ".cursor/hooks/guard/hook.py"]\ntimeout: 10\n')
    OWNED = GUARD.replace('hook.py"]', 'hook.py", "--owner", "{owner}"]')
    PY = sync.hook_interpreter(sys.executable, os.name == "nt")

    def tree(self, files: dict[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    ON = {"hooks": True}

    def plan(self, files: dict[str, str], cfg: dict | None = None) -> dict[str, str]:
        with mock.patch.object(sync, "HOOKS_DIR", self.tree(files)):
            return build_plan("t", self.ON if cfg is None else cfg, DEFAULTS, SHA, MANIFEST)

    def entries(self, plan: dict[str, str], event: str = "beforeShellExecution") -> list[dict]:
        return json.loads(plan[".cursor/hooks.json"])["hooks"][event]

    def test_hooks_are_off_unless_a_target_opts_in(self):
        """Off until the hook design review; a broken fail-closed
        guard blocked every shell command, the checker included."""
        plan = self.plan({"guard/hook.yaml": self.GUARD, "guard/hook.py": "pass\n"}, {})
        self.assertFalse([k for k in plan if k.startswith(".cursor/hooks")])

    def test_the_shell_edit_hook_is_not_shipped(self):
        """Intent: no-shell-file-edits denied every agent commit, so it is pulled from the
        render until it is fixed; the script stays for its tests."""
        plan = build_plan("t", self.ON, DEFAULTS, SHA, MANIFEST)
        commands = ([e["command"] for e in self.entries(plan)]
                    if ".cursor/hooks.json" in plan else [])
        self.assertNotIn("python3 .cursor/hooks/no-shell-file-edits/hook.py", commands)
        self.assertFalse([k for k in plan if k.startswith(".cursor/hooks/no-shell-file-edits/")])
        self.assertTrue((sync.ROOT / "hooks" / "no-shell-file-edits" / "hook.py").is_file())

    def test_owner_placeholder_is_filled(self):
        plan = self.plan({"guard/hook.yaml": self.OWNED})
        self.assertEqual([e["command"] for e in self.entries(plan)],
                         [f"{self.PY} .cursor/hooks/guard/hook.py --owner {MANIFEST['source']['owner']}"])

    def test_owner_placeholder_without_an_owner_is_refused(self):
        ownerless = {**MANIFEST, "source": {k: v for k, v in MANIFEST["source"].items()
                                            if k != "owner"}}
        with mock.patch.object(sync, "HOOKS_DIR", self.tree({"guard/hook.yaml": self.OWNED})), \
                self.assertRaises(sync.SyncError) as caught:
            build_plan("t", self.ON, DEFAULTS, SHA, ownerless)
        self.assertIn("owner", str(caught.exception))

    def test_the_json_fragment_is_retired_for_hook_yaml(self):
        for source in (p for p in sync.HOOKS_DIR.iterdir() if p.is_dir()):
            with self.subTest(hook=source.name):
                self.assertFalse((source / "config.json").exists())

    def test_hooks_json_carries_the_generated_marker(self):
        """JSON has no comment syntax, so the stamp is a key."""
        config = json.loads(self.plan({"guard/hook.yaml": self.GUARD,
                                       "guard/hook.py": "pass\n"})[".cursor/hooks.json"])
        self.assertIn(f"{MARK}{SHA}", config["_generated"])
        self.assertEqual(config["version"], 1)

    def test_fail_closed_is_rendered_when_the_source_omits_it(self):
        plan = self.plan({"guard/hook.yaml": self.GUARD, "guard/hook.py": "pass\n"})
        self.assertEqual([e["failClosed"] for e in self.entries(plan)], [True])

    def test_fail_open_is_refused(self):
        """Cursor permission hooks fail open by default - hooks/README.md."""
        with self.assertRaises(sync.SyncError) as caught:
            self.plan({"guard/hook.yaml": self.GUARD + "failClosed: false\n"})
        self.assertIn("guard", str(caught.exception))

    def test_an_unknown_key_is_refused(self):
        with self.assertRaises(sync.SyncError) as caught:
            self.plan({"guard/hook.yaml": self.GUARD + "timout: 5\n"})
        self.assertIn("timout", str(caught.exception))

    def test_a_missing_event_kind_or_run_is_refused(self):
        """Intent: the neutral schema's required keys replace event and command."""
        for dropped in ("event", "kind", "run"):
            body = "".join(line + "\n" for line in self.GUARD.splitlines()
                           if not line.startswith(dropped))
            with self.subTest(dropped=dropped), self.assertRaises(sync.SyncError):
                self.plan({"guard/hook.yaml": body})

    def test_hooks_on_one_event_merge_in_name_order(self):
        other = self.GUARD.replace("guard", "another")
        plan = self.plan({"guard/hook.yaml": self.GUARD, "another/hook.yaml": other})
        self.assertEqual([e["command"] for e in self.entries(plan)],
                         [f"{self.PY} .cursor/hooks/another/hook.py",
                          f"{self.PY} .cursor/hooks/guard/hook.py"])

    def test_a_directory_without_hook_yaml_is_not_a_cursor_hook(self):
        """hooks/no-secret-defaults is a git hook and CI check, not an agent hook."""
        plan = self.plan({"guard/hook.yaml": self.GUARD, "gitonly/check.py": "pass\n"})
        self.assertFalse([k for k in plan if k.startswith(".cursor/hooks/gitonly/")])

    def test_no_hook_sources_render_no_hooks_json(self):
        self.assertFalse([k for k in self.plan({}) if k.startswith(".cursor/hooks")])

    def test_the_manifest_switch_turns_hooks_off(self):
        plan = self.plan({"guard/hook.yaml": self.GUARD, "guard/hook.py": "pass\n"},
                         {"hooks": False})
        self.assertFalse([k for k in plan if k.startswith(".cursor/hooks")])

    def test_a_stale_marked_hooks_json_is_an_orphan(self):
        repo = self.tree({".cursor/hooks.json":
                          json.dumps({"_generated": f"{sync.STAMP_MARKER}x"}) + "\n"})
        self.assertIn(".cursor/hooks.json", sync.find_orphans(repo, {}))

    def test_an_unmarked_hooks_json_is_foreign(self):
        repo = self.tree({".cursor/hooks.json": '{"version": 1, "hooks": {}}\n'})
        self.assertIn(".cursor/hooks.json", sync.find_foreign(repo, {}))

    def test_an_orphaned_hook_script_is_found(self):
        repo = self.tree({".cursor/hooks/old/hook.py": f"# {sync.STAMP_MARKER}x\n"})
        self.assertIn(".cursor/hooks/old/hook.py", sync.find_orphans(repo, {}))

    def test_emit_refuses_to_overwrite_an_unmarked_hooks_json(self):
        """A hand-owned hooks.json is the repo's own guard; overwriting it drops that guard."""
        original = '{"version": 1, "hooks": {}}\n'
        repo = self.tree({".cursor/hooks.json": original})
        with self.assertRaises(sync.SyncError) as caught, mock.patch("builtins.print"):
            sync.emit(repo, {".cursor/hooks.json": "{}\n"}, True,
                      ident={"name": "n", "email": "e@example.com"})
        self.assertIn(".cursor/hooks.json", str(caught.exception))
        self.assertEqual((repo / ".cursor/hooks.json").read_text(encoding="utf-8"), original)


class HookSchema(unittest.TestCase):
    """Intent: the tool-neutral schema, hooks/README.md "Tool-neutral schema": run: is an argument list, kind: sets the fail mode,
    events are neutral, and a hook whose event a targeted tool lacks is refused."""

    ON = CursorHooks.ON
    PY = CursorHooks.PY
    tree = CursorHooks.tree
    plan = CursorHooks.plan
    entries = CursorHooks.entries

    def hook(self, **override) -> str:
        spec = {"event": "shell.before", "kind": "permission",
                "run": ["{python}", ".cursor/hooks/guard/hook.py"], "timeout": 10, **override}
        return yaml.safe_dump({k: v for k, v in spec.items() if v is not None})

    def refused(self, body: str) -> str:
        with self.assertRaises(sync.SyncError) as caught:
            self.plan({"guard/hook.yaml": body, "guard/hook.py": "pass\n"})
        return str(caught.exception)

    def test_run_must_be_a_list(self):
        """Intent: DECISIONS.md, "Rejected: a command: string" - quoting a string per shell is
        a problem solved per machine."""
        message = self.refused(self.hook(run="{python} .cursor/hooks/guard/hook.py"))
        self.assertIn("run: must be a list", message)
        self.assertIn("hooks/guard/hook.yaml", message)

    def test_every_run_entry_must_be_a_string(self):
        self.assertIn("run: entry 2 is not a string",
                      self.refused(self.hook(run=["{python}", "x.py", 10])))

    def test_an_empty_run_is_refused(self):
        self.assertIn("run: is empty", self.refused(self.hook(run=[])))

    def test_kind_must_be_permission_or_observer(self):
        message = self.refused(self.hook(kind="guard"))
        self.assertIn("guard", message)
        self.assertIn("permission", message)
        self.assertIn("observer", message)

    def test_a_fail_closed_key_is_refused(self):
        """Intent: DECISIONS.md, "Rejected: a per-hook fail: field" - a mode derived from the
        kind of hook cannot be set wrong."""
        message = self.refused(self.hook(failClosed=True))
        self.assertIn("['failClosed']", message)
        self.assertIn("the fail mode comes from kind:", message)

    def test_the_old_command_key_is_refused_naming_the_new_keys(self):
        """Intent: replace the old schema outright, and
        refuse an old-shape file with a message naming the new keys."""
        message = self.refused('event: beforeShellExecution\ncommand: "{python} x.py"\n')
        self.assertIn("command", message)
        self.assertIn("run", message)
        self.assertIn("kind", message)

    def test_an_unknown_neutral_event_is_refused(self):
        message = self.refused(self.hook(event="beforeShellExecution"))
        self.assertIn("beforeShellExecution", message)
        self.assertIn("shell.before", message)

    def test_an_unknown_tool_is_refused(self):
        self.assertIn("vim", self.refused(self.hook(tools=["cursor", "vim"])))

    def test_an_event_a_targeted_tool_lacks_is_refused(self):
        """Intent: DECISIONS.md, "Rejected: skipping a hook silently for a tool that lacks its
        event" - that renders as guarded with nothing guarding. Copilot's events are
        declared now, so the refusal is real before its adapter renders."""
        message = self.refused(self.hook(event="reply.after", kind="observer"))
        self.assertIn("reply.after", message)
        self.assertIn("copilot", message)
        self.assertIn("tools", message)

    def test_tools_can_leave_out_the_tool_that_lacks_the_event(self):
        plan = self.plan({"guard/hook.yaml": self.hook(event="reply.after", kind="observer",
                                                       tools=["cursor"])})
        self.assertEqual(len(self.entries(plan, "afterAgentResponse")), 1)

    def test_a_hook_for_another_tool_renders_nothing_for_cursor(self):
        plan = self.plan({"guard/hook.yaml": self.hook(tools=["copilot"]),
                          "guard/hook.py": "pass\n"})
        self.assertFalse([k for k in plan if k.startswith(".cursor/hooks")])

    def test_a_permission_hook_fails_closed_and_an_observer_fails_open(self):
        """Intent: hooks/README.md - "A permission hook fails closed, an observer fails open.
        There is no per-hook override." Written out either way."""
        plan = self.plan({"guard/hook.yaml": self.hook(),
                          "watch/hook.yaml": self.hook(kind="observer", event="file.write.after",
                                                       run=["{python}", "w.py"])})
        self.assertEqual([e["failClosed"] for e in self.entries(plan)], [True])
        self.assertEqual([e["failClosed"] for e in self.entries(plan, "afterFileEdit")], [False])

    def test_neutral_events_map_to_cursors(self):
        """Intent: hooks/README.md, the neutral event table. file.write.before renders, unverified live until the hook that uses it."""
        for neutral, native in (("session.start", "sessionStart"),
                                ("shell.before", "beforeShellExecution"),
                                ("file.write.before", "preToolUse"),
                                ("file.write.after", "afterFileEdit"),
                                ("reply.after", "afterAgentResponse"),
                                ("turn.end", "stop")):
            with self.subTest(neutral=neutral):
                plan = self.plan({"guard/hook.yaml": self.hook(event=neutral, tools=["cursor"])})
                self.assertEqual(len(self.entries(plan, native)), 1)

    def test_a_pre_write_hook_carries_cursors_write_matcher(self):
        plan = self.plan({"guard/hook.yaml": self.hook(event="file.write.before")})
        self.assertEqual([e.get("matcher") for e in self.entries(plan, "preToolUse")], ["Write"])

    def test_an_argument_needing_quotes_is_quoted_for_the_hook_shell(self):
        """Intent: hooks/README.md - each tool's adapter quotes run:; Cursor joins it for the
        machine's hook shell. PowerShell single-quotes and doubles a quote; POSIX as shlex."""
        run = ["{python}", "x.py", "a b", "it's"]
        self.assertEqual(sync.hook_command(run, "w", r"C:\py\python.exe", windows=True),
                         "& \"C:\\py\\python.exe\" x.py 'a b' 'it''s'")
        self.assertEqual(sync.hook_command(run, "w", "/usr/bin/python3", windows=False),
                         "'/usr/bin/python3' x.py 'a b' 'it'\"'\"'s'")

    def test_the_owner_fills_inside_an_argument(self):
        plan = self.plan({"guard/hook.yaml": self.hook(
            run=["{python}", "x.py", "--owner={owner}"])})
        self.assertEqual([e["command"] for e in self.entries(plan)],
                         [f"{self.PY} x.py --owner={MANIFEST['source']['owner']}"])

    def test_the_library_renders_beside_the_hooks(self):
        """Intent: hooks/lib/ renders to
        .cursor/hooks/lib/, where a hook finds it beside its own folder."""
        plan = self.plan({"guard/hook.yaml": self.hook(), "guard/hook.py": "pass\n",
                          "lib/hookio.py": "pass\n"})
        self.assertIn(".cursor/hooks/lib/hookio.py", plan)
        self.assertNotIn(".cursor/hooks/lib/hook.yaml", plan)

    def test_no_hooks_render_no_library(self):
        plan = self.plan({"lib/hookio.py": "pass\n"})
        self.assertFalse([k for k in plan if k.startswith(".cursor/hooks")])

    def test_the_real_library_ships_with_a_hook(self):
        guard = {"guard/hook.yaml": CursorHooks.GUARD, "guard/hook.py": "pass\n",
                 "lib/hookio.py": (sync.HOOKS_DIR / "lib" / "hookio.py").read_text(encoding="utf-8")}
        self.assertIn(".cursor/hooks/lib/hookio.py", self.plan(guard))


class HookInterpreter(unittest.TestCase):
    """Intent: a Windows checkout's first python3 was an sh shim, no hook could start, and
    every shell command was denied. So: the interpreter running sync.py,
    absolute and quoted, in the form the OS's hook shell needs."""

    COMMAND = ["{python}", ".cursor/hooks/guard/hook.py", "--owner", "o"]

    def test_the_windows_form_calls_a_quoted_path_with_a_space(self):
        """Cursor runs a Windows hook through PowerShell, which calls a quoted path only with &."""
        python = r"C:\Program Files\Python314\python.exe"
        self.assertEqual(sync.hook_command(self.COMMAND, "w", python, windows=True),
                         f'& "{python}" .cursor/hooks/guard/hook.py --owner o')

    def test_the_posix_form_single_quotes_the_path(self):
        self.assertEqual(sync.hook_command(self.COMMAND, "w", "/opt/my python/bin/python3",
                                           windows=False),
                         "'/opt/my python/bin/python3' .cursor/hooks/guard/hook.py --owner o")
        self.assertEqual(sync.hook_interpreter("/opt/it's/python3", windows=False),
                         "'/opt/it'\\''s/python3'")

    def test_a_bare_interpreter_is_refused(self):
        for bare in ("python", "python3", "py", "python3.exe", "Python"):
            with self.subTest(bare=bare), self.assertRaises(sync.SyncError) as caught:
                sync.hook_command([bare, ".cursor/hooks/guard/hook.py"], "hooks/guard/hook.yaml",
                                  "/usr/bin/python3", windows=False)
            self.assertIn(bare, str(caught.exception))
            self.assertIn("hooks/guard/hook.yaml", str(caught.exception))

    def test_the_placeholder_must_open_the_command(self):
        """PowerShell's & is only the call operator at the start of a command."""
        with self.assertRaises(sync.SyncError):
            sync.hook_command(["env", "{python}", "x.py"], "w", "/usr/bin/python3", windows=False)

    def test_a_virtual_environment_is_refused(self):
        """A hook rendered with a venv's interpreter breaks when that venv is removed."""
        guard = {"guard/hook.yaml": CursorHooks.GUARD, "guard/hook.py": "pass\n"}
        hooks = CursorHooks.tree(self, guard)
        with mock.patch.object(sync, "HOOKS_DIR", hooks), \
                mock.patch.object(sync.sys, "prefix", str(Path(sync.sys.base_prefix) / "venv")), \
                self.assertRaises(sync.SyncError) as caught:
            build_plan("t", {"hooks": True}, DEFAULTS, SHA, MANIFEST)
        self.assertIn("virtual environment", str(caught.exception))

    def test_a_windows_folder_seen_from_wsl_is_recognised(self):
        for path, platform, expected in (("/mnt/c/Users/me/repo", "linux", True),
                                         ("/mnt/D/repo", "linux", True),
                                         ("/mnt/data/repo", "linux", False),
                                         ("/home/me/repo", "linux", False),
                                         ("/mnt/c/Users/me/repo", "win32", False)):
            with self.subTest(path=path, platform=platform):
                self.assertEqual(sync.on_windows_mount(path, platform), expected)

    def test_emit_refuses_hooks_json_into_a_windows_folder_from_wsl(self):
        """A WSL interpreter path written into a Windows checkout cannot launch there."""
        repo = CursorHooks.tree(self, {})
        with mock.patch.object(sync, "on_windows_mount", return_value=True), \
                mock.patch("builtins.print"), self.assertRaises(sync.SyncError) as caught:
            sync.emit(repo, {".cursor/hooks.json": "{}\n"}, True,
                      ident={"name": "n", "email": "e@example.com"})
        self.assertIn("/mnt/", str(caught.exception))
        self.assertFalse((repo / ".cursor/hooks.json").exists())

class HookLaunchCheck(unittest.TestCase):
    """Intent: a rendered interpreter that cannot start locks the agent out: every
    fail-closed hook denies every action, and the agent cannot repair hooks.json itself.
    So before writing, sync.py launches each interpreter the
    way Cursor will, and refuses rather than replace a working file."""

    WIN = r'& "C:\Program Files\Python314\python.exe" .cursor/hooks/guard/hook.py --owner o'
    POSIX = "'/usr/bin/python3' .cursor/hooks/guard/hook.py --owner o"
    IDENT = {"name": "n", "email": "e@example.com"}
    OLD = '{"_generated": "' + sync.STAMP_MARKER + 'old", "version": 1, "hooks": {}}\n'

    def setUp(self):
        self.windows = os.name == "nt"
        self.command = self.WIN if self.windows else self.POSIX
        self.repo = CursorHooks.tree(self, {".cursor/hooks.json": self.OLD})

    def hooks_json(self, command: str) -> str:
        return json.dumps({"_generated": f"{sync.STAMP_MARKER}{SHA}", "version": 1,
                           "hooks": {"beforeShellExecution": [
                               {"command": command, "failClosed": True}]}}, indent=2) + "\n"

    @contextlib.contextmanager
    def launches(self, **behaviour):
        """subprocess.run mocked; git's own calls in emit are patched out, so every call
        left is the launch check's."""
        ran = mock.Mock(**behaviour)
        with mock.patch.object(sync.subprocess, "run", ran), \
                mock.patch.object(sync.shutil, "which", return_value=None), \
                mock.patch.object(sync, "activate_hooks"), \
                mock.patch.object(sync, "ensure_identity"), \
                mock.patch("builtins.print"):
            yield ran

    def failed(self, code: int = 1, output: str = "the term is not recognized"):
        return {"return_value": subprocess.CompletedProcess([], code, "", output)}

    def test_the_probe_replaces_the_script_with_a_no_op(self):
        """Intent: "launches each rendered command's interpreter the way
        Cursor will, with a no-op in place of the script"."""
        self.assertEqual(sync.launch_probe(self.WIN),
                         r'& "C:\Program Files\Python314\python.exe" -c pass')
        self.assertEqual(sync.launch_probe(self.POSIX), "'/usr/bin/python3' -c pass")

    def test_windows_tries_powershell_and_pwsh_when_installed(self):
        """Intent: on Windows the check runs under powershell.exe, and
        under pwsh when installed."""
        with mock.patch.object(sync.shutil, "which", return_value=r"C:\tools\pwsh.exe"):
            shells = sync.hook_shells(windows=True)
        self.assertEqual([argv[0] for argv in shells], ["powershell.exe", r"C:\tools\pwsh.exe"])

    def test_without_pwsh_only_powershell_is_tried(self):
        """Intent: with pwsh absent only powershell.exe is tried."""
        with mock.patch.object(sync.shutil, "which", return_value=None):
            shells = sync.hook_shells(windows=True)
        self.assertEqual([argv[0] for argv in shells], ["powershell.exe"])

    def test_elsewhere_the_hook_runs_under_sh(self):
        """Intent: "elsewhere under sh"."""
        self.assertEqual([argv[0] for argv in sync.hook_shells(windows=False)], ["sh"])

    def test_an_interpreter_that_does_not_start_is_refused_and_nothing_is_written(self):
        """Intent: refuse, name the command, and leave hooks.json
        unwritten; the refusal names the shell, the exit code and its output."""
        plan = {".cursor/hooks.json": self.hooks_json(self.command), "AGENTS.md": "x\n"}
        with self.launches(**self.failed(1, "the term is not recognized")), \
                self.assertRaises(sync.SyncError) as caught:
            sync.emit(self.repo, plan, True, ident=self.IDENT)
        message = str(caught.exception)
        shell = sync.hook_shells(self.windows)[0][0]
        for expected in (self.command, shell, "exit code 1", "the term is not recognized"):
            self.assertIn(expected, message)
        self.assertEqual((self.repo / ".cursor/hooks.json").read_text(encoding="utf-8"), self.OLD)
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_a_launch_that_cannot_run_or_hangs_is_refused(self):
        """Intent: "Any failure refuses"; every subprocess gets an
        explicit timeout."""
        plan = {".cursor/hooks.json": self.hooks_json(self.command)}
        for error in (FileNotFoundError("no such shell"),
                      subprocess.TimeoutExpired("sh", 30)):
            with self.subTest(error=type(error).__name__), \
                    self.launches(side_effect=error), self.assertRaises(sync.SyncError):
                sync.emit(self.repo, plan, True, ident=self.IDENT)
            self.assertEqual((self.repo / ".cursor/hooks.json").read_text(encoding="utf-8"),
                             self.OLD)

    def test_an_interpreter_that_starts_is_written(self):
        """Intent: an interpreter that starts is written."""
        content = self.hooks_json(self.command)
        ok = subprocess.CompletedProcess([], 0, "", "")
        with self.launches(return_value=ok) as ran:
            sync.emit(self.repo, {".cursor/hooks.json": content}, True, ident=self.IDENT)
        self.assertEqual((self.repo / ".cursor/hooks.json").read_text(encoding="utf-8"), content)
        argv = ran.call_args.args[0]
        self.assertEqual(argv[-1], sync.launch_probe(self.command))
        self.assertIn("timeout", ran.call_args.kwargs)

    def test_with_hooks_off_no_launch_runs(self):
        """Intent: with hooks off, no check runs."""
        plan = build_plan("t", {"hooks": False}, DEFAULTS, SHA, MANIFEST)
        self.assertNotIn(".cursor/hooks.json", plan)
        with self.launches() as ran:
            sync.emit(self.repo, plan, True, ident=self.IDENT)
        ran.assert_not_called()

    def test_check_mode_runs_no_launch(self):
        """Intent: "--check never writes, so it runs no launch check"."""
        with self.launches() as ran:
            sync.emit(self.repo, {".cursor/hooks.json": self.hooks_json(self.command)}, False,
                      ident=self.IDENT)
        ran.assert_not_called()


class HooksJsonLocal(unittest.TestCase):
    """Intent: hooks.json names this machine's interpreter, so it cannot be
    shared: ignored and untracked in every target, and outside --check."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        git("init", "--quiet", "-b", "main", str(self.repo), cwd=self.repo)
        configure(self.repo)

    def tracked(self) -> bool:
        return bool(git("ls-files", "--", ".cursor/hooks.json", cwd=self.repo).strip())

    def commit_hooks_json(self) -> None:
        path = self.repo / ".cursor" / "hooks.json"
        path.parent.mkdir()
        path.write_text("{}\n", encoding="utf-8", newline="\n")
        git("add", "-A", cwd=self.repo)
        git("commit", "--quiet", "-m", "tracked hooks.json", cwd=self.repo)

    def test_hooks_json_is_a_local_probe_not_a_tracked_one(self):
        self.assertNotIn(".cursor/hooks.json", sync.CURSOR_PROBES_TRACKED)
        self.assertIn(".cursor/hooks.json", sync.CURSOR_PROBES_LOCAL)
        self.assertNotIn("!.cursor/hooks.json", sync.CURSOR_RULES)

    def test_write_untracks_a_tracked_hooks_json_and_keeps_the_file(self):
        self.commit_hooks_json()
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_hooks_local(self.repo, write=True), 1)
        self.assertFalse(self.tracked())
        self.assertTrue((self.repo / ".cursor" / "hooks.json").is_file())

    def test_check_reports_a_tracked_hooks_json_without_untracking(self):
        self.commit_hooks_json()
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_hooks_local(self.repo, write=False), 1)
        self.assertTrue(self.tracked())

    def test_an_untracked_hooks_json_is_no_change(self):
        self.assertEqual(sync.ensure_hooks_local(self.repo, write=True), 0)

    def test_the_old_re_include_is_replaced_so_hooks_json_is_ignored(self):
        """Every target's .gitignore carries the old !.cursor/hooks.json; left in place it
        keeps the file tracked and the probe check refuses."""
        old = ("# Cursor: rendered output is tracked.\n.cursor/*\n!.cursor/rules/\n"
               "!.cursor/skills/\n!.cursor/hooks/\n!.cursor/hooks.json\n")
        (self.repo / ".gitignore").write_text(old, encoding="utf-8", newline="\n")
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_cursor_tracked(self.repo, write=True), 1)
        text = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("!.cursor/hooks.json", text)
        self.assertTrue(sync._git_ignores(self.repo, ".cursor/hooks.json"))
        self.assertFalse(sync._git_ignores(self.repo, ".cursor/hooks/guard/hook.py"))

    def test_the_re_include_is_replaced_while_hooks_json_is_still_tracked(self):
        """A profile's own first render: check-ignore calls a tracked file not ignored, which
        read as a mis-ignore and refused, restoring the old .gitignore."""
        self.commit_hooks_json()
        old = ".cursor/*\n!.cursor/rules/\n!.cursor/skills/\n!.cursor/hooks/\n!.cursor/hooks.json\n"
        (self.repo / ".gitignore").write_text(old, encoding="utf-8", newline="\n")
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_cursor_tracked(self.repo, write=True), 1)
        self.assertNotIn("!.cursor/hooks.json",
                         (self.repo / ".gitignore").read_text(encoding="utf-8"))

    def test_an_ignored_hooks_json_is_not_a_hidden_plan_path(self):
        (self.repo / ".gitignore").write_text(".cursor/*\n!.cursor/hooks/\n",
                                              encoding="utf-8", newline="\n")
        self.assertEqual(sync.hidden_plan_paths(self.repo, {".cursor/hooks.json": "",
                                                            ".cursor/hooks/g/hook.py": ""}), [])

    def test_check_compares_without_hooks_json(self):
        """--check passes on a checkout with no hooks.json: the file is never compared."""
        hooks = CursorHooks.tree(self, {"guard/hook.yaml": CursorHooks.GUARD,
                                        "guard/hook.py": "pass\n"})
        real = sync.self_config
        for patcher in (mock.patch.object(sync, "HOOKS_DIR", hooks),
                        mock.patch.object(sync, "self_config",
                                          lambda manifest: {**real(manifest), "hooks": True})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertIn(".cursor/hooks.json",
                      build_plan("example-profile", sync.self_config(MANIFEST), DEFAULTS, SHA,
                                      MANIFEST),
                      "the self plan renders no hooks.json, so this test proves nothing")
        compared: list[dict] = []

        def recorder(target, plan, write, *, ident):
            compared.append(dict(plan))
            return 0

        argv = ["sync.py", "--profile", str(EXAMPLE), "--self", "--check", "--no-fetch"]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sync, "emit", recorder), \
                mock.patch.object(sync, "source_sha", return_value=SHA), \
                contextlib.redirect_stdout(io.StringIO()):
            sync.main()
        self.assertTrue(compared, "emit was never called")
        self.assertNotIn(".cursor/hooks.json", compared[0])


class ScratchIgnored(unittest.TestCase):
    """Intent: working files go in scratch/, not the system temp directory; one repo of
    eight did not ignore scratch/, so following the rule there would commit the files."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True, env=env,
                       capture_output=True, timeout=60)

    def ignored(self) -> bool:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        return subprocess.run(["git", "check-ignore", "-q", "scratch/x.ps1"], cwd=self.repo,
                              env=env, timeout=60).returncode == 0

    def test_write_adds_the_ignore_and_keeps_existing_lines(self):
        (self.repo / ".gitignore").write_text("node_modules/", encoding="utf-8")
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_scratch_ignored(self.repo, write=True), 1)
        self.assertTrue(self.ignored())
        self.assertTrue((self.repo / ".gitignore").read_text(encoding="utf-8")
                        .startswith("node_modules/\n"))

    def test_check_reports_without_writing(self):
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_scratch_ignored(self.repo, write=False), 1)
        self.assertFalse((self.repo / ".gitignore").exists())

    def test_already_ignored_is_no_change(self):
        (self.repo / ".gitignore").write_text("scratch/\n", encoding="utf-8")
        before = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(sync.ensure_scratch_ignored(self.repo, write=True), 0)
        self.assertEqual((self.repo / ".gitignore").read_text(encoding="utf-8"), before)

    def test_running_twice_adds_the_line_once(self):
        with mock.patch("builtins.print"):
            sync.ensure_scratch_ignored(self.repo, write=True)
            self.assertEqual(sync.ensure_scratch_ignored(self.repo, write=True), 0)
        self.assertEqual((self.repo / ".gitignore").read_text(encoding="utf-8")
                         .count("scratch/"), 1)


class PycacheIgnored(unittest.TestCase):
    """Intent: running a rendered script left .github/scripts/tickets/__pycache__/ in a
    repo whose .gitignore was the only one of seven without a rule, and its next rollout
    failed on a dirty tree (2026-09-30)."""

    NESTED = ".github/scripts/tickets/__pycache__/edit.cpython-311.pyc"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True, env=env,
                       capture_output=True, timeout=60)

    def ignored(self) -> bool:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        return subprocess.run(["git", "check-ignore", "-q", self.NESTED], cwd=self.repo,
                              env=env, timeout=60).returncode == 0

    def test_write_adds_the_ignore_and_keeps_existing_lines(self):
        (self.repo / ".gitignore").write_text("node_modules/", encoding="utf-8")
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_pycache_ignored(self.repo, write=True), 1)
        self.assertTrue(self.ignored())
        self.assertTrue((self.repo / ".gitignore").read_text(encoding="utf-8")
                        .startswith("node_modules/\n"))

    def test_check_reports_without_writing(self):
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_pycache_ignored(self.repo, write=False), 1)
        self.assertFalse((self.repo / ".gitignore").exists())

    def test_an_existing_pyc_rule_already_counts(self):
        """Six targets ignore bytecode with rules of their own; none of them is touched."""
        (self.repo / ".gitignore").write_text("*.py[cod]\n", encoding="utf-8")
        before = (self.repo / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(sync.ensure_pycache_ignored(self.repo, write=True), 0)
        self.assertEqual((self.repo / ".gitignore").read_text(encoding="utf-8"), before)

    def test_running_twice_adds_the_line_once(self):
        with mock.patch("builtins.print"):
            sync.ensure_pycache_ignored(self.repo, write=True)
            self.assertEqual(sync.ensure_pycache_ignored(self.repo, write=True), 0)
        self.assertEqual((self.repo / ".gitignore").read_text(encoding="utf-8")
                         .count("__pycache__/"), 1)


class CursorTracked(unittest.TestCase):
    """Intent: track the rendered Cursor output. Eight of nine estate repos carry a
    hand-added .cursor/ ignore from 2026-09-18. Only what sync renders is re-included:
    two repos already hold a local .cursor/cli.json, and
    .cursor/mcp.json is where an MCP credential lives."""

    RENDERED = (".cursor/rules/estate.mdc", ".cursor/skills/x/SKILL.md",
                ".cursor/hooks/guard/hook.py")
    LOCAL = (".cursor/cli.json", ".cursor/mcp.json", ".cursor/hooks.json")
    SEPT_18 = ".cursor/\n"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True, env=clean_env(),
                       capture_output=True, timeout=60)

    def ignored(self, rel: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", rel], cwd=self.repo,
                              env=clean_env(), timeout=60).returncode == 0

    def gitignore(self) -> str:
        return (self.repo / ".gitignore").read_text(encoding="utf-8")

    def write(self, text: str) -> None:
        (self.repo / ".gitignore").write_text(text, encoding="utf-8", newline="\n")

    def test_write_replaces_the_blanket_ignore(self):
        self.write("node_modules/\n\n" + self.SEPT_18 + "\ndist/\n")
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_cursor_tracked(self.repo, write=True), 1)
        for rel in self.RENDERED:
            self.assertFalse(self.ignored(rel), f"{rel} is still ignored")
        self.assertTrue(self.ignored("node_modules/x") and self.ignored("dist/x"),
                        "an unrelated rule was lost")

    def test_local_cursor_state_stays_ignored(self):
        self.write(self.SEPT_18)
        with mock.patch("builtins.print"):
            sync.ensure_cursor_tracked(self.repo, write=True)
        for rel in self.LOCAL:
            self.assertTrue(self.ignored(rel), f"{rel} would be committed")

    def test_a_bare_line_without_the_comment_is_replaced(self):
        """One repo's line sits in an 'Editor / IDE' block with no sync comment."""
        self.write("# Editor / IDE\n.cursor/\n.vscode/\n")
        with mock.patch("builtins.print"):
            sync.ensure_cursor_tracked(self.repo, write=True)
        self.assertFalse(self.ignored(".cursor/rules/estate.mdc"))
        self.assertTrue(self.ignored(".vscode/settings.json"), "the neighbouring rule was lost")
        self.assertIn("# Editor / IDE\n", self.gitignore())

    def test_no_gitignore_gets_the_local_state_rule(self):
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_cursor_tracked(self.repo, write=True), 1)
        self.assertTrue(self.ignored(".cursor/mcp.json"))
        self.assertFalse(self.ignored(".cursor/rules/estate.mdc"))

    def test_check_reports_without_writing(self):
        self.write(self.SEPT_18)
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_cursor_tracked(self.repo, write=False), 1)
        self.assertEqual(self.gitignore(), self.SEPT_18)

    def test_running_twice_changes_nothing_the_second_time(self):
        self.write(self.SEPT_18)
        with mock.patch("builtins.print"):
            sync.ensure_cursor_tracked(self.repo, write=True)
            after = self.gitignore()
            self.assertEqual(sync.ensure_cursor_tracked(self.repo, write=True), 0)
        self.assertEqual(self.gitignore(), after)

    def test_a_rule_sync_does_not_own_still_hiding_rendered_output_refuses(self):
        """A pattern sync cannot safely rewrite must stop the run, not pass as fixed."""
        (self.repo / ".gitignore").write_bytes(b"dist/\r\n.cursor*\r\n")
        with mock.patch("builtins.print"), self.assertRaises(sync.SyncError) as caught:
            sync.ensure_cursor_tracked(self.repo, write=True)
        self.assertIn(".cursor/rules/", str(caught.exception))
        self.assertEqual((self.repo / ".gitignore").read_bytes(), b"dist/\r\n.cursor*\r\n",
                         "a refused run left .gitignore changed")


class ProfileLoader(unittest.TestCase):
    """profile.yaml replaces manifest.yaml, and one function locates it. The core never
    computes a profile path anywhere else, so a second reader cannot resolve a different file -
    the failure where a writer and a reader disagreed silently."""

    def tmp_dir(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_no_argument_refuses_asking_for_a_profile(self):
        """Intent: the core is never a profile, so no --profile is a refusal naming the
        flag rather than a render of the core's own folder."""
        with self.assertRaises(sync.SyncError) as ctx:
            sync.resolve_profile(None)
        self.assertIn("--profile", str(ctx.exception))

    def test_an_explicit_directory_resolves_to_itself(self):
        folder = self.tmp_dir()
        (folder / "profile.yaml").write_text("source: {}\n", encoding="utf-8")
        self.assertEqual(sync.resolve_profile(folder), folder.resolve())

    def test_a_directory_without_profile_yaml_is_refused_naming_it(self):
        """Intent: prescriptions - missing means abort. A guessed fallback would render the wrong
        estate without saying so."""
        folder = self.tmp_dir()
        with self.assertRaises(sync.SyncError) as ctx:
            sync.resolve_profile(folder)
        self.assertIn(str(folder), str(ctx.exception))

    def test_an_unknown_top_level_key_fails_naming_the_key_and_the_file(self):
        """Intent: an unknown key fails with the key named, so a typo cannot
        be silently ignored."""
        folder = self.tmp_dir()
        (folder / "profile.yaml").write_text("source: {}\nno_such_key: 1\n", encoding="utf-8")
        with self.assertRaises(sync.SyncError) as ctx:
            sync.load_profile(folder)
        self.assertIn("no_such_key", str(ctx.exception))
        self.assertIn("profile.yaml", str(ctx.exception))

    def test_the_example_profile_loads_and_carries_targets(self):
        profile = sync.load_profile(sync.resolve_profile(EXAMPLE))
        self.assertTrue(profile.get("targets"))

    def test_identity_is_a_top_level_key(self):
        """Intent: source.identity becomes identity."""
        profile = sync.load_profile(sync.resolve_profile(EXAMPLE))
        self.assertNotIn("identity", profile.get("source") or {})
        self.assertEqual(sync.identity(profile),
                         {"name": "Example Owner", "email": "owner@example.invalid"})

    def test_sync_names_manifest_yaml_nowhere_in_its_source(self):
        """Intent: a search for manifest.yaml in source returns nothing
        outside history. A reader still naming it is a reader that was not moved."""
        text = (sync.ROOT / "sync.py").read_text(encoding="utf-8")
        self.assertNotIn("manifest.yaml", text)


class ProfileSeeds(unittest.TestCase):
    """A profile adds seeds under <profile>/seeds/, merged with the core's own. A name
    used by both is refused, and two seeds landing on one destination path are refused too."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)

    def seed(self, rel: str, text: str) -> Path:
        path = self.profile / "seeds" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def plan(self, cfg: dict | None = None, defaults: dict | None = None) -> dict[str, str]:
        manifest = {**MANIFEST, "features": lock_all_on(self.profile)}
        return build_plan("t", cfg or {}, defaults or DEFAULTS, SHA, manifest,
                               profile_dir=self.profile)

    def test_a_plan_needs_a_profile_directory(self):
        """Intent: the core is never a profile, so a plan built with no
        profile directory is an error, not a render of the core's own folder."""
        with self.assertRaises(TypeError):
            sync.build_plan("t", {}, DEFAULTS, SHA, MANIFEST)

    def test_a_profile_skill_is_rendered_into_both_roots(self):
        self.seed("skills/profile-only/procedure.md",
                  "---\nname: profile-only\ndescription: d\n---\nbody\n")
        plan = self.plan()
        self.assertIn(".cursor/skills/profile-only/SKILL.md", plan)
        self.assertIn(".github/skills/profile-only/SKILL.md", plan)

    def test_a_profile_rule_is_rendered_when_the_defaults_name_it(self):
        self.seed("rules/spec-profile-only.md",
                  "---\nid: profile-only\ndescription: d\nscope: '*'\n---\nbody\n")
        defaults = {**DEFAULTS, "tier2": [*DEFAULTS["tier2"], "profile-only"]}
        self.assertIn(".cursor/rules/profile-only.mdc", self.plan(defaults=defaults))

    def test_a_profile_prompt_agent_and_githook_are_rendered(self):
        self.seed("context/profile-only.prompt.md", "---\ndescription: d\n---\nbody\n")
        self.seed("agents/profile-only/definition.md",
                  "---\nname: profile-only\ndescription: d\n---\nbody\n")
        self.seed("githooks/gates/profile-only.sh", "#!/usr/bin/env bash\nexit 0\n")
        plan = self.plan()
        self.assertIn(".github/prompts/profile-only.prompt.md", plan)
        self.assertIn(".github/agents/profile-only.agent.md", plan)
        self.assertIn(".githooks/gates/profile-only.sh", plan)

    def test_a_profile_workflow_action_and_script_are_rendered(self):
        """Intent: the core renders a profile's CI and scripts, so tooling the core
        does not own, such as a ticket client, can ship from the profile instead of the core."""
        self.seed("workflows/profile-only.yml", "on: push\njobs: {}\n")
        self.seed("actions/profile-only/action.yml", "runs:\n  using: composite\n  steps: []\n")
        self.seed("actions/profile-only/run.sh", "#!/usr/bin/env bash\nexit 0\n")
        self.seed("actions/profile-only/check.py", "print('ok')\n")
        self.seed("scripts/profile_tool.py", "print('ok')\n")
        self.seed("scripts/profile_pkg/mod.py", "x = 1\n")
        self.seed("scripts/profile_pkg/data.json", "{}\n")
        self.seed("scripts/profile_pkg/__pycache__/mod.cpython-314.pyc", "junk")
        plan = self.plan()
        for path in (".github/workflows/profile-only.yml",
                     ".github/actions/profile-only/action.yml",
                     ".github/actions/profile-only/run.sh",
                     ".github/actions/profile-only/check.py",
                     ".github/scripts/profile_tool.py",
                     ".github/scripts/profile_pkg/mod.py",
                     ".github/scripts/profile_pkg/data.json"):
            self.assertIn(path, plan)
        self.assertNotIn(".github/scripts/profile_pkg/__pycache__/mod.cpython-314.pyc", plan)
        self.assertIn(SHA, plan[".github/scripts/profile_pkg/mod.py"])

    def core_seed(self, attr: str, rel: str, text: str) -> Path:
        """The core folder `attr`, copied with `rel` added and patched in for this test. The
        core may ship none of a kind, and a collision test must not write the source tree."""
        real = getattr(sync, attr)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / real.name
        if real.exists():
            shutil.copytree(real, folder, ignore=shutil.ignore_patterns("__pycache__"))
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        patcher = mock.patch.object(sync, attr, folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    def test_a_workflow_name_in_both_core_and_profile_is_refused_naming_both_paths(self):
        """Intent: the duplicate rule holds for the new kinds, so a profile
        workflow never silently replaces the core's."""
        core = self.core_seed("WORKFLOWS_DIR", "core-only.yml", "on: push\njobs: {}\n")
        mine = self.seed("workflows/core-only.yml", "on: push\njobs: {}\n")
        self.assert_duplicate_refused(core, mine)

    def test_an_action_name_in_both_core_and_profile_is_refused_naming_both_paths(self):
        """Intent: the duplicate rule holds for actions, compared by action folder."""
        action = "runs:\n  using: composite\n  steps: []\n"
        core = self.core_seed("ACTIONS_DIR", "core-only/action.yml", action)
        mine = self.seed("actions/core-only/action.yml", action)
        self.assert_duplicate_refused(core.parent, mine.parent)

    def test_a_profile_script_landing_on_a_core_script_path_is_refused(self):
        """Intent: a profile script cannot replace a script the core renders by a
        fixed path, such as the response checker's entry point."""
        self.seed("scripts/prime.py", "print('mine')\n")
        with self.assertRaises(sync.SyncError) as ctx:
            self.plan()
        self.assertIn(".github/scripts/prime.py", str(ctx.exception))

    def test_the_new_seed_kinds_are_known(self):
        """Intent: seeds/scripts, seeds/workflows and seeds/actions are accepted, not
        refused as an unknown seed folder."""
        for kind in ("scripts", "workflows", "actions"):
            self.assertIn(kind, sync.SEED_KINDS)

    def assert_duplicate_refused(self, core_path: Path, profile_path: Path, **plan_args):
        with self.assertRaises(sync.SyncError) as ctx:
            self.plan(**plan_args)
        message = str(ctx.exception)
        self.assertIn(str(core_path), message)
        self.assertIn(str(profile_path), message)
        self.assertIn("not allowed", message)
        self.assertIn("new name", message)

    def test_a_skill_name_in_both_core_and_profile_is_refused_naming_both_paths(self):
        """Intent: fail and report that the name attempted is already in use and duplicates
        are not allowed, then ask for a new one."""
        name = sorted(p.name for p in sync.SKILLS_DIR.iterdir() if p.is_dir())[0]
        mine = self.seed(f"skills/{name}/procedure.md",
                         "---\nname: x\ndescription: d\n---\nbody\n")
        self.assert_duplicate_refused(sync.SKILLS_DIR / name, mine.parent)

    def test_a_rule_name_in_both_core_and_profile_is_refused_naming_both_paths(self):
        mine = self.seed("rules/spec-python.md", "---\nid: python\ndescription: d\n---\nbody\n")
        self.assert_duplicate_refused(sync.RULES_DIR / "spec-python.md", mine)

    def test_a_gate_name_in_both_core_and_profile_is_refused_naming_both_paths(self):
        gate = "#!/usr/bin/env bash\nexit 0\n"
        core = self.core_seed("GITHOOKS_DIR", "gates/core-only.sh", gate)
        mine = self.seed("githooks/gates/core-only.sh", gate)
        self.assert_duplicate_refused(core, mine)

    def test_an_agent_hook_name_in_both_core_and_profile_is_refused_naming_both_paths(self):
        core = self.core_seed("HOOKS_DIR", "core-only/hook.yaml", CursorHooks.GUARD)
        mine = self.seed("hooks/core-only/hook.yaml", "event: beforeShellExecution\ncommand: x\n")
        self.assert_duplicate_refused(core.parent, mine.parent, cfg={"hooks": True})

    def test_an_unknown_seed_folder_is_refused_naming_it_and_the_allowed_kinds(self):
        """Intent: a typo such as seeds/skill/ must not render nothing and say nothing,
        the same rule load_profile applies to an unknown key."""
        self.seed("skill/x/procedure.md", "---\nname: x\ndescription: d\n---\nbody\n")
        with self.assertRaises(sync.SyncError) as ctx:
            self.plan()
        self.assertIn("skill", str(ctx.exception))
        self.assertIn("skills", str(ctx.exception))

    def test_every_known_seed_kind_is_allowed(self):
        for kind in sync.SEED_KINDS:
            (self.profile / "seeds" / kind).mkdir(parents=True, exist_ok=True)
        self.assertTrue(self.plan())

    def test_two_writes_to_one_destination_path_are_refused(self):
        """Intent: the secondary guard - names can differ and still land on one file, which
        would silently let the later seed replace the earlier one."""
        plan = sync.Plan()
        plan["a/b"] = "first"
        with self.assertRaises(sync.SyncError) as ctx:
            plan["a/b"] = "second"
        self.assertIn("a/b", str(ctx.exception))
        with self.assertRaises(sync.SyncError):
            plan.update({"a/b": "third"})

    def test_build_plan_returns_a_guarded_plan(self):
        self.assertIsInstance(build_plan("t", {}, DEFAULTS, SHA, MANIFEST), sync.Plan)


class ExampleProfile(unittest.TestCase):
    """examples/profile/ ships with the core, so it must leak nothing from this
    estate, and it must be a profile the renderer accepts."""

    FOLDER = sync.ROOT / "examples" / "profile"

    def tearDown(self):
        build_plan("t", {}, DEFAULTS, SHA, MANIFEST)  # restores the stamp source name

    def test_it_loads_as_a_valid_profile(self):
        self.assertTrue(sync.load_profile(sync.resolve_profile(self.FOLDER)).get("targets"))

    def test_every_key_the_core_accepts_is_present(self):
        profile = sync.load_profile(sync.resolve_profile(self.FOLDER))
        self.assertEqual(set(profile), set(sync.PROFILE_KEYS))

    def test_every_example_target_renders(self):
        folder = locked_example(self)
        profile = sync.load_profile(sync.resolve_profile(folder))
        for name, cfg in profile["targets"].items():
            with self.subTest(target=name):
                plan = build_plan(name, cfg or {}, profile["defaults"], SHA, profile,
                                       profile_dir=folder)
                self.assertIn(f"generated from example-profile@{SHA}", plan["AGENTS.md"])


class MainWithAnotherProfile(unittest.TestCase):
    """`--profile examples/profile <scratch-repo> --write` renders a scratch
    repository from a clean checkout, and every reader gets the same profile path.

    The core's own copy must stay out of it: a profile elsewhere renders its targets and
    nothing else. `emit` is wrapped so a render aimed at this checkout is recorded and not
    written, because a test must not edit the tree it runs in."""

    def setUp(self):
        self.PROFILE = locked_example(self)

    def tearDown(self):
        build_plan("t", {}, DEFAULTS, SHA, MANIFEST)  # restores the stamp source name

    def run_main(self) -> tuple[int, list[Path], Path, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        repo = root / "example-app"
        repo.mkdir()
        git("init", "--quiet", "-b", "main", str(repo), cwd=root)
        configure(repo)
        real_emit = sync.emit
        aimed_at: list[Path] = []

        def recorder(target, plan, write, *, ident):
            aimed_at.append(Path(target).resolve())
            if Path(target).resolve() == sync.ROOT.resolve():
                return 0
            return real_emit(target, plan, write, ident=ident)

        argv = ["sync.py", "--profile", str(self.PROFILE), "--root", str(root),
                "--no-fetch", "--write", "example-app"]
        out = io.StringIO()
        # source_sha refuses a dirty tree, which this checkout is while the suite runs; the
        # refusal has its own tests, so the stamp's SHA is fixed here.
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sync, "emit", recorder), \
                mock.patch.object(sync, "source_sha", return_value=SHA), \
                contextlib.redirect_stdout(out):
            code = sync.main()
        return code, aimed_at, repo, out.getvalue()

    def test_it_renders_the_scratch_repository_from_the_other_profile(self):
        code, _, repo, output = self.run_main()
        self.assertEqual(code, 0, output)
        stamped = (repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("generated from example-profile@", stamped)

    def test_main_prints_each_drop(self):
        """Intent: main reports what the render left out, seeds and
        sections both, rather than only build_plan recording it."""
        for rel, text in (("needs-query", "---\nname: needs-query\ndescription: d\n"
                                          "requires: [tracker.query]\n---\nb\n"),
                          ("has-section", "---\nname: has-section\ndescription: d\n---\n"
                                          "<!-- requires: tracker.query -->\nx\n<!-- end -->\n")):
            seed = self.PROFILE / "seeds" / "skills" / rel / "procedure.md"
            seed.parent.mkdir(parents=True)
            seed.write_text(text, encoding="utf-8", newline="\n")
        code, _, _, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertRegex(output, r"(?m)^\[INFO\] dropped \S*needs-query/procedure\.md: "
                                 r"unbound tracker\.query$")
        self.assertRegex(output, r"(?m)^\[INFO\] dropped section \S*has-section/procedure\.md:5: "
                                 r"unbound tracker\.query$")

    def test_it_never_renders_this_checkout_for_another_profile(self):
        """Intent: the self-render exists so this repo obeys its own rules. Under a
        profile that is not this one it would stamp this checkout with the wrong source."""
        _, aimed_at, _, _ = self.run_main()
        self.assertNotIn(sync.ROOT.resolve(), aimed_at)

    def test_every_reader_gets_the_same_profile_path(self):
        real_resolve = sync.resolve_profile
        seen: list[Path] = []

        def recorder(arg):
            folder = real_resolve(arg)
            seen.append(folder)
            return folder

        with mock.patch.object(sync, "resolve_profile", recorder):
            self.run_main()
        self.assertTrue(seen, "nothing resolved a profile")
        self.assertEqual({str(p) for p in seen}, {str(self.PROFILE.resolve())})


class StampSource(unittest.TestCase):
    """The stamp names the profile's source repository, and every detector accepts any
    source name."""

    OTHER = {**MANIFEST, "source": {**MANIFEST["source"], "repo": "other-profile"}}
    tree = CursorHooks.tree

    def tearDown(self):
        build_plan("t", {}, DEFAULTS, SHA, MANIFEST)  # restores the source name

    def test_the_stamp_carries_the_profile_source_name(self):
        plan = build_plan("t", {}, DEFAULTS, SHA, self.OTHER)
        self.assertIn(f"generated from other-profile@{SHA}", plan["AGENTS.md"])
        self.assertNotIn("generated from example-profile@", plan["AGENTS.md"])

    def test_the_profile_s_own_name_is_stamped(self):
        plan = build_plan("t", {}, DEFAULTS, SHA, MANIFEST)
        self.assertIn(f"{MARK}{SHA}", plan["AGENTS.md"])

    def test_stamp_refuses_before_a_profile_sets_the_source(self):
        """Intent: a render before the profile names its source fails,
        rather than stamping a name that looks right."""
        with mock.patch.object(sync, "_stamp_source", ""):
            with self.assertRaises(sync.SyncError):
                sync.stamp(SHA)

    def test_is_stamped_accepts_any_source_name(self):
        for name in ("some-profile", "other-profile", "a.b_c"):
            with self.subTest(name=name):
                self.assertTrue(sync.is_stamped(f"<!-- generated from {name}@abc1234 - x -->"))

    def test_is_stamped_rejects_text_that_only_resembles_a_stamp(self):
        for text in ("", "plain", "generated from nowhere", "generated from @abc1234"):
            with self.subTest(text=text):
                self.assertFalse(sync.is_stamped(text))

    def test_a_json_stamp_names_the_profile_source_too(self):
        hooks = self.tree({"guard/hook.yaml": CursorHooks.GUARD, "guard/hook.py": "pass\n"})
        with mock.patch.object(sync, "HOOKS_DIR", hooks):
            plan = build_plan("t", {"hooks": True}, DEFAULTS, SHA, self.OTHER)
        self.assertIn(f"generated from other-profile@{SHA}",
                      json.loads(plan[".cursor/hooks.json"])["_generated"])


class SelfStamp(unittest.TestCase):
    """The profile's own render stamps no SHA, so two branches that each change a
    source input do not both rewrite the stamp line of every rendered file. A consuming
    repository's render keeps the SHA: it is the only record of which source version the
    target holds."""

    SELF = "<!-- generated from example-profile - edit the source, not this file -->"
    # Any stamp that still names a SHA, in the HTML-comment, '#'-comment and JSON forms.
    WITH_SHA = r"generated from [^\s@]+@"

    def emitted(self, argv: list[str]) -> list[tuple[Path, dict]]:
        """Each (repo, plan) `main` hands to emit, with the SHA and the disk both faked."""
        calls: list[tuple[Path, dict]] = []

        def recorder(target, plan, write, *, ident):
            calls.append((Path(target), dict(plan)))
            return 0

        with mock.patch.object(sys, "argv", ["sync.py", *argv]), \
                mock.patch.object(sync, "emit", recorder), \
                mock.patch.object(sync, "source_sha", return_value=SHA), \
                contextlib.redirect_stdout(io.StringIO()):
            sync.main()
        return calls

    def self_plan(self) -> dict:
        [(_, plan)] = self.emitted(["--profile", str(EXAMPLE), "--self", "--no-fetch"])
        return plan

    def test_a_self_render_stamps_no_sha(self):
        self.assertEqual(self.self_plan()["AGENTS.md"].splitlines()[0], self.SELF)

    def test_no_file_in_a_self_render_names_a_sha_in_its_stamp(self):
        """Intent: a single file that still stamps a SHA conflicts on every branch that
        re-renders it, so one survivor undoes the change. Only a file's first 40 lines are
        read - where the gates look for the stamp - because a skill's body may quote one."""
        for path, text in self.self_plan().items():
            with self.subTest(path=path):
                found = re.search(self.WITH_SHA + r"\S*", "\n".join(text.splitlines()[:40]))
                self.assertIsNone(found, f"{path} stamps a SHA: {found and found.group()}")

    def test_the_hooks_json_stamp_carries_no_sha_in_a_self_render(self):
        hooks = CursorHooks.tree(self, {"guard/hook.yaml": CursorHooks.GUARD,
                                        "guard/hook.py": "pass\n"})
        real = sync.self_config
        for patcher in (mock.patch.object(sync, "HOOKS_DIR", hooks),
                        mock.patch.object(sync, "self_config",
                                          lambda manifest: {**real(manifest), "hooks": True})):
            patcher.start()
            self.addCleanup(patcher.stop)
        generated = json.loads(self.self_plan()[".cursor/hooks.json"])["_generated"]
        self.assertEqual(generated, "generated from example-profile - edit the source, not this file")

    @unittest.skipUnless((sync.ROOT.parent / sync.PROFILE_NAME).is_file(),
                         "this core does not sit inside a profile")
    def test_a_target_render_keeps_the_sha_and_the_self_render_beside_it_drops_it(self):
        profile = sync.ROOT.parent
        manifest = sync.load_profile(profile)
        name = next(n for n, cfg in (manifest.get("targets") or {}).items()
                    if not (cfg or {}).get("skip"))
        source = sync.source_repo(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / name).mkdir()
            git("init", "--quiet", cwd=Path(tmp) / name)
            calls = self.emitted(["--profile", str(profile), name, "--root", tmp, "--no-fetch"])
        self.assertEqual(len(calls), 2, "expected the target render, then the self-render")
        first = calls[0][1]["AGENTS.md"].splitlines()[0]
        second = calls[1][1]["AGENTS.md"].splitlines()[0]
        self.assertIn(f"generated from {source}@{SHA}", first)
        self.assertEqual(second, f"<!-- generated from {source} - edit the source, not this file -->")

    def test_is_stamped_accepts_the_form_without_a_sha(self):
        for text in ("<!-- generated from some-profile - edit the source, not this file -->",
                     "# generated from some-profile - edit the source, not this file",
                     "generated from a.b_c - edit the source, not this file"):
            with self.subTest(text=text):
                self.assertTrue(sync.is_stamped(text))

    def test_is_stamped_still_accepts_the_form_with_a_sha(self):
        self.assertTrue(sync.is_stamped(
            "<!-- generated from some-profile@abc1234 - edit the source, not this file -->"))

    def test_is_stamped_rejects_prose_that_only_starts_like_a_stamp(self):
        """Intent: no sentence beginning 'generated from' may count as a stamp, in either form."""
        for text in ("generated from the build output", "generated from scratch.",
                     "generated from some-profile", "generated from  - edit the source"):
            with self.subTest(text=text):
                self.assertFalse(sync.is_stamped(text))


class Identity(unittest.TestCase):
    """Every manifest repository commits as the profile identity, set per clone so the
    machine's global config - possibly another identity's address - never decides it."""

    IDENT = {"name": "Profile Owner", "email": "owner@example.invalid"}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.repo.mkdir()
        git("init", "--quiet", cwd=self.repo)

    def local(self, key: str) -> str:
        return subprocess.run(("git", "config", "--local", "--get", key), cwd=self.repo,
                              env=clean_env(), capture_output=True, text=True,
                              timeout=60).stdout.strip()

    def test_a_missing_or_empty_identity_refuses(self):
        """Intent: prescriptions - missing means abort, and an empty value is as dangerous as a
        missing one. A render with no identity would leave the global address in charge."""
        for source in ({}, {"identity": {}}, {"identity": {"name": "n"}},
                       {"identity": {"name": "n", "email": ""}},
                       {"identity": {"name": "", "email": "a@b.c"}},
                       {"identity": {"name": "n", "email": "not-an-address"}}):
            with self.subTest(source=source), self.assertRaises(sync.SyncError):
                sync.identity(source)

    def test_write_sets_the_identity_locally(self):
        """Intent: repository-local user.name and user.email. The address the identity
        gate compares against is rendered, not git config."""
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_identity(self.repo, True, self.IDENT), 2)
        self.assertEqual(self.local("user.name"), "Profile Owner")
        self.assertEqual(self.local("user.email"), "owner@example.invalid")
        self.assertEqual(self.local("gate.identityEmail"), "")

    def test_a_stale_gate_identity_key_is_removed(self):
        """Intent: stop writing gate.identityEmail and unset it where present, so
        no clone keeps a key that reads as if it still governed the gate."""
        git("config", "--local", "gate.identityEmail", "someone@elsewhere.invalid", cwd=self.repo)
        with mock.patch("builtins.print"):
            sync.ensure_identity(self.repo, True, self.IDENT)
            self.assertEqual(self.local("gate.identityEmail"), "")
            self.assertEqual(sync.ensure_identity(self.repo, True, self.IDENT), 0)

    def test_dry_run_writes_nothing(self):
        with mock.patch("builtins.print"):
            self.assertEqual(sync.ensure_identity(self.repo, False, self.IDENT), 2)
        self.assertEqual(self.local("user.email"), "")

    def test_running_twice_changes_nothing_the_second_time(self):
        with mock.patch("builtins.print"):
            sync.ensure_identity(self.repo, True, self.IDENT)
            self.assertEqual(sync.ensure_identity(self.repo, True, self.IDENT), 0)

    def test_verify_passes_once_the_identity_is_set(self):
        with mock.patch("builtins.print"):
            sync.ensure_identity(self.repo, True, self.IDENT)
        sync.verify_identity(self.repo, self.IDENT)

    def test_verify_refuses_what_git_would_actually_use(self):
        """Intent: refuse a target whose effective identity mismatches.
        A later include overrides the local value, so checking config keys would pass here."""
        override = self.repo.parent / "override.gitconfig"
        override.write_text("[user]\n\temail = someone@elsewhere.invalid\n", encoding="utf-8")
        with mock.patch("builtins.print"):
            sync.ensure_identity(self.repo, True, self.IDENT)
        git("config", "--local", "include.path", override.as_posix(), cwd=self.repo)
        with self.assertRaises(sync.SyncError) as caught:
            sync.verify_identity(self.repo, self.IDENT)
        self.assertIn("someone@elsewhere.invalid", str(caught.exception))


class GateConfig(unittest.TestCase):
    """The pre-push hook's settings are a tracked, rendered file, because per-clone git
    config let one `git config` line disable a guard unseen."""

    def config(self, cfg: dict) -> dict[str, str]:
        text = build_plan("t", cfg, DEFAULTS, SHA, MANIFEST)[".githooks/gate-config"]
        self.assertIn(MARK, text.splitlines()[0])
        return dict(line.split("=", 1) for line in text.splitlines()[1:])

    def test_the_plan_carries_the_target_branch_and_the_source_identity(self):
        """Intent: from the manifest, the target's branch: and the source identity."""
        self.assertEqual(self.config({"branch": "dev"}),
                         {"deploy-branch": "dev",
                          "identity-email": MANIFEST["identity"]["email"],
                          "config-dir": MANIFEST["gate_config_dir"]})

    def test_a_target_without_a_branch_deploys_from_main(self):
        """Characterisation: the hook defaulted to main; the default moves here."""
        self.assertEqual(self.config({})["deploy-branch"], "main")

    def test_a_branch_that_could_forge_a_line_is_refused(self):
        """Intent: prescriptions - validate every externally supplied value before it reaches a
        path or command. A newline in branch: would write a second identity-email line."""
        for branch in ("dev\nidentity-email=x@y.z", "has space", ""):
            with self.subTest(branch=branch), self.assertRaises(sync.SyncError):
                build_plan("t", {"branch": branch}, DEFAULTS, SHA, MANIFEST)

    def test_a_stale_deploy_branch_key_is_removed(self):
        """Intent: stop setting gate.deployBranch and unset it where present."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git("init", "--quiet", cwd=repo)
            (repo / ".githooks").mkdir()
            git("config", "--local", "gate.deployBranch", "nothing", cwd=repo)
            with mock.patch("builtins.print"):
                sync.activate_hooks(repo, True)
            found = subprocess.run(("git", "config", "--local", "--get", "gate.deployBranch"),
                                   cwd=repo, env=clean_env(), capture_output=True, text=True,
                                   timeout=60).stdout.strip()
            self.assertEqual(found, "")


FIXTURE_TARGETS = {
    "alpha": {},
    "bravo": {},
    "charlie": {"branch": "dev"},
    "delta": {"skip": True},
}
LIVE = [name for name, cfg in FIXTURE_TARGETS.items() if not cfg.get("skip")]
IDENTITY = {"user.name": "rollout fixture", "user.email": "fixture@example.invalid",
            "commit.gpgsign": "false"}


def clean_env(**extra: str) -> dict[str, str]:
    # Under a pre-push hook GIT_DIR points at the profile repo, and git would act on it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra)
    return env


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(("git", *args), cwd=cwd, env=clean_env(), capture_output=True,
                            text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"fixture: git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout.strip()


def configure(repo: Path) -> None:
    for key, value in IDENTITY.items():
        git("config", key, value, cwd=repo)


def branch_of(name: str) -> str:
    return FIXTURE_TARGETS[name].get("branch", "main")


class GateFlags(unittest.TestCase):
    """The enabled-gate list is rendered from profile.lock, and a lock that disagrees
    with features: refuses the render, naming the flag. Run against a copy of the example
    profile, so no test writes this checkout's own lock."""

    def setUp(self):
        self.folder = example_copy(self, gates=("alpha", "beta"))
        self.known = sync.consent.known_gates(self.folder)
        self.addCleanup(sync.set_stamp_source, MANIFEST)

    def declare(self, gates: dict, locked: dict | None = None) -> None:
        """Write features: as `gates`, and the lock as `locked` (default: the same)."""
        path = self.folder / "profile.yaml"
        path.write_text(sync.consent.replace_features_block(
            path.read_text(encoding="utf-8"), sync.consent.render_features_block(gates)),
            encoding="utf-8")
        (self.folder / sync.consent.LOCK_NAME).write_text(
            sync.consent.render_lock({"gates": gates if locked is None else locked}),
            encoding="utf-8")

    def plan(self) -> dict:
        profile = sync.load_profile(self.folder)
        return build_plan("example-app", {}, profile["defaults"], SHA, profile,
                               profile_dir=self.folder)

    def enabled(self) -> list[str]:
        text = self.plan()[sync.ENABLED_GATES]
        return [line for line in text.splitlines() if line and not line.startswith("#")]

    def test_no_lock_refuses_the_render(self):
        """Intent: no lock refuses, pointing at the one-time
        consent run, rather than rendering every gate as enabled."""
        with self.assertRaises(sync.SyncError) as caught:
            self.plan()
        self.assertIn("core/consent.py --profile . --init", str(caught.exception))

    def test_every_gate_that_is_on_is_listed(self):
        """Intent: render the enabled-gate list from the lock."""
        self.declare({name: True for name in self.known})
        self.assertEqual(self.enabled(), sorted(self.known))

    def test_a_disabled_gate_is_left_off_the_list(self):
        """Intent: the enabled-gate list is rendered, and CI's required list
        derived from it."""
        off = self.known[0]
        self.declare({name: name != off for name in self.known})
        self.assertNotIn(off, self.enabled())
        self.assertEqual(len(self.enabled()), len(self.known) - 1)

    def test_a_features_edit_without_consent_refuses_naming_the_flag(self):
        """Intent: a features: edit without the consent command fails the
        next render, naming the flag."""
        off = self.known[0]
        self.declare({name: name != off for name in self.known},
                     locked={name: True for name in self.known})
        with self.assertRaises(sync.SyncError) as caught:
            self.plan()
        self.assertIn(off, str(caught.exception))

    def test_the_old_gate_list_is_no_longer_rendered(self):
        """Intent: delete the gates file; the list is derived, not hand-kept."""
        self.declare({name: True for name in self.known})
        self.assertNotIn(".github/gates", self.plan())
        self.assertFalse((sync.ROOT / "gates").exists())

    def test_a_target_s_old_gate_list_is_removed_as_an_orphan(self):
        """Intent: a target's stamped .github/gates must not linger beside the new list,
        where a reader could still find it."""
        self.declare({name: True for name in self.known})
        with tempfile.TemporaryDirectory() as repo:
            old = Path(repo) / ".github" / "gates"
            old.parent.mkdir(parents=True)
            old.write_text(f"# {sync.stamp(SHA)[5:-4].strip()}\nidentity\n", encoding="utf-8")
            self.assertIn(".github/gates", sync.find_orphans(Path(repo), self.plan()))

    def test_only_the_profile_repo_is_told_to_check_its_lock(self):
        """Intent: the lock is enforced in the profile repo, and a target trusts
        its rendered list, so only the self-render names the consent check."""
        mine = build_plan("example-profile", sync.self_config(MANIFEST), DEFAULTS, SHA, MANIFEST)
        name, cfg = next(iter(live_targets().items()))
        theirs = build_plan(name, cfg, DEFAULTS, SHA, MANIFEST)
        self.assertIn(f"consent-check={sync.CONSENT_SCRIPT}\n", mine[".githooks/gate-config"])
        self.assertNotIn("consent-check", theirs[".githooks/gate-config"])
        self.assertEqual(sync.CONSENT_SCRIPT, "core/consent.py")
        self.assertTrue((sync.ROOT / "consent.py").is_file())


class CapabilityBindings(unittest.TestCase):
    """A profile binds the wireframes' capabilities to skills, and a seed that
    requires an unbound capability is dropped and named rather than rendered half-working."""

    NEEDS = "requires: [tracker.query]\n"
    QUERY = {"tracker.query": {"skill": "example-tracker"}}

    def setUp(self):
        self.profile = example_copy(self)
        self.seed(TRACKER, TRACKER_TEXT)

    def seed(self, rel: str, text: str) -> Path:
        path = self.profile / "seeds" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def seed_every_kind(self, extra: str = "") -> list[Path]:
        return [
            self.seed("skills/needs-query/procedure.md",
                      f"---\nname: needs-query\ndescription: d\n{extra}---\nbody\n"),
            self.seed("rules/spec-needs-query.md",
                      f"---\nid: needs-query\ndescription: d\nscope: '*'\n{extra}---\nbody\n"),
            self.seed("context/needs-query.prompt.md", f"---\ndescription: d\n{extra}---\nbody\n"),
            self.seed("agents/needs-query/definition.md",
                      f"---\nname: needs-query\ndescription: d\n{extra}---\nbody\n"),
        ]

    def plan(self, capabilities: dict | None = None) -> sync.Plan:
        manifest = {**MANIFEST, "features": lock_all_on(self.profile),
                    "capabilities": capabilities or {}}
        defaults = DEFAULTS
        if (self.profile / "seeds" / "rules" / "spec-needs-query.md").exists():
            defaults = {**DEFAULTS, "tier2": [*DEFAULTS["tier2"], "needs-query"]}
        return build_plan("t", {}, defaults, SHA, manifest, profile_dir=self.profile)

    RENDERED = (".cursor/skills/needs-query/SKILL.md", ".cursor/rules/needs-query.mdc",
                ".github/prompts/needs-query.prompt.md", ".github/agents/needs-query.agent.md")

    def assert_refuses(self, needle: str, **plan_args) -> None:
        with self.assertRaises(sync.SyncError) as caught:
            self.plan(**plan_args)
        self.assertIn(needle, str(caught.exception))

    def test_capabilities_come_from_every_wireframe(self):
        """Intent: a second wireframe needs no edit to sync.py."""
        folder = self.profile / "capabilities"
        folder.mkdir()
        (folder / "a.yaml").write_text("operations:\n  x: {capability: a.x}\n", encoding="utf-8")
        (folder / "b.yaml").write_text("operations:\n  y: {capability: b.y}\n", encoding="utf-8")
        with mock.patch.object(sync, "CAPABILITIES_DIR", folder):
            self.assertEqual(sync.known_capabilities(), {"a.x", "b.y"})

    def test_a_wireframe_that_names_no_capability_or_repeats_one_refuses(self):
        folder = self.profile / "capabilities"
        folder.mkdir()
        for text in ("operations:\n  x: {description: d}\n", "operations: []\n",
                     "operations:\n  x: {capability: a.x}\n  y: {capability: a.x}\n"):
            with self.subTest(text=text):
                (folder / "a.yaml").write_text(text, encoding="utf-8")
                with mock.patch.object(sync, "CAPABILITIES_DIR", folder), \
                        self.assertRaises(sync.SyncError):
                    sync.known_capabilities()

    def test_a_misspelled_binding_refuses_naming_it(self):
        """Intent: a typo must not read as unbound and drop silently."""
        self.assert_refuses("tracker.qeury",
                            capabilities={"tracker.qeury": {"skill": "example-tracker"}})

    def test_a_binding_names_exactly_one_skill(self):
        """Intent: {skill: <name>} and nothing else, until another kind exists."""
        for value in ("example-tracker", {"agent": "qa"}, {"skill": 3},
                      {"skill": "example-tracker", "agent": "qa"}):
            with self.subTest(value=value):
                self.assert_refuses("tracker.query", capabilities={"tracker.query": value})

    def test_a_binding_to_a_skill_no_seed_provides_refuses(self):
        self.assert_refuses("no-such-skill",
                            capabilities={"tracker.query": {"skill": "no-such-skill"}})

    def test_an_unbound_requirement_drops_every_kind_and_names_it(self):
        """Intent: requires: drops the whole artifact, and sync lists it."""
        seeds = self.seed_every_kind(self.NEEDS)
        plan = self.plan()
        for path in self.RENDERED:
            with self.subTest(path=path):
                self.assertNotIn(path, plan)
        self.assertEqual(sorted(own_drops(self.profile, plan.dropped)),
                         sorted((p, ["tracker.query"]) for p in seeds))

    def test_a_bound_requirement_renders_every_kind(self):
        self.seed_every_kind(self.NEEDS)
        plan = self.plan(self.QUERY)
        for path in self.RENDERED:
            with self.subTest(path=path):
                self.assertIn(path, plan)
        self.assertEqual(own_drops(self.profile, plan.dropped), [])
        self.assertNotIn("requires", plan[".cursor/skills/needs-query/SKILL.md"])

    def test_a_misspelled_requirement_refuses_naming_it(self):
        self.seed_every_kind("requires: [tracker.qeury]\n")
        self.assert_refuses("tracker.qeury", capabilities=self.QUERY)

    def test_requires_must_be_a_list(self):
        self.seed_every_kind("requires: tracker.query\n")
        self.assert_refuses("must be a list", capabilities=self.QUERY)

    def test_an_agent_listing_a_dropped_agent_refuses(self):
        """Intent: a dropped agent must not leave a subagent list pointing at it."""
        self.seed("agents/needs-query/definition.md",
                  f"---\nname: needs-query\ndescription: d\n{self.NEEDS}---\nbody\n")
        self.seed("agents/caller/definition.md",
                  "---\nname: caller\ndescription: d\nagents: [needs-query]\n---\nbody\n")
        self.assert_refuses("needs-query")

    def test_a_binding_to_a_dropped_skill_refuses(self):
        self.seed("skills/needs-query/procedure.md",
                  "---\nname: needs-query\ndescription: d\nrequires: [tracker.edit]\n---\nb\n")
        self.assert_refuses("tracker.query",
                            capabilities={"tracker.query": {"skill": "needs-query"}})

    def test_each_drop_is_printed_with_what_dropped_it(self):
        seeds = self.seed_every_kind(self.NEEDS)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sync.report_drops(self.plan())
        lines = [line for line in out.getvalue().splitlines() if "needs-query" in line]
        self.assertEqual(len(lines), len(seeds))
        for line in lines:
            self.assertRegex(line, r"^\[INFO\] dropped \S+: unbound tracker\.query$")


class RequiresBlocks(unittest.TestCase):
    """A seed body's <!-- requires: --> blocks and {{capability}} markers
    render for a profile that binds them, and drop or refuse - naming the source line - for
    one that does not."""

    QUERY = {"tracker.query": {"skill": "example-tracker"}}
    NEEDS = "requires: [tracker.query]\n"
    SKILL = "skills/needs-query/procedure.md"
    OUT = ".cursor/skills/needs-query/SKILL.md"
    # The skill seed's frontmatter is four lines, five with NEEDS, so its body starts on
    # line 5 or 6 of the file.

    def setUp(self):
        self.profile = example_copy(self)
        self.seed(TRACKER, TRACKER_TEXT)

    def seed(self, rel: str, text: str) -> Path:
        path = self.profile / "seeds" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def skill(self, body: str, extra: str = "") -> Path:
        return self.seed(self.SKILL, f"---\nname: needs-query\ndescription: d\n{extra}---\n{body}")

    def plan(self, capabilities: dict | None = None, cfg: dict | None = None) -> sync.Plan:
        manifest = {**MANIFEST, "features": lock_all_on(self.profile),
                    "capabilities": capabilities or {}}
        defaults = DEFAULTS
        if (self.profile / "seeds" / "rules" / "spec-needs-query.md").exists():
            defaults = {**DEFAULTS, "tier2": [*DEFAULTS["tier2"], "needs-query"]}
        return build_plan("t", cfg or {}, defaults, SHA, manifest, profile_dir=self.profile)

    def assert_refuses(self, *needles: str, capabilities: dict | None = None) -> None:
        with self.assertRaises(sync.SyncError) as caught:
            self.plan(self.QUERY if capabilities is None else capabilities)
        for needle in needles:
            self.assertIn(needle, str(caught.exception))

    BLOCK = "before\n<!-- requires: tracker.query -->\nonly-when-bound\n<!-- end -->\nafter\n"

    def test_a_bound_block_keeps_its_content_and_loses_its_marker_lines(self):
        """Intent: a section that needs a capability renders where it is bound,
        and the block syntax never reaches the reader."""
        self.skill(self.BLOCK)
        plan = self.plan(self.QUERY)
        self.assertIn("before\nonly-when-bound\nafter\n", plan[self.OUT])
        self.assertNotIn("<!--", plan[self.OUT].split("-->", 1)[1])
        self.assertEqual(own_drops(self.profile, plan.dropped_sections), [])

    def test_an_unbound_block_is_removed_and_recorded_with_its_line(self):
        """Intent: the section half of the drop listing: what was left out, and
        where, so a profile can see what binding would bring it back."""
        path = self.skill(self.BLOCK)
        plan = self.plan()
        self.assertIn("before\nafter\n", plan[self.OUT])
        self.assertNotIn("only-when-bound", plan[self.OUT])
        self.assertEqual(own_drops(self.profile, plan.dropped_sections),
                         [(path, 6, ["tracker.query"])])

    def test_each_dropped_section_is_printed_with_its_line(self):
        self.skill(self.BLOCK)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sync.report_drops(self.plan())
        mine = [line for line in out.getvalue().splitlines() if "needs-query" in line]
        self.assertEqual(len(mine), 1, out.getvalue())
        self.assertRegex(mine[0], r"^\[INFO\] dropped section \S+procedure\.md:6: "
                                  r"unbound tracker\.query$")

    def test_a_guarded_marker_renders_as_the_bound_skill(self):
        """Intent: a marker reads as prose naming the skill."""
        for body, extra in (("Use {{tracker.query}}.\n", self.NEEDS),
                            ("<!-- requires: tracker.query -->\nUse {{tracker.query}}.\n"
                             "<!-- end -->\n", "")):
            with self.subTest(body=body):
                self.skill(body, extra)
                self.assertIn("Use the `example-tracker` skill.\n",
                              self.plan(self.QUERY)[self.OUT])

    def test_a_marker_in_fenced_code_is_still_resolved(self):
        """Intent: no fence exemption, so a marker cannot hide in an
        example and render literally for every profile."""
        self.skill("```\n{{tracker.query}}\n```\n", self.NEEDS)
        self.assertIn("```\nthe `example-tracker` skill\n```\n", self.plan(self.QUERY)[self.OUT])

    def test_an_unguarded_marker_refuses_naming_its_line(self):
        """Intent: a marker outside requires: and outside a block renders for a
        profile that binds it and points at nothing for one that does not."""
        self.skill("x\n{{tracker.query}}\n")
        self.assert_refuses("procedure.md:6", "unguarded")

    def test_a_marker_naming_no_capability_refuses_even_in_a_dropped_block(self):
        """Intent: a typo must refuse in every profile, not only one that binds the block."""
        for body, caps in (("{{tracker.qeury}}\n", self.QUERY),
                           ("<!-- requires: tracker.query -->\n{{tracker.qeury}}\n"
                            "<!-- end -->\n", {})):
            with self.subTest(body=body):
                self.skill(body)
                self.assert_refuses("{{tracker.qeury}}", "names no capability",
                                    capabilities=caps)

    def test_a_malformed_block_refuses_naming_its_line(self):
        """Intent: nesting refuses, and so does every structure that
        would otherwise render a block's markers literally or drop the rest of the file."""
        cases = {
            "nested": ("<!-- requires: tracker.query -->\n<!-- requires: tracker.edit -->\n"
                       "<!-- end -->\n<!-- end -->\n", "procedure.md:6"),
            "stray end": ("a\n<!-- end -->\n", "procedure.md:6"),
            "unclosed": ("a\n<!-- requires: tracker.query -->\nb\n", "procedure.md:6"),
            "no names": ("<!-- requires: -->\n<!-- end -->\n", "procedure.md:5"),
            "unknown name": ("<!-- requires: tracker.qeury -->\n<!-- end -->\n",
                             "tracker.qeury"),
            "not alone": ("a <!-- end -->\n", "procedure.md:5"),
        }
        for case, (body, needle) in cases.items():
            with self.subTest(case=case):
                self.skill(body)
                self.assert_refuses(needle)

    def test_every_markdown_body_passes_through_render_body(self):
        """Intent: one function for every body, so no kind renders a marker
        literally because its branch was missed."""
        body = "{{tracker.query}}\n"
        seeds = [
            self.skill(body, self.NEEDS),
            self.seed("rules/spec-needs-query.md",
                      f"---\nid: needs-query\ndescription: d\nscope: '*'\n{self.NEEDS}---\n{body}"),
            self.seed("context/needs-query.prompt.md", f"---\ndescription: d\n{self.NEEDS}---\n{body}"),
            self.seed("agents/needs-query/definition.md",
                      f"---\nname: needs-query\ndescription: d\n{self.NEEDS}---\n{body}"),
        ]
        with mock.patch.object(sync, "render_body", wraps=sync.render_body) as spy:
            plan = self.plan(self.QUERY, cfg={"estate": True})
        seen = {call.args[1] for call in spy.call_args_list}
        estate = self.profile / "seeds" / "context" / "estate.md"
        for path in [*seeds, sync.RULES_DIR / "prescriptions.md", estate]:
            with self.subTest(path=path):
                self.assertIn(path, seen)
        for out in (self.OUT, ".cursor/rules/needs-query.mdc",
                    ".github/prompts/needs-query.prompt.md", ".github/agents/needs-query.agent.md"):
            with self.subTest(out=out):
                self.assertIn("the `example-tracker` skill", plan[out])

    def test_a_dropped_seed_is_still_checked(self):
        """Intent: a broken block in a seed every profile drops must
        refuse now, not in the first profile that binds it."""
        broken = "<!-- requires: tracker.query -->\nnever closed\n"
        kinds = {
            self.SKILL: "---\nname: needs-query\ndescription: d\n",
            "rules/spec-needs-query.md": "---\nid: needs-query\ndescription: d\nscope: '*'\n",
            "context/needs-query.prompt.md": "---\ndescription: d\n",
            "agents/needs-query/definition.md": "---\nname: needs-query\ndescription: d\n",
        }
        for rel, head in kinds.items():
            with self.subTest(kind=rel):
                path = self.seed(rel, f"{head}{self.NEEDS}---\n{broken}")
                self.assert_refuses(path.name, "never closed", capabilities={})
                path.unlink()

    def test_a_dropped_seed_records_no_sections(self):
        """Intent: the seed is already listed as dropped; its blocks are not listed again."""
        path = self.skill(self.BLOCK, self.NEEDS)
        plan = self.plan()
        self.assertEqual(own_drops(self.profile, plan.dropped), [(path, ["tracker.query"])])
        self.assertEqual(own_drops(self.profile, plan.dropped_sections), [])

    def test_requires_on_agents_md_or_the_estate_map_refuses(self):
        """Intent: dropping either leaves a repo without its
        resident rules, so requires: there refuses even when the capability is bound."""
        real = sync.load_doc
        for name in ("prescriptions.md", "estate.md"):
            def with_requires(path, *required, name=name):
                meta, body = real(path, *required)
                return ({**meta, "requires": ["tracker.query"]} if path.name == name else meta,
                        body)

            with self.subTest(name=name), mock.patch.object(sync, "load_doc", with_requires), \
                    self.assertRaises(sync.SyncError) as caught:
                self.plan(self.QUERY, cfg={"estate": True})
            self.assertIn(name, str(caught.exception))
            self.assertIn("requires:", str(caught.exception))

    def test_go_templates_are_not_markers(self):
        """Characterisation: docker inspect lines use Go-template braces. The marker
        pattern must not read them, or a correct seed refuses."""
        body = "docker inspect -f '{{.State.Status}}' x\ndocker inspect -f '{{json .Mounts}}' x\n"
        self.assertEqual(sync.MARKER.findall(body), [])
        self.skill(body)
        self.assertIn("{{json .Mounts}}", self.plan()[self.OUT])


class ModeBlocks(unittest.TestCase):
    """A seed body's <!-- mode: --> blocks render only for a target of that
    mode, and refuse - naming the source line - when malformed."""

    SKILL = "skills/moded/procedure.md"
    OUT = ".cursor/skills/moded/SKILL.md"
    # The skill seed's frontmatter is four lines, so its body starts on line 5.
    BLOCKS = ("shared\n<!-- mode: interactive -->\nask first\n<!-- end -->\n"
              "<!-- mode: factory -->\nthe spec is your grant\n<!-- end -->\nshared again\n")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)

    def skill(self, body: str) -> Path:
        path = self.profile / "seeds" / self.SKILL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: moded\ndescription: d\n---\n{body}", encoding="utf-8",
                        newline="\n")
        return path

    def plan(self) -> sync.Plan:
        manifest = {**MANIFEST, "features": lock_all_on(self.profile)}
        return build_plan("t", {}, DEFAULTS, SHA, manifest, profile_dir=self.profile)

    def render(self, path: Path, mode: str) -> str:
        meta, body = sync.load_doc(path, "name", "description")
        return sync.render_body(body, path, meta, sync.known_capabilities(), {}, sync.Plan(),
                                mode=mode)

    def test_an_interactive_target_keeps_only_interactive_sections(self):
        """Intent: "Each render target takes the core plus its own mode's sections."
        Every target rendered today is interactive."""
        self.skill(self.BLOCKS)
        out = self.plan()[self.OUT]
        self.assertIn("shared\nask first\nshared again\n", out)
        self.assertNotIn("the spec is your grant", out)
        self.assertNotIn("<!--", out.split("-->", 1)[1])

    def test_a_factory_target_keeps_only_factory_sections(self):
        """Intent: the factory render takes the core plus the factory
        sections, and never the interactive ones."""
        path = self.skill(self.BLOCKS)
        self.assertEqual(self.render(path, "factory"),
                         "shared\nthe spec is your grant\nshared again\n")

    def test_a_left_out_mode_section_is_not_listed_as_dropped(self):
        """Intent: every render leaves out the other mode's sections, so listing
        them beside unbound capabilities would bury the drops that matter."""
        path = self.skill(self.BLOCKS)
        plan = self.plan()
        self.assertEqual([d for d in plan.dropped_sections if d[0] == path], [])

    def test_a_malformed_mode_block_refuses_naming_its_line(self):
        """Intent: the same structural rules as a requires block, so a
        marker never renders literally and a section never leaks into the wrong mode."""
        cases = {
            "unknown mode": ("<!-- mode: headless -->\nx\n<!-- end -->\n", "procedure.md:5"),
            "mode in mode": ("<!-- mode: factory -->\n<!-- mode: interactive -->\n"
                             "<!-- end -->\n<!-- end -->\n", "procedure.md:6"),
            "mode in requires": ("<!-- requires: tracker.query -->\n<!-- mode: factory -->\n"
                                 "<!-- end -->\n<!-- end -->\n", "procedure.md:6"),
            "requires in mode": ("<!-- mode: factory -->\n<!-- requires: tracker.query -->\n"
                                 "<!-- end -->\n<!-- end -->\n", "procedure.md:6"),
            "unclosed": ("a\n<!-- mode: factory -->\nb\n", "procedure.md:6"),
            "not alone": ("a <!-- mode: factory -->\n", "procedure.md:5"),
        }
        for case, (body, needle) in cases.items():
            with self.subTest(case=case):
                self.skill(body)
                with self.assertRaises(sync.SyncError) as caught:
                    self.plan()
                self.assertIn(needle, str(caught.exception))


class SeedSessions(unittest.TestCase):
    """An agent seed's sessions: names the kinds of session it is rendered
    for, and is interactive alone when absent."""

    OUT = ".github/agents/moded.agent.md"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)

    def agent(self, extra: str = "") -> Path:
        path = self.profile / "seeds" / "agents" / "moded" / "definition.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: moded\ndescription: d\n{extra}---\nbody\n",
                        encoding="utf-8", newline="\n")
        return path

    def plan(self) -> sync.Plan:
        manifest = {**MANIFEST, "features": lock_all_on(self.profile)}
        return build_plan("t", {}, DEFAULTS, SHA, manifest, profile_dir=self.profile)

    def test_an_agent_without_sessions_renders_for_interactive_tools(self):
        """Characterisation: no agent seed carries sessions: today. Pinned so the new key
        can never drop one that leaves it out: absent is interactive."""
        self.agent()
        self.assertIn("body", self.plan()[self.OUT])

    def test_a_factory_only_agent_gets_no_interactive_file(self):
        """Intent: "Each render target takes the core plus its own mode's sections."
        A role only the factory runs must not load in Cursor or VS Code."""
        self.agent("sessions: [factory]\n")
        self.assertNotIn(self.OUT, self.plan())

    def test_the_key_does_not_reach_the_rendered_frontmatter(self):
        """Characterisation: render_agent copies named fields only. Pinned because a
        sessions: line in a VS Code agent file is an unknown key that tool would report."""
        self.agent("sessions: [interactive, factory]\n")
        self.assertNotIn("sessions", self.plan()[self.OUT])

    def test_a_malformed_sessions_value_refuses_naming_the_seed(self):
        """Intent: "an unknown key refuses ... so a typo is never ignored"
        (sync.py load_profile). An unrecognised session would render a role nowhere."""
        cases = {
            "unknown": "sessions: [headless]\n",
            "empty": "sessions: []\n",
            "not a list": "sessions: factory\n",
            "duplicate": "sessions: [factory, factory]\n",
        }
        for case, extra in cases.items():
            with self.subTest(case=case):
                self.agent(extra)
                with self.assertRaises(sync.SyncError) as caught:
                    self.plan()
                self.assertIn("definition.md: sessions:", str(caught.exception))


class FactoryBundle(unittest.TestCase):
    """A target with factory: true also receives the factory bundle - the
    factory prescriptions and every agent that opts in, rendered in factory mode."""

    ROLES = ("coder", "qa", "test-writer")

    def bundle(self, plan: dict) -> list[str]:
        return sorted(p for p in plan if p.startswith(f"{sync.FACTORY_DIR}/"))

    def plan(self, cfg: dict | None = None) -> sync.Plan:
        return build_plan("t", {"factory": True} if cfg is None else cfg, DEFAULTS, SHA,
                               MANIFEST)

    def test_the_bundle_is_the_prescriptions_and_the_opted_in_roles(self):
        """Intent: factory/rules/prescriptions.md and
        factory/rules/<role>.agent.md, for the three roles the inventory covers."""
        self.assertEqual(self.bundle(self.plan()),
                         sorted([f"{sync.FACTORY_DIR}/prescriptions.md",
                                 *(f"{sync.FACTORY_DIR}/{r}.agent.md" for r in self.ROLES)]))

    def test_no_bundle_file_is_named_agents_md(self):
        """Intent: interactive tools load a nested AGENTS.md, so a bundle file
        by that name would put factory rules into interactive sessions."""
        self.assertFalse([p for p in self.bundle(self.plan()) if p.endswith("AGENTS.md")])

    def test_the_bundle_carries_factory_sections_only(self):
        """Intent: "Each render target takes the core plus its own mode's sections."
        Checked against lines each mode is known to hold."""
        plan = self.plan()
        rules = plan[f"{sync.FACTORY_DIR}/prescriptions.md"]
        self.assertIn("Never commit a live credential", rules)
        self.assertNotIn("wait for explicit approval", rules)
        role = plan[f"{sync.FACTORY_DIR}/test-writer.agent.md"]
        self.assertIn("the spec this run was briefed with", role)
        self.assertNotIn("ask the operator for one case", role)
        self.assertNotIn("<!--", role.split("-->", 1)[1])

    def test_factory_qa_judges_survivors_and_never_mutates(self):
        """Intent: factory QA never mutates and has no edit rights; it judges the survivors
        the brief lists, and a survivor is either weak or equivalent."""
        role = self.plan()[f"{sync.FACTORY_DIR}/qa.agent.md"]
        for stale in ("break the code it covers", "Mutate code", "the mutation made",
                      "Edits anywhere but the copy"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, role)
        for wanted in ("surviv", "`weak`", "`equivalent`", "Every edit"):
            with self.subTest(wanted=wanted):
                self.assertIn(wanted, role)

    def test_factory_qa_verdict_is_one_of_three_exact_words(self):
        """Intent: factory QA allows exactly "weak", "equivalent" and "undecided", each
        with a reason, in the agreed shape - the result block's verdict field plus reasons,
        with the covering tests in reasons."""
        role = self.plan()[f"{sync.FACTORY_DIR}/qa.agent.md"]
        for wanted in ("`weak`", "`equivalent`", "`undecided`", "`verdict`", "`reasons`",
                       "tests:", "rather than tracing at length"):
            with self.subTest(wanted=wanted):
                self.assertIn(wanted, role)
        self.assertNotIn("still passed - weak", role,
                         "the harness matches `weak` exactly; the prefix reads as not judged")

    def test_interactive_qa_still_mutates_in_its_own_worktree(self):
        """Intent: interactive mode is unchanged, because interactive QA still mutates inside
        its own worktree."""
        role = self.plan()[".github/agents/qa.agent.md"]
        self.assertIn("break the code it covers", role)
        self.assertIn("git worktree add --detach", role)
        self.assertNotIn("equivalent", role)
        self.assertNotIn("undecided", role)
        self.assertIn("still passed - weak", role)

    def test_every_bundle_file_is_stamped_with_the_source_sha(self):
        """Intent: the factory set comes from a render pinned by SHA, which the harness
        also needs."""
        plan = self.plan()
        for path in self.bundle(plan):
            with self.subTest(path=path):
                self.assertTrue(sync.is_stamped(plan[path]))
                self.assertIn(SHA, plan[path])

    def test_the_interactive_files_are_unchanged_by_the_bundle(self):
        """Characterisation: before the bundle existed, a target's render was its interactive
        files alone. Pinned so turning the bundle on never changes them."""
        with_bundle, without = self.plan(), self.plan({})
        factory = (f"{sync.FACTORY_DIR}/", f"{sync.FACTORY_SKILLS_DIR}/")
        self.assertEqual({p: c for p, c in with_bundle.items() if not p.startswith(factory)},
                         dict(without))

    def test_a_target_without_the_key_gets_no_bundle(self):
        """Characterisation: no target renders a bundle today. Pinned so the bundle stays
        opt-in per target."""
        self.assertEqual(self.bundle(self.plan({})), [])

    def test_a_stale_bundle_file_is_an_orphan(self):
        """Intent: the directory is fixed so a bundle the
        target stops receiving is found and removed like any other rendered file."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            stale = repo / sync.FACTORY_DIR / "retired-role.agent.md"
            stale.parent.mkdir(parents=True)
            stale.write_text(f"<!-- {sync.STAMP_MARKER}x -->\n", encoding="utf-8")
            self.assertIn(f"{sync.FACTORY_DIR}/retired-role.agent.md",
                          sync.find_orphans(repo, self.plan({})))

    def test_a_malformed_key_or_an_empty_bundle_refuses(self):
        """Intent: a typo is never ignored - and a bundle with no role would
        hand the harness prescriptions and nothing to run."""
        with self.assertRaises(sync.SyncError) as caught:
            self.plan({"factory": "yes"})
        self.assertIn("factory: must be true or false", str(caught.exception))
        with tempfile.TemporaryDirectory() as empty, \
                mock.patch.object(sync, "AGENTS_DIR", Path(empty)):
            with self.assertRaises(sync.SyncError) as caught:
                self.plan()
        self.assertIn("no agent seed lists factory", str(caught.exception))


class FactorySkills(unittest.TestCase):
    """A skill seed that opts into the factory renders into the factory bundle,
    and an agent seed names the factory skills its role is given."""

    SKILL = "factory/skills/kit/SKILL.md"
    ROLE = "factory/rules/moded.agent.md"
    BLOCKS = ("shared\n<!-- mode: interactive -->\nask first\n<!-- end -->\n"
              "<!-- mode: factory -->\nthe spec is your grant\n<!-- end -->\n")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)

    def skill(self, extra: str = "", name: str = "kit", body: str = "body\n") -> Path:
        path = self.profile / "seeds" / "skills" / name / "procedure.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: d\n{extra}---\n{body}",
                        encoding="utf-8", newline="\n")
        return path

    def agent(self, extra: str = "") -> Path:
        path = self.profile / "seeds" / "agents" / "moded" / "definition.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: moded\ndescription: d\nsessions: [interactive, factory]\n"
                        f"{extra}---\nbody\n", encoding="utf-8", newline="\n")
        return path

    def plan(self, cfg: dict | None = None) -> sync.Plan:
        manifest = {**MANIFEST, "features": lock_all_on(self.profile)}
        return build_plan("t", {"factory": True} if cfg is None else cfg, DEFAULTS, SHA,
                               manifest, profile_dir=self.profile)

    def factory_skills(self, plan: dict) -> list[str]:
        return sorted(p for p in plan if p.startswith("factory/skills/"))

    def test_a_skill_for_both_sessions_renders_to_the_bundle_and_both_roots(self):
        """Intent: "A skill whose sessions: includes factory renders to
        factory/skills/<name>/SKILL.md ... for factory: true targets only." """
        self.skill("sessions: [interactive, factory]\n")
        plan = self.plan()
        self.assertIn(self.SKILL, plan)
        for root in sync.SKILL_ROOTS:
            with self.subTest(root=root):
                self.assertIn(f"{root}/kit/SKILL.md", plan)
        self.assertEqual(self.factory_skills(self.plan({})), [])

    def test_a_skill_without_sessions_never_reaches_the_bundle(self):
        """Characterisation: a skill renders to the bundle only by opting in. Pinned because
        a render must show no change while no skill opts into the factory; since spec-gate
        opts in, the check is on this test's own skill rather than on the bundle being
        empty."""
        self.skill()
        plan = self.plan()
        self.assertFalse([p for p in self.factory_skills(plan) if p.startswith("factory/skills/kit/")])
        self.assertIn(".cursor/skills/kit/SKILL.md", plan)

    def test_a_factory_only_skill_is_not_rendered_for_interactive_tools(self):
        """Intent: "A skill whose sessions: lacks interactive does not
        render to SKILL_ROOTS." """
        self.skill("sessions: [factory]\n")
        plan = self.plan()
        self.assertIn(self.SKILL, plan)
        self.assertFalse([p for p in plan
                          if any(p.startswith(f"{root}/kit/") for root in sync.SKILL_ROOTS)])

    def test_a_factory_skill_carries_its_assets_and_factory_sections_only(self):
        """Intent: it renders "with its bundled assets, in factory mode
        (<!-- mode: --> sections resolved for factory)"."""
        path = self.skill("sessions: [interactive, factory]\n", body=self.BLOCKS)
        (path.parent / "tool.py").write_text("print('x')\n", encoding="utf-8")
        plan = self.plan()
        out = plan[self.SKILL]
        self.assertIn("shared\nthe spec is your grant\n", out)
        self.assertNotIn("ask first", out)
        self.assertTrue(sync.is_stamped(out))
        self.assertIn("print('x')", plan["factory/skills/kit/tool.py"])
        self.assertIn("ask first", plan[".cursor/skills/kit/SKILL.md"])

    def test_a_role_lists_its_skills_in_the_factory_file_only(self):
        """Intent: "render_agent writes the list into the frontmatter of
        factory/rules/<role>.agent.md, which the harness reads." """
        self.skill("sessions: [factory]\n")
        self.agent("skills: [kit]\n")
        plan = self.plan()
        head = plan[self.ROLE].split("\n---\n", 1)[0]
        self.assertEqual(yaml.safe_load(head.lstrip("-\n"))["skills"], ["kit"])
        self.assertNotIn("skills", plan[".github/agents/moded.agent.md"])

    def test_a_role_naming_a_skill_it_cannot_have_refuses(self):
        """Intent: "The render refuses a name that is not a factory
        skill." An interactive skill must never be listed on a headless role."""
        self.skill(name="chat-only")
        cases = {
            "unknown": "skills: [nowhere]\n",
            "interactive only": "skills: [chat-only]\n",
            "not a list": "skills: chat-only\n",
            "duplicate": "skills: [kit, kit]\n",
            "empty": "skills: []\n",
        }
        self.skill("sessions: [factory]\n")
        for case, extra in cases.items():
            with self.subTest(case=case):
                self.agent(extra)
                with self.assertRaises(sync.SyncError) as caught:
                    self.plan({})
                self.assertIn("definition.md: skills:", str(caught.exception))

    def test_a_malformed_skill_sessions_refuses_naming_the_seed(self):
        """Intent: sessions: is "read through the same seed_sessions as
        agent seeds", so a typo refuses rather than rendering a skill nowhere."""
        self.skill("sessions: [headless]\n")
        with self.assertRaises(sync.SyncError) as caught:
            self.plan()
        self.assertIn("procedure.md: sessions:", str(caught.exception))

    def test_a_stale_factory_skill_is_an_orphan(self):
        """Intent: "factory/skills joins RENDER_DIRS, so a removed factory
        skill is found as an orphan." """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            stale = repo / "factory" / "skills" / "retired" / "SKILL.md"
            stale.parent.mkdir(parents=True)
            stale.write_text(f"<!-- {sync.STAMP_MARKER}x -->\n", encoding="utf-8")
            self.assertIn("factory/skills/retired/SKILL.md",
                          sync.find_orphans(repo, self.plan({})))


class GateConfigDir(unittest.TestCase):
    """The folder each repo keeps its gate configuration in is the profile's, and
    no core file names a CI system's folder in its place."""

    # Every location a gate's hand-owned configuration used to be fixed at.
    OLD = re.compile(r"\.github/(test-roots|doc-paths|lint-baseline)")
    # Core files: what ships to every repo and into ai-toolbox. This repo's own tests and
    # test selection read its own .github/, which is this profile's choice, not the core's.
    CORE = ("githooks", "hooks", "skills", "agents", "rules", "context", "sync.py",
            "consent.py", "gate_report.py", "actions", "vendor.py", "setup_profile.py")

    def tearDown(self):
        sync.set_stamp_source(MANIFEST)

    def test_the_gate_config_names_the_profiles_folder(self):
        plan = build_plan("t", {}, DEFAULTS, SHA, MANIFEST)
        self.assertIn(f"config-dir={MANIFEST['gate_config_dir']}\n", plan[".githooks/gate-config"])

    def test_a_profile_without_the_key_refuses_naming_it(self):
        """Intent: no default, because the core names no CI system's folder."""
        manifest = {k: v for k, v in MANIFEST.items() if k != "gate_config_dir"}
        with self.assertRaises(sync.SyncError) as caught:
            build_plan("t", {}, DEFAULTS, SHA, manifest)
        self.assertIn("gate_config_dir", str(caught.exception))

    def test_a_folder_that_leaves_the_repo_refuses(self):
        """Intent: validate every externally supplied value before it reaches a path."""
        for value in ("../x", "/etc", "a/../b", "..", ".", "a b", "", "x\nconfig-dir=y"):
            with self.subTest(value=value), self.assertRaises(sync.SyncError):
                sync.gate_config_dir({"gate_config_dir": value})

    def test_the_hand_owned_files_follow_the_folder(self):
        """Intent: test-roots and doc-paths stay hand-owned wherever the profile keeps them."""
        self.assertLessEqual({".gates/test-roots", ".gates/doc-paths"},
                             sync.never_write({"gate_config_dir": ".gates/"}))

    def test_no_core_file_names_github_as_the_gate_config_location(self):
        """Intent: checked by search."""
        hits = []
        for entry in self.CORE:
            path = sync.ROOT / entry
            files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
            for file in files:
                if "__pycache__" in file.parts:
                    continue
                text = file.read_text(encoding="utf-8", errors="replace")
                hits += [f"{file.relative_to(sync.ROOT)}: {m.group(0)}"
                         for m in self.OLD.finditer(text)]
        self.assertEqual(hits, [])


class GateWireframe(unittest.TestCase):
    """The core's description of a gate names no toolchain and no CI system."""

    PATH = sync.ROOT / "githooks" / "README.md"
    WORDS = ("python", "node", "npm", "pip", "ruff", "eslint", "mypy", "pytest", "jest",
             "tsc", "cargo", "docker", "shellcheck", "gitleaks", "github", "gitlab",
             "actions", "workflow", "jenkins", "circleci", "travis", "azure")

    def named(self, text: str) -> list[str]:
        return [w for w in self.WORDS if re.search(rf"\b{w}\b", text, re.IGNORECASE)]

    def test_the_wireframe_names_no_toolchain_or_ci_system(self):
        """Intent: scanned case-insensitively for a word list held here."""
        self.assertEqual(self.named(self.PATH.read_text(encoding="utf-8")), [])

    def test_a_planted_word_is_found(self):
        """Intent: the scan fails when a listed word is planted in it."""
        text = self.PATH.read_text(encoding="utf-8")
        for word in self.WORDS:
            with self.subTest(word=word):
                self.assertEqual(self.named(f"{text}\nRun it with {word.upper()}.\n"), [word])

    def test_it_states_the_contract(self):
        """Intent: a gate is a script that exits non-zero and says why, and a
        profile declares its gates."""
        text = self.PATH.read_text(encoding="utf-8")
        for phrase in ("Any other exit fails", "what it printed is the reason",
                       "features: gates:", "seeds/githooks/gates/"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


class HiddenPlanPaths(unittest.TestCase):
    """sync.hidden_plan_paths against a real repository's .gitignore."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        git("init", "--quiet", "-b", "main", str(self.repo), cwd=self.repo)
        configure(self.repo)

    def test_an_exact_name_rule_is_seen(self):
        """Intent: every rendered file actually reaches the target. Text-mode stdin sent 'AGENTS.md\\r' on Windows, which an exact-name rule never matches."""
        (self.repo / ".gitignore").write_text("AGENTS.md\n", encoding="utf-8", newline="\n")
        self.assertEqual(sync.hidden_plan_paths(self.repo, {"AGENTS.md": "", "OTHER.md": ""}),
                         ["AGENTS.md"])

    def test_a_tracked_file_under_a_broad_rule_is_not_hidden(self):
        """Intent: the false failure of 2026-09-29 - '*secret*' with an exact-name
        negation for the rendered gate. The negation must match, so nothing is hidden."""
        (self.repo / ".gitignore").write_text("*secret*\n!.githooks/gates/secret-scan.sh\n",
                                              encoding="utf-8", newline="\n")
        gate = self.repo / ".githooks" / "gates" / "secret-scan.sh"
        gate.parent.mkdir(parents=True)
        gate.write_text("x\n", encoding="utf-8", newline="\n")
        self.assertEqual(sync.hidden_plan_paths(self.repo, {".githooks/gates/secret-scan.sh": ""}), [])


# The fixture profile's ghcli: the three names the core's drift dispatch uses, so the
# core's rollout is tested without a profile's real client. _raw is the seam a test fakes.
GHCLI_STUB = '''"""A stand-in for a profile's ghcli, for the core's rollout fixture."""
import subprocess
import types


class GhError(Exception):
    pass


class EstateError(Exception):
    pass


estate_data = types.SimpleNamespace(EstateError=EstateError)


def _raw(args, timeout, env):
    return subprocess.run(("gh", *args), capture_output=True, text=True, timeout=timeout,
                          env=env)


def run(*args, timeout):
    try:
        result = _raw(args, timeout, None)
    except OSError as exc:
        raise GhError(f"gh could not start: {exc}") from exc
    if result.returncode != 0:
        raise GhError(f"gh {' '.join(args)} exited {result.returncode}")
    return result.stdout
'''


def path_without_a_real_gh(entries: list[str]) -> list[str]:
    """PATH entries with every directory that holds a Windows gh.exe left out. A gh with no
    extension is not left out: the fixture's stub gh comes first on PATH and answers instead,
    and on Linux the real gh lives beside git, so dropping its directory would lose git."""
    return [d for d in entries if d and not (Path(d) / "gh.exe").is_file()]


class PathWithoutAGh(unittest.TestCase):
    """Intent: the Rollout fixture hides a real gh from the run, and keeps the rest of PATH.
    On Linux gh and git share /usr/bin, so dropping that directory leaves no git to find."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def folder(self, name: str, *files: str) -> str:
        directory = self.base / name
        directory.mkdir()
        for file in files:
            (directory / file).write_text("", encoding="utf-8")
        return str(directory)

    def test_a_directory_holding_gh_and_git_is_kept(self):
        shared = self.folder("usr-bin", "gh", "git")
        self.assertEqual(path_without_a_real_gh([shared]), [shared])

    def test_a_directory_holding_a_windows_gh_is_dropped(self):
        self.assertEqual(path_without_a_real_gh([self.folder("cli", "gh.exe")]), [])

    def test_a_directory_with_neither_is_kept_and_an_empty_entry_is_dropped(self):
        plain = self.folder("plain", "git")
        self.assertEqual(path_without_a_real_gh(["", plain]), [plain])


class Rollout(unittest.TestCase):
    """`sync.py --rollout SUBJECT` renders and commits every live target.

    The source is a profile repository vendoring a copy of this core under core/, with
    the example profile's seeds, a stub ghcli, and targets that are temporary repositories,
    each with a bare repository as its remote. githooks/ is left out of the core's copy, so
    targets receive no pre-push gates: those gates are not what is under test.
    """

    # Rollout mechanics, not rule content: the render classes above cover content, and
    # this class costs ten minutes, so it does not inherit their list.
    EXERCISES = ["examples/profile/profile.yaml"]

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        source = base / "source"
        listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=sync.ROOT)
        for rel in filter(None, listed.split("\0")):
            if rel.split("/", 1)[0] == "githooks":
                continue
            src = sync.ROOT / rel
            if src.is_file():
                dest = source / "core" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        shutil.copytree(EXAMPLE / "seeds", source / "seeds")
        (source / "ghcli.py").write_text(GHCLI_STUB, encoding="utf-8", newline="\n")
        (source / ".gitignore").write_text("scratch/\n__pycache__/\n", encoding="utf-8",
                                           newline="\n")
        (source / "README.md").write_text("fixture profile\n", encoding="utf-8", newline="\n")
        manifest = {**MANIFEST, "targets": FIXTURE_TARGETS}
        (source / "profile.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False),
                                             encoding="utf-8", newline="\n")
        git("init", "--quiet", "-b", "main", cwd=source)
        configure(source)
        git("add", "-A", cwd=source)
        git("commit", "--quiet", "-m", "fixture source", cwd=source)
        cls.render_self(source)
        cls.origin = base / "origin.git"
        git("clone", "--quiet", "--bare", str(source), str(cls.origin), cwd=base)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @staticmethod
    def render_self(source: Path) -> None:
        """Commit the source's own render, as an operator does before a rollout."""
        result = subprocess.run((sys.executable, "core/sync.py", "--profile", ".", "--self",
                                 "--write", "--no-fetch"),
                                cwd=source, env=clean_env(), capture_output=True, text=True,
                                timeout=300)
        if result.returncode != 0:
            raise AssertionError(f"fixture: self-render failed: {result.stderr}")
        git("add", "-A", cwd=source)
        if git("status", "--porcelain", cwd=source):
            git("commit", "--quiet", "-m", "fixture self-render", cwd=source)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        origin = base / "profile.git"
        git("clone", "--quiet", "--bare", str(self.origin), str(origin), cwd=base)
        self.source = base / "profile"
        git("clone", "--quiet", str(origin), str(self.source), cwd=base)
        configure(self.source)
        self.lock = self.source / "scratch" / "rollout.lock"

        self.root = base / "repos"
        self.remotes = base / "remotes"
        self.root.mkdir()
        self.remotes.mkdir()
        for name in LIVE:
            self.make_target(name, branch_of(name))
        self.initial = {name: self.head(name) for name in LIVE}

        # --push preflight requires shellcheck to resolve; no hook ever runs it here.
        bin_dir = base / "bin"
        bin_dir.mkdir()
        (bin_dir / "shellcheck.cmd").write_text("@exit /b 0\r\n", encoding="utf-8")
        stub = bin_dir / "shellcheck"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        # The fixture keeps the real owner, so an unstubbed gh would trigger real workflow runs.
        # The stub answers ghcli's owner check, so the dispatch after it is what GH_STUB_EXIT fails.
        self.gh_log = bin_dir / "gh.log"
        owner = MANIFEST["source"]["owner"]
        (bin_dir / "gh.cmd").write_text(
            '@echo %*>>"%~dp0gh.log"\r\n'
            '@if "%1 %2"=="auth token" (echo stub-token& exit /b 0)\r\n'
            f'@if "%1 %2"=="api user" (echo {owner}& exit /b 0)\r\n'
            '@if defined GH_STUB_EXIT exit /b %GH_STUB_EXIT%\r\n@exit /b 0\r\n',
            encoding="utf-8")
        gh = bin_dir / "gh"
        gh.write_text('#!/bin/sh\necho "$*" >> "$(dirname "$0")/gh.log"\n'
                      'case "$1 $2" in\n'
                      '  "auth token") echo stub-token; exit 0 ;;\n'
                      f'  "api user") echo {owner}; exit 0 ;;\n'
                      'esac\nexit "${GH_STUB_EXIT:-0}"\n',
                      encoding="utf-8", newline="\n")
        gh.chmod(0o755)
        # ghcli runs gh without PATHEXT, so on Windows it never finds gh.cmd, and a real gh
        # further down PATH would dispatch real workflow runs as the owner. Leave none to find.
        path = path_without_a_real_gh(os.environ.get("PATH", "").split(os.pathsep))
        self.env = clean_env(PATH=os.pathsep.join([str(bin_dir), *path]))

    def make_target(self, name: str, branch: str) -> None:
        remote = self.remotes / f"{name}.git"
        git("init", "--quiet", "--bare", "-b", "main", str(remote), cwd=self.remotes)
        repo = self.root / name
        git("init", "--quiet", "-b", "main", str(repo), cwd=self.root)
        configure(repo)
        (repo / "README.md").write_text(f"{name}\n", encoding="utf-8", newline="\n")
        git("add", "-A", cwd=repo)
        git("commit", "--quiet", "-m", "initial", cwd=repo)
        git("remote", "add", "origin", str(remote), cwd=repo)
        git("push", "--quiet", "-u", "origin", "main", cwd=repo)
        if branch != "main":
            git("checkout", "--quiet", "-b", branch, cwd=repo)
            git("push", "--quiet", "-u", "origin", branch, cwd=repo)

    def rollout(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            (sys.executable, "core/sync.py", "--profile", ".", "--rollout", *args,
             "--root", str(self.root)),
            cwd=self.source, env=self.env, capture_output=True, text=True, timeout=600)

    def rollout_in_process(self, after_target_emit, *args: str, gh_raw=None) -> tuple[int, str, str]:
        """Run the copy's main() with emit wrapped; after_target_emit(repo) runs after
        each write into a target. The ticket routes rendering through emit. gh_raw, if
        given, stands in for every gh process ghcli would start."""
        spec = importlib.util.spec_from_file_location("sync_rollout_fixture",
                                                      self.source / "core" / "sync.py")
        module = importlib.util.module_from_spec(spec)
        # dataclasses resolves string annotations through sys.modules.
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        saved_path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved_path))
        spec.loader.exec_module(module)

        real = module.emit
        signature = inspect.signature(real)
        root = self.root.resolve()

        def emit(*a, **k):
            bound = signature.bind(*a, **k)
            changed = real(*a, **k)
            repo = Path(bound.arguments["repo"]).resolve()
            if bound.arguments["write"] and repo.is_relative_to(root):
                after_target_emit(repo)
            return changed

        out, err = io.StringIO(), io.StringIO()
        argv = ["sync.py", "--profile", str(self.source), "--rollout", *args,
                "--root", str(self.root)]
        with contextlib.ExitStack() as stack:
            if gh_raw is not None:
                sys.modules.pop("ghcli", None)
                ghcli = module.profile_module("ghcli", self.source, "--push")
                self.addCleanup(sys.modules.pop, "ghcli", None)
                stack.enter_context(mock.patch.object(ghcli, "_raw", side_effect=gh_raw))
            stack.enter_context(mock.patch.object(module, "emit", emit))
            stack.enter_context(mock.patch.dict(os.environ, self.env, clear=True))
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            try:
                code = module.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def leave_live_lock(self) -> str:
        """A lock as a rollout writes it, left behind as a killed process leaves it.
        Captured from a real run, so the test assumes nothing about its format."""
        held: dict[str, bytes | None] = {}

        def capture(_repo: Path) -> None:
            held.setdefault("lock", self.lock.read_bytes() if self.lock.is_file() else None)

        code, out, err = self.rollout_in_process(capture, "first")
        self.assertEqual(code, 0, out + err)
        self.assertIsNotNone(held.get("lock"), "no scratch/rollout.lock while a target rendered")
        for name in LIVE:
            repo = self.root / name
            git("reset", "--quiet", "--hard", "@{u}", cwd=repo)
            git("clean", "-q", "-fdx", cwd=repo)
        self.lock.parent.mkdir(exist_ok=True)
        self.lock.write_bytes(held["lock"])
        return str(os.getpid())

    def write_lock(self, started_ago: timedelta, heartbeat_ago: timedelta) -> None:
        """A lock in the rollout's format, held by a process that is alive."""
        now = datetime.now(timezone.utc)
        self.lock.parent.mkdir(exist_ok=True)
        self.lock.write_text(json.dumps({
            "pid": os.getpid(),
            "started": (now - started_ago).isoformat(),
            "heartbeat": (now - heartbeat_ago).isoformat(),
            "subject": "held",
        }), encoding="utf-8")

    def assert_lock_refuses(self, started_ago: timedelta, heartbeat_ago: timedelta) -> None:
        self.write_lock(started_ago, heartbeat_ago)
        before = {name: self.state(name) for name in LIVE}
        result = self.rollout("x")
        self.assertNotEqual(result.returncode, 0,
                            "a lock inside both thresholds was not honoured: " + result.stdout + result.stderr)
        self.assertIn(str(os.getpid()), result.stdout + result.stderr,
                      "the refusal does not name the holder, so the lock may not be why it refused")
        self.assertEqual({name: self.state(name) for name in LIVE}, before, "a target was touched")

    def assert_lock_is_stale(self, started_ago: timedelta, heartbeat_ago: timedelta) -> None:
        self.write_lock(started_ago, heartbeat_ago)
        result = self.rollout("x")
        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         "a stale lock blocked the run: " + result.stdout + result.stderr)
        for name in LIVE:
            self.assertNotEqual(self.head(name), self.initial[name], f"{name} was not committed")

    def head(self, name: str, ref: str = "HEAD") -> str:
        return git("rev-parse", ref, cwd=self.root / name)

    def remote_refs(self, name: str) -> str:
        return git("for-each-ref", cwd=self.remotes / f"{name}.git")

    def state(self, name: str) -> tuple[str, str, str]:
        repo = self.root / name
        return (git("for-each-ref", cwd=repo), git("rev-parse", "HEAD", cwd=repo),
                git("status", "--porcelain", "-uall", cwd=repo))

    @staticmethod
    def summary(stdout: str) -> str:
        lines = stdout.strip().splitlines()
        return lines[-1] if lines else ""

    def test_rollout_reports_each_target(self):
        """Intent: a dirty target is skipped, the rest run, and the
        last line is ROLLOUT COMPLETE in its fixed form; skip: targets are excluded."""
        dirty = self.root / "bravo" / "README.md"
        dirty.write_text("bravo\nlocal edit\n", encoding="utf-8", newline="\n")

        result = self.rollout("x")

        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 2 ok, 1 failed",
                         result.stdout + result.stderr)
        self.assertNotEqual(result.returncode, 0, "a target failed, so the exit code must say so")
        self.assertEqual(self.head("bravo"), self.initial["bravo"])
        self.assertEqual(dirty.read_text(encoding="utf-8"), "bravo\nlocal edit\n")
        for name in ("alpha", "charlie"):
            self.assertNotEqual(self.head(name), self.initial[name], f"{name} was not committed")
        body = result.stdout.strip().splitlines()[:-1]
        for name in LIVE:
            self.assertTrue(any(name in line for line in body), f"no line reports {name}")

    def test_rollout_refuses_path_outside_the_plan(self):
        """Intent: a changed path outside the plan is refused."""
        alpha = (self.root / "alpha").resolve()

        def stray(repo: Path) -> None:
            if repo == alpha:
                (alpha / "stray.txt").write_text("not rendered\n", encoding="utf-8")

        code, out, err = self.rollout_in_process(stray, "x")

        self.assertNotEqual(code, 0, out + err)
        self.assertEqual(self.head("alpha"), self.initial["alpha"], "a path outside the plan was committed")
        self.assertNotEqual(self.head("bravo"), self.initial["bravo"], "one refusal stopped the rest")
        self.assertEqual(self.summary(out), "ROLLOUT COMPLETE: 2 ok, 1 failed", out + err)

    def test_rollout_does_not_push_by_default(self):
        """Intent: commit by default, push only with --push."""
        before = {name: self.remote_refs(name) for name in LIVE}

        result = self.rollout("x")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed")
        for name in LIVE:
            self.assertNotEqual(self.head(name), self.initial[name],
                                f"{name}: nothing committed, so an unchanged remote proves nothing")
            self.assertEqual(self.remote_refs(name), before[name], f"{name} was pushed")

    def test_rollout_failed_push_does_not_stop_the_next_target(self):
        """Intent: with --push, a failing push is reported and the
        next target still runs."""
        git("remote", "set-url", "origin", str(self.remotes / "missing.git"), cwd=self.root / "alpha")

        result = self.rollout("x", "--push")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 2 ok, 1 failed",
                         result.stdout + result.stderr)
        for name in ("bravo", "charlie"):
            self.assertNotEqual(self.head(name), self.initial[name], f"{name} was not committed")
            self.assertEqual(git("rev-parse", f"refs/heads/{branch_of(name)}",
                                 cwd=self.remotes / f"{name}.git"),
                             self.head(name), f"{name} was not pushed")

    def test_rollout_refuses_live_lock(self):
        """Intent: a second invocation while a live lock exists
        exits non-zero and names the holder."""
        holder = self.leave_live_lock()
        before = {name: self.state(name) for name in LIVE}

        result = self.rollout("second")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(holder, result.stdout + result.stderr, "the refusal does not name the holder's pid")
        self.assertEqual({name: self.state(name) for name in LIVE}, before)
        self.lock.unlink()
        self.assertEqual(self.summary(self.rollout("second").stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         "with the lock gone the same run must succeed, or the lock was not the cause")

    def test_rollout_break_lock_clears_a_live_lock(self):
        """Intent: --break-lock clears a lock of any age."""
        self.leave_live_lock()

        result = self.rollout("second", "--break-lock")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed")
        for name in LIVE:
            self.assertNotEqual(self.head(name), self.initial[name], f"{name} was not committed")
        self.assertFalse(self.lock.exists(), "the lock outlived the run that broke it")

    def test_rollout_lock_past_one_hour_from_start_is_stale(self):
        """Intent: a lock more than 1 hour past its start time is
        treated as stale, even with a fresh heartbeat. The control is the same lock
        inside the hour, which must refuse, so ignoring the lock cannot pass."""
        self.assert_lock_refuses(timedelta(minutes=58), timedelta(minutes=1))
        self.assert_lock_is_stale(timedelta(minutes=62), timedelta(minutes=1))

    def test_rollout_lock_without_heartbeat_for_twenty_minutes_is_stale(self):
        """Intent: a lock whose heartbeat is more than 20 minutes
        old is treated as stale, even inside the hour. The control is a heartbeat
        inside 20 minutes, which must refuse."""
        self.assert_lock_refuses(timedelta(minutes=30), timedelta(minutes=18))
        self.assert_lock_is_stale(timedelta(minutes=30), timedelta(minutes=22))

    def test_rollout_refuses_a_target_whose_effective_identity_differs(self):
        """Intent: sync.py --rollout refuses a target whose effective email
        mismatches. An include after the local value wins over what sync sets."""
        alpha = self.root / "alpha"
        override = self.root.parent / "override.gitconfig"
        override.write_text("[user]\n\temail = someone@elsewhere.invalid\n", encoding="utf-8")
        git("config", "--local", "include.path", override.as_posix(), cwd=alpha)

        result = self.rollout("x")

        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 2 ok, 1 failed",
                         result.stdout + result.stderr)
        self.assertEqual(self.head("alpha"), self.initial["alpha"], "a commit landed under the wrong identity")
        self.assertIn("someone@elsewhere.invalid", result.stdout + result.stderr)
        self.assertNotEqual(self.head("bravo"), self.initial["bravo"], "one refusal stopped the rest")

    def test_rollout_commits_as_the_manifest_identity(self):
        """Intent: after a rollout, every target's local identity is the manifest's,
        and the rollout commit carries it."""
        result = self.rollout("x")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = sync.identity(MANIFEST)["email"]
        for name in LIVE:
            repo = self.root / name
            self.assertEqual(git("config", "--local", "user.email", cwd=repo), expected, name)
            self.assertEqual(git("log", "-1", "--format=%ae|%ce", cwd=repo), f"{expected}|{expected}", name)

    def test_rollout_names_the_profile_source(self):
        """Intent: the core derives every name it writes from the
        profile's source.repo, so a rollout's report and commits name the profile, never
        the core's own product."""
        result = self.rollout("x")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        source = MANIFEST["source"]["repo"]
        self.assertTrue(any(line.startswith(f"{source}@") and line.endswith(" rollout: x")
                            for line in result.stdout.splitlines()), result.stdout)
        for name in LIVE:
            body = git("log", "-1", "--format=%b", cwd=self.root / name).strip()
            self.assertTrue(body.startswith(f"From {source}@"), f"{name}: {body!r}")

    def test_rollout_refuses_wrong_branch(self):
        """Intent: a target on the wrong branch is refused, and nothing is committed to
        it. One target in the fixture deploys from dev, not main."""
        charlie = self.root / "charlie"
        git("checkout", "--quiet", "main", cwd=charlie)
        before = self.state("charlie")[:2]

        result = self.rollout("x")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state("charlie")[:2], before, "a commit landed on the wrong branch")
        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 2 ok, 1 failed",
                         result.stdout + result.stderr)
        self.assertNotEqual(self.head("alpha"), self.initial["alpha"], "the other targets did not run")

    def assert_alpha_refused(self, result: subprocess.CompletedProcess, before: tuple, why: str) -> None:
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertEqual(self.state("alpha")[1:], before[1:], "alpha was rendered or committed into")
        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 2 ok, 1 failed", output)
        self.assertIn(why, output)
        self.assertNotEqual(self.head("bravo"), self.initial["bravo"], "one refusal stopped the rest")

    def test_rollout_refuses_a_target_behind_its_upstream(self):
        """Intent: a target behind its upstream is refused before anything
        is rendered or committed, and the refusal names the fix."""
        alpha = self.root / "alpha"
        (alpha / "remote.txt").write_text("on the remote only\n", encoding="utf-8", newline="\n")
        git("add", "-A", cwd=alpha)
        git("commit", "--quiet", "-m", "remote only", cwd=alpha)
        git("push", "--quiet", cwd=alpha)
        git("reset", "--quiet", "--hard", "HEAD~1", cwd=alpha)
        before = self.state("alpha")

        result = self.rollout("x")

        self.assert_alpha_refused(result, before, "git pull --ff-only")

    def test_rollout_refuses_a_target_with_no_upstream(self):
        """Intent: with no upstream there is nothing to compare against, and
        unknown is not current."""
        alpha = self.root / "alpha"
        git("branch", "--unset-upstream", cwd=alpha)
        before = self.state("alpha")

        result = self.rollout("x")

        self.assert_alpha_refused(result, before, "no upstream")

    def test_rollout_refuses_a_target_whose_fetch_fails(self):
        """Intent: a failed fetch cannot show the target is current, so it
        is a refusal, not a pass."""
        alpha = self.root / "alpha"
        git("remote", "set-url", "origin", str(self.remotes / "missing.git"), cwd=alpha)
        before = self.state("alpha")

        result = self.rollout("x")

        self.assert_alpha_refused(result, before, "git fetch")

    def test_rollout_refuses_unpushed_source(self):
        """Intent: if the source is ahead of origin the command
        refuses before touching any target; ensure_current lets that case through."""
        readme = self.source / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nlocal only\n",
                          encoding="utf-8", newline="\n")
        git("commit", "--quiet", "-am", "not on origin", cwd=self.source)
        before = {name: self.state(name) for name in LIVE}

        result = self.rollout("x")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({name: self.state(name) for name in LIVE}, before, "a target was touched")
        git("push", "--quiet", "origin", "main", cwd=self.source)
        self.assertEqual(self.summary(self.rollout("x").stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         "once pushed the same run must succeed, or being ahead was not the cause")

    def test_rollout_refuses_pending_self_render(self):
        """Intent: a pending self-render refuses
        before any target is touched, naming the files."""
        rule = self.source / "core" / "rules" / "prescriptions.md"
        rule.write_text(rule.read_text(encoding="utf-8") + "\n- Fixture rule.\n",
                        encoding="utf-8", newline="\n")
        git("commit", "--quiet", "-am", "source edit, render not committed", cwd=self.source)
        git("push", "--quiet", "origin", "main", cwd=self.source)
        before = {name: self.state(name) for name in LIVE}

        result = self.rollout("x")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({name: self.state(name) for name in LIVE}, before, "a target was touched")
        self.assertIn("AGENTS.md", result.stdout + result.stderr, "the refusal does not name the files")
        self.render_self(self.source)
        git("push", "--quiet", "origin", "main", cwd=self.source)
        self.assertEqual(self.summary(self.rollout("x").stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         "once rendered the same run must succeed, or the render was not the cause")

    def commit_in(self, name: str, rel: str, text: str) -> str:
        repo = self.root / name
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
        git("add", "-A", cwd=repo)
        git("commit", "--quiet", "-m", f"fixture: {rel}", cwd=repo)
        git("push", "--quiet", cwd=repo)
        return self.head(name)

    def test_rollout_fails_a_target_whose_gitignore_hides_a_rendered_file(self):
        """Intent: every rendered file actually reaches the target. One repo's lib/ rule
        hid .githooks/lib/ and the rollout said ok."""
        before = self.commit_in("alpha", ".gitignore", "rules/\n")

        result = self.rollout("x")

        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 2 ok, 1 failed",
                         result.stdout + result.stderr)
        alpha = [line for line in result.stdout.splitlines() if line.startswith("alpha:")]
        self.assertTrue(alpha and ".github/rules/" in alpha[0], result.stdout)
        self.assertEqual(self.head("alpha"), before, "a partial render was committed")

    def test_rollout_does_not_count_cursor_as_hidden(self):
        """Intent: what the source ignores stays ignored. Since 2026-10-09 a blanket .cursor/
        ignore is replaced by the
        rendered-output allowlist (sync.ensure_cursor_tracked) rather than tolerated."""
        self.commit_in("alpha", ".gitignore", ".cursor/\n")

        result = self.rollout("x")

        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         result.stdout + result.stderr)

    def test_rollout_commits_the_rendered_cursor_output(self):
        """Intent: track the rendered Cursor output, so a fresh
        clone carries rules and skills. alpha carries a blanket .cursor/ ignore."""
        self.commit_in("alpha", ".gitignore", ".cursor/\n")

        result = self.rollout("x")

        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         result.stdout + result.stderr)
        for name in LIVE:
            tracked = git("ls-files", ".cursor", cwd=self.root / name).splitlines()
            with self.subTest(target=name):
                self.assertTrue(any(p.startswith(".cursor/rules/") for p in tracked), tracked)
                self.assertTrue(any(p.startswith(".cursor/skills/") for p in tracked), tracked)

    def test_check_reports_drift_in_a_rendered_cursor_file(self):
        """Intent: "A test shows --check reports drift in a rendered
        .cursor/ file". It was skipped as gitignored until then (sync.UNCHECKABLE)."""
        result = self.rollout("x")
        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         result.stdout + result.stderr)
        alpha = self.root / "alpha"
        rule = sorted((alpha / ".cursor" / "rules").glob("*.mdc"))[0]
        rule.write_text(rule.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8",
                        newline="\n")

        check = subprocess.run(
            (sys.executable, "core/sync.py", "--profile", ".", "alpha", "--check", "--no-fetch",
             "--root", str(self.root)),
            cwd=self.source, env=self.env, capture_output=True, text=True, timeout=300)

        self.assertEqual(check.returncode, 1, check.stdout + check.stderr)
        self.assertIn(f"--- {rule.relative_to(alpha).as_posix()}", check.stdout)

    def push_intervals(self, parallel: str) -> list[tuple[float, float]]:
        """Run --rollout --push with a 3 s pre-push hook in each target; return each hook's span."""
        git("config", "rollout.parallel", parallel, cwd=self.source)
        logs = self.root.parent / "hook-logs"
        logs.mkdir()
        py = Path(sys.executable).as_posix()
        for name in LIVE:
            hook = self.root / name / ".git" / "hooks" / "pre-push"
            hook.write_text(
                "#!/bin/sh\n"
                f'log="{logs.as_posix()}/{name}"\n'
                f'"{py}" -c "import time; print(time.time())" >> "$log"\n'
                "sleep 3\n"
                f'"{py}" -c "import time; print(time.time())" >> "$log"\n',
                encoding="utf-8", newline="\n")
            hook.chmod(0o755)

        result = self.rollout("x", "--push")

        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         result.stdout + result.stderr)
        spans = []
        for name in LIVE:
            start, end = (float(t) for t in (logs / name).read_text(encoding="utf-8").split())
            spans.append((start, end))
        return spans

    @staticmethod
    def overlapping(spans: list[tuple[float, float]]) -> bool:
        return any(a[0] < b[1] and b[0] < a[1] for i, a in enumerate(spans) for b in spans[i + 1:])

    def test_rollout_pushes_targets_in_parallel(self):
        """Intent: pushes run side by side, so a rollout costs about
        one repo's gates rather than the sum of all of them."""
        self.assertTrue(self.overlapping(self.push_intervals("3")), "no two pushes overlapped")

    def test_rollout_parallel_one_pushes_one_at_a_time(self):
        """Intent: the configured number is honoured; the control
        that stops test_rollout_pushes_targets_in_parallel passing while ignoring it."""
        self.assertFalse(self.overlapping(self.push_intervals("1")), "pushes overlapped at 1")

    def test_rollout_capacity_is_probed_once_per_machine(self):
        """Intent: a once-per-machine read-only check, not per push or repo, stored so later rollouts reuse it."""
        first = self.rollout("x", "--push")
        self.assertEqual(self.summary(first.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed",
                         first.stdout + first.stderr)
        self.assertIn("set rollout.parallel=", first.stdout)
        self.assertGreaterEqual(int(git("config", "--get", "rollout.parallel", cwd=self.source)), 1)

        second = self.rollout("y", "--push")

        self.assertNotIn("set rollout.parallel=", second.stdout, "capacity was probed again")

    def test_rollout_uses_the_manifest_default_when_capacity_is_unreadable(self):
        """Intent: fall back to a configurable number, 3 to start with, when capacity
        cannot be determined."""
        with mock.patch("os.cpu_count", return_value=None):
            code, out, err = self.rollout_in_process(lambda _repo: None, "x", "--push")

        self.assertEqual(code, 0, out + err)
        self.assertEqual(git("config", "--get", "rollout.parallel", cwd=self.source),
                         str(MANIFEST["rollout"]["parallel_default"]))
        self.assertEqual(MANIFEST["rollout"]["parallel_default"], 3)

    def test_rollout_refuses_an_invalid_parallel_setting(self):
        """Intent: prescriptions - validate every externally supplied value. The setting is
        hand-editable git config."""
        git("config", "rollout.parallel", "lots", cwd=self.source)
        before = {name: self.state(name) for name in LIVE}

        result = self.rollout("x", "--push")

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("rollout.parallel", result.stdout + result.stderr)
        self.assertEqual({name: self.state(name) for name in LIVE}, before, "a target was touched")

    def gh_calls(self) -> list[str]:
        return (self.gh_log.read_text(encoding="utf-8", errors="replace").split("\n")
                if self.gh_log.exists() else [])

    def test_rollout_push_triggers_the_estate_drift_check(self):
        """Intent: with --push, gh receives `workflow run rules-drift.yml`
        once the targets are pushed, so the estate check runs against rendered targets.
        In process with ghcli's gh faked: a subprocess run cannot stub gh on Windows."""
        owner = MANIFEST["source"]["owner"]
        calls: list[tuple[str, ...]] = []

        def gh(args, timeout, env):
            calls.append(args)
            answers = {("auth", "token"): "stub-token", ("api", "user"): owner}
            return subprocess.CompletedProcess(args, 0, answers.get(args[:2], "") + "\n", "")

        code, out, err = self.rollout_in_process(lambda _repo: None, "x", "--push", gh_raw=gh)

        self.assertEqual(self.summary(out), "ROLLOUT COMPLETE: 3 ok, 0 failed", out + err)
        runs = [" ".join(c) for c in calls if c[:2] == ("workflow", "run")]
        self.assertEqual(len(runs), 1, calls)
        self.assertIn("rules-drift.yml", runs[0])
        self.assertIn(f"--repo {owner}/{MANIFEST['source']['repo']}", runs[0])
        lines = out.splitlines()
        pushed = max(i for i, line in enumerate(lines) if ", pushed" in line)
        triggered = next(i for i, line in enumerate(lines) if "drift check triggered" in line)
        self.assertGreater(triggered, pushed, "the check was triggered before every push finished")

    def test_rollout_without_push_does_not_trigger_the_drift_check(self):
        """Intent: without --push nothing reached the remotes, so a
        drift run would check targets that have not changed."""
        result = self.rollout("x")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([c for c in self.gh_calls() if c.strip()], [])

    def test_rollout_reports_a_failed_trigger_without_failing(self):
        """Intent: a failing gh gives one warning line and the exit code
        stays that of the rollout, which had already finished."""
        self.env["GH_STUB_EXIT"] = "1"

        result = self.rollout("x", "--push")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.summary(result.stdout), "ROLLOUT COMPLETE: 3 ok, 0 failed")
        warnings = [line for line in result.stdout.splitlines() if "drift check not triggered" in line]
        self.assertEqual(len(warnings), 1, result.stdout)


class SelfRenderMerge(unittest.TestCase):
    """Branches that each self-render a change to a different source input merge
    without a conflict on the stamp line of every rendered file, and branches that change
    the same lines of the same source input still conflict.

    The source is a profile repository vendoring a copy of this core under core/, built like
    the Rollout fixture's. Three branches leave the base: `logging` and `shell` each append a
    line to a different rule, and `logging-too` appends another line to the same place as
    `logging`. Each is committed, then self-rendered and committed again.
    """

    # A mechanism test over the real renderer, not rule content, so it declares no rule
    # source as exercised: the render classes above cover content.
    EXERCISES = ["examples/profile/profile.yaml"]

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.source = base / "source"
        listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=sync.ROOT)
        for rel in filter(None, listed.split("\0")):
            if rel.split("/", 1)[0] == "githooks":
                continue
            src = sync.ROOT / rel
            if src.is_file():
                dest = cls.source / "core" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        shutil.copytree(EXAMPLE / "seeds", cls.source / "seeds")
        (cls.source / "ghcli.py").write_text(GHCLI_STUB, encoding="utf-8", newline="\n")
        (cls.source / ".gitignore").write_text("scratch/\n__pycache__/\n", encoding="utf-8",
                                               newline="\n")
        (cls.source / "README.md").write_text("fixture profile\n", encoding="utf-8", newline="\n")
        manifest = {**MANIFEST, "targets": FIXTURE_TARGETS}
        (cls.source / "profile.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False),
                                                 encoding="utf-8", newline="\n")
        git("init", "--quiet", "-b", "main", cwd=cls.source)
        configure(cls.source)
        git("add", "-A", cwd=cls.source)
        git("commit", "--quiet", "-m", "fixture source", cwd=cls.source)
        Rollout.render_self(cls.source)
        cls.branch("logging", "spec-logging.md", "A line added on one branch.\n")
        cls.branch("shell", "spec-shell.md", "A line added on another branch.\n")
        cls.branch("logging-too", "spec-logging.md", "A different line, in the same place.\n")

    @classmethod
    def branch(cls, name: str, rule: str, line: str) -> None:
        """A branch from main that appends `line` to a core rule, then self-renders."""
        git("checkout", "--quiet", "-b", name, "main", cwd=cls.source)
        path = cls.source / "core" / "rules" / rule
        path.write_text(path.read_text(encoding="utf-8") + line, encoding="utf-8", newline="\n")
        git("add", "-A", cwd=cls.source)
        git("commit", "--quiet", "-m", f"{name}: source change", cwd=cls.source)
        Rollout.render_self(cls.source)
        git("checkout", "--quiet", "main", cwd=cls.source)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def merge(self, ours: str, theirs: str) -> subprocess.CompletedProcess:
        """Merge branch `theirs` into branch `ours` in a clone, and return git's result."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clone = Path(tmp.name) / "clone"
        git("clone", "--quiet", str(self.source), str(clone), cwd=Path(tmp.name))
        configure(clone)
        git("checkout", "--quiet", "-b", ours, f"origin/{ours}", cwd=clone)
        return subprocess.run(("git", "merge", "--no-edit", f"origin/{theirs}"), cwd=clone,
                              env=clean_env(), capture_output=True, text=True, timeout=120)

    def test_branches_changing_different_source_inputs_merge_without_a_conflict(self):
        result = self.merge("logging", "shell")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_branches_changing_the_same_lines_still_conflict_naming_the_source(self):
        result = self.merge("logging", "logging-too")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("core/rules/spec-logging.md", result.stdout + result.stderr)


class ProfileModules(unittest.TestCase):
    """The core imports no profile code at load, and loads a profile module only for
    the flag that needs it, refusing in one line when the profile ships none."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)
        self.path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), self.path))

    def module(self, rel: str, text: str) -> None:
        path = self.profile / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        name = path.stem
        self.addCleanup(sys.modules.pop, name, None)

    def test_sync_imports_no_profile_module_at_load(self):
        """Intent: the core runs without profile code, so nothing the
        profile ships is imported when sync.py loads."""
        text = (sync.ROOT / "sync.py").read_text(encoding="utf-8")
        self.assertNotIn("\nimport ghcli", text)
        self.assertNotIn("import runner_switch", text)

    def test_a_flag_needing_a_module_the_profile_lacks_refuses_in_one_line(self):
        """Intent: a missing profile module is one clear refusal naming the
        module and the flag, never a traceback."""
        with self.assertRaises(sync.SyncError) as ctx:
            sync.profile_module("ghcli", self.profile, "--push")
        message = str(ctx.exception)
        self.assertIn("ghcli", message)
        self.assertIn("--push", message)
        self.assertNotIn("\n", message)

    def test_a_module_under_seeds_scripts_is_loaded(self):
        """Intent: a profile ships its modules under seeds/scripts/, alone or
        in a package folder."""
        self.module("seeds/scripts/probepkg/core_probe.py", "VALUE = 7\n")
        self.assertEqual(sync.profile_module("core_probe", self.profile, "--x").VALUE, 7)

    def test_a_module_at_the_profile_root_is_loaded(self):
        """Intent: a profile tool that is not rendered into targets sits at the
        profile root."""
        self.module("core_root_probe.py", "VALUE = 8\n")
        self.assertEqual(sync.profile_module("core_root_probe", self.profile, "--x").VALUE, 8)

    def test_a_module_in_two_places_refuses_naming_both(self):
        """Intent: two copies of one module would import whichever sys.path lists
        first, which is a guess."""
        self.module("core_twice.py", "VALUE = 1\n")
        self.module("seeds/scripts/core_twice.py", "VALUE = 2\n")
        with self.assertRaises(sync.SyncError) as ctx:
            sync.profile_module("core_twice", self.profile, "--x")
        self.assertIn(str(self.profile), str(ctx.exception))
        self.assertIn(str(self.profile / "seeds" / "scripts"), str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""The execution plans are machine-checkable, and the runner fails closed.

"follow execution plan gold" is only a reliable instruction if the plan cannot
silently rot. These tests pin:

  * both committed plans are valid (unique ids/orders, known statuses, every
    cited source file exists, 'next' points at an unblocked phase);
  * the validator REJECTS the failure modes that would mislead an executor —
    a duplicate id, a dangling blocker, 'next' on a blocked or done phase, a
    missing doc, an unknown status, a missing key;
  * the runner is read-only (it never writes the paper state it reads);
  * aliases resolve ("bitcoin" -> btc), unknown books exit 2, invalid plans
    exit 1, and no flag can change trading state.

Hermetic: every case that mutates a plan uses a temp root; the paper-state read
is pointed at a temp file too, never at the live book.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import execution_plan as ep  # noqa: E402


def committed(book):
    return json.loads((ROOT / "plans" / f"{book}.json").read_text())


class CommittedPlansTests(unittest.TestCase):
    def test_both_plans_are_valid(self):
        for book in ("gold", "btc"):
            with self.subTest(book=book):
                self.assertEqual(ep.validate(committed(book), ROOT), [])

    def test_plans_cannot_go_live(self):
        for book in ("gold", "btc"):
            plan = committed(book)
            self.assertEqual(plan["verdict"], "NO-GO")
            self.assertEqual(plan["mode_expected"], "FORWARD_TEST")
            rules = " ".join(plan["never"]).lower()
            self.assertIn("never change trading_mode", rules)
            self.assertIn("never", rules)

    def test_next_is_unblocked_and_not_done(self):
        for book in ("gold", "btc"):
            plan = committed(book)
            phase = ep.phase_by_id(plan, plan["next"])
            self.assertNotEqual(phase["status"], "done")
            for blocker in phase["blocked_by"]:
                self.assertEqual(ep.phase_by_id(plan, blocker)["status"], "done")

    def test_every_phase_has_an_exit_gate(self):
        for book in ("gold", "btc"):
            for phase in committed(book)["phases"]:
                self.assertTrue(phase["exit_gate"].strip(), phase["id"])
                self.assertTrue(phase["steps"], phase["id"])

    def test_plan_files_are_documents_not_state(self):
        # A plan must never be the thing a service imports or the deploy gate
        # reads: it is inert for every unit (deploy.sh / autosync.sh assert it).
        for book in ("gold", "btc"):
            self.assertTrue((ROOT / "plans" / f"{book}.json").is_file())


class ValidatorRejectsTests(unittest.TestCase):
    def setUp(self):
        self.plan = committed("gold")

    def broken(self, mutate):
        plan = json.loads(json.dumps(self.plan))
        mutate(plan)
        return ep.validate(plan, ROOT)

    def test_duplicate_phase_id(self):
        def m(p):
            p["phases"][1]["id"] = p["phases"][0]["id"]
        self.assertTrue(any("unique" in x for x in self.broken(m)))

    def test_dangling_blocker(self):
        def m(p):
            p["phases"][1]["blocked_by"] = ["does-not-exist"]
        self.assertTrue(any("unknown phase" in x for x in self.broken(m)))

    def test_self_block(self):
        def m(p):
            p["phases"][0]["blocked_by"] = [p["phases"][0]["id"]]
        self.assertTrue(any("itself" in x for x in self.broken(m)))

    def test_next_on_blocked_phase(self):
        def m(p):
            p["next"] = "breakout-b-test"      # blocked by phase 1, which is active
        self.assertTrue(any("blocked by" in x for x in self.broken(m)))

    def test_next_on_done_phase(self):
        def m(p):
            p["phases"][0]["status"] = "done"
            p["next"] = "breakout-b-protocol"
        self.assertTrue(any("already done" in x for x in self.broken(m)))

    def test_unknown_status(self):
        def m(p):
            p["phases"][0]["status"] = "nearly done"
        self.assertTrue(any("status" in x for x in self.broken(m)))

    def test_missing_source_file(self):
        def m(p):
            p["phases"][0]["sources"] = ["docs/this_was_deleted.md"]
        self.assertTrue(any("source file missing" in x for x in self.broken(m)))

    def test_missing_required_key(self):
        def m(p):
            del p["phases"][0]["exit_gate"]
        self.assertTrue(any("missing" in x for x in self.broken(m)))

    def test_done_phase_with_open_blocker(self):
        def m(p):
            p["phases"][1]["status"] = "done"   # blocked by the still-active phase 1
        self.assertTrue(any("blocker" in x for x in self.broken(m)))

    def test_garbage_verdict_and_empty_rules(self):
        def m(p):
            p["verdict"] = "probably fine"
            p["never"] = []
        problems = self.broken(m)
        self.assertTrue(any("verdict" in x for x in problems))
        self.assertTrue(any("never" in x for x in problems))

    def test_validate_list_is_empty_for_a_clean_plan(self):
        self.assertEqual(ep.validate(json.loads(json.dumps(self.plan)), ROOT), [])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "plans").mkdir()
        (self.root / "logs").mkdir()
        for book in ("gold", "btc"):
            src = committed(book)
            src["paths"]["paper_state"] = "logs/paper_account.json"
            src["paths"]["live_status"] = "logs/live_status.json"
            (self.root / "plans" / f"{book}.json").write_text(json.dumps(src))
        # Every cited doc must exist under the temp root for validation.
        for book in ("gold", "btc"):
            for phase in committed(book)["phases"]:
                for rel in phase["sources"]:
                    path = self.root / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
        self.state = {"closed": 80, "balance": 239.58, "wins": 19, "losses": 61,
                      "position": None, "updated_at": "2026-10-28 19:32:30"}
        (self.root / "logs" / "paper_account.json").write_text(json.dumps(self.state))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        # --root keeps it on the temp copy; redirect keeps the gate output clean.
        with contextlib.redirect_stdout(io.StringIO()):
            return ep.main([*argv, "--root", str(self.root)])

    def test_aliases(self):
        self.assertEqual(ep.resolve_book("gold"), "gold")
        for alias in ("btc", "bitcoin", "BTCUSD", " Bitcoin "):
            self.assertEqual(ep.resolve_book(alias), "btc", alias)
        with self.assertRaises(SystemExit):
            ep.resolve_book("ethereum")

    def test_default_brief_prints_next_phase_and_rules(self):
        plan = ep.load("btc", self.root)
        state = ep.paper_state(plan, self.root)
        text = ep.render_brief(plan, state, "FORWARD_TEST")
        self.assertIn("NEXT PHASE  1. Pre-register a new BTC hypothesis", text)
        self.assertIn("exit gate", text)
        self.assertIn("HARD RULES", text)
        self.assertIn("Never change TRADING_MODE", text)

    def test_brief_reports_paper_state_and_staleness(self):
        plan = ep.load("gold", self.root)
        fresh = ep.paper_state(plan, self.root)
        self.assertEqual(fresh["closed"], 80)
        self.assertFalse(fresh["stale"])
        stub = dict(fresh, stale=True)
        self.assertIn("STALE", ep.render_brief(plan, stub, "FORWARD_TEST"))

    def test_missing_paper_state_is_unknown_not_zero(self):
        (self.root / "logs" / "paper_account.json").unlink()
        plan = ep.load("gold", self.root)
        state = ep.paper_state(plan, self.root)
        self.assertIn("error", state)
        self.assertIn("UNKNOWN", ep.render_brief(plan, state, "FORWARD_TEST"))

    def test_runner_is_read_only(self):
        before = (self.root / "logs" / "paper_account.json").read_bytes()
        self.assertEqual(self.run_cli("gold", "--status"), 0)
        self.assertEqual(self.run_cli("gold", "--list"), 0)
        self.assertEqual(self.run_cli("gold", "--json"), 0)
        self.assertEqual(before, (self.root / "logs" / "paper_account.json").read_bytes())
        self.assertEqual(sorted(p.name for p in (self.root / "logs").iterdir()),
                         ["paper_account.json"])

    def test_exit_codes(self):
        self.assertEqual(self.run_cli("--validate"), 0)
        (self.root / "plans" / "gold.json").write_text('{"book": "gold"}')
        self.assertEqual(self.run_cli("--validate"), 1)
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli("ethereum")
        self.assertIn("unknown book", str(ctx.exception))

    def test_json_output_is_resolved_and_serialisable(self):
        plan = ep.load("gold", self.root)
        payload = ep.resolved(plan, ep.paper_state(plan, self.root), "FORWARD_TEST")
        text = json.dumps(payload, indent=2)
        reloaded = json.loads(text)
        self.assertEqual(reloaded["next"]["id"], plan["next"])
        self.assertEqual(reloaded["verdict"], "NO-GO")
        self.assertEqual(reloaded["paper_state"]["closed"], 80)


if __name__ == "__main__":
    unittest.main()

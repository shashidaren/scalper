"""Read-only readiness view: published counts are not approval gates.

The tab serves two documents from one route: gold's roadmap and BTC's roadmap.
The tests below pin three properties that matter more than the wording:

  * fail-closed — an unreadable/invalid paper state shows "unknown", never
    "done", and the route writes nothing;
  * separate gates — a BTC instance renders BTC's own gates and must not show
    gold's 300-trade reference or gold's phases; gold must not pick up BTC's;
  * no auto-approval — a closed count above any reference stays NO-GO.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard
from fastapi.testclient import TestClient

GOLD_ONLY_PHRASES = (
    '300+ trades',
    '300-count reference',
    'BREAKOUT-B',
    'Roadmap status is a documented baseline, last reviewed 27 October',
)
BTC_ONLY_PHRASES = (
    'BTCUSD',
    'Phase 1c',
    'donchian',
    'Qualifying forward evidence',
)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patchers = [patch.object(dashboard, 'LOG_DIR', self.root)]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        self.tmp.cleanup()

    def state(self, **changes):
        data = dict(closed=69, balance=294.10, updated_at='2026-10-26 14:20:04',
                    wins=19, losses=50)
        data.update(changes)
        (self.root / 'paper_account.json').write_text(json.dumps(data))

    # --- gold -------------------------------------------------------------
    def test_missing_and_invalid_snapshot_fail_closed(self):
        self.assertEqual(dashboard.readiness_context()['book'], 'gold')
        self.assertIsNone(dashboard.readiness_context()['snapshot'])
        for changes in (dict(closed=-1), dict(closed=True), dict(balance=float('nan')),
                        dict(updated_at='not a date')):
            self.state(**changes)
            self.assertIsNone(dashboard.readiness_context()['snapshot'])

    def test_route_read_only_and_no_auto_approval(self):
        self.state(closed=500)
        before = (self.root / 'paper_account.json').read_bytes()
        with TestClient(dashboard.app) as client:
            response = client.get('/readiness')
        self.assertEqual(response.status_code, 200)
        self.assertIn('LIVE: NO-GO', response.text)
        self.assertIn('500 closed', response.text)
        self.assertIn('0 to the 300-count reference', response.text)
        self.assertEqual(before, (self.root / 'paper_account.json').read_bytes())
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_gold_page_does_not_show_btc_gates(self):
        with TestClient(dashboard.app) as client:
            text = client.get('/readiness').text
        for phrase in BTC_ONLY_PHRASES:
            self.assertNotIn(phrase, text)
        self.assertIn('Readiness</a>', text)   # tab is present for both books

    # --- btc --------------------------------------------------------------
    def test_btc_does_not_inherit_gold_gates(self):
        with patch.object(dashboard.config, 'SYMBOL', 'BTCUSD'):
            context = dashboard.readiness_context()
            with TestClient(dashboard.app) as client:
                text = client.get('/readiness').text
        self.assertEqual(context['book'], 'btc')
        for phrase in GOLD_ONLY_PHRASES:
            self.assertNotIn(phrase, text)
        self.assertIn('Bitcoin (BTCUSD)', text)
        self.assertIn('LIVE: NO-GO', text)
        # BTC-specific evidence, not gold's phases.
        self.assertIn('Phase 1c', text)
        self.assertIn('f7305461', text)

    def test_btc_has_no_reference_countdown(self):
        self.state(closed=141, balance=276.91)
        with patch.object(dashboard.config, 'SYMBOL', 'BTCUSD'):
            snapshot = dashboard.readiness_context()['snapshot']
        self.assertIsNone(snapshot['reference'])
        self.assertIsNone(snapshot['remaining'])
        with patch.object(dashboard.config, 'SYMBOL', 'BTCUSD'):
            with TestClient(dashboard.app) as client:
                text = client.get('/readiness').text
        self.assertIn('141 closed', text)
        self.assertIn('276.91', text)
        self.assertIn('no reference countdown', text.lower())

    def test_btc_wins_losses_optional(self):
        self.state(closed=141, balance=276.91)
        del_wins = json.dumps(dict(closed=141, balance=276.91,
                                   updated_at='2026-10-26 14:20:04'))
        (self.root / 'paper_account.json').write_text(del_wins)
        with patch.object(dashboard.config, 'SYMBOL', 'BTCUSD'):
            snapshot = dashboard.readiness_context()['snapshot']
            with TestClient(dashboard.app) as client:
                text = client.get('/readiness').text
        self.assertIsNone(snapshot['wins'])
        self.assertNotIn('NoneW', text)
        self.assertIn('141 closed', text)

    def test_unknown_symbol_gets_no_roadmap(self):
        with patch.object(dashboard.config, 'SYMBOL', 'EURUSD'):
            context = dashboard.readiness_context()
            with TestClient(dashboard.app) as client:
                text = client.get('/readiness').text
        self.assertEqual(context['book'], 'other')
        self.assertIn('NO ROADMAP FOR THIS INSTANCE', text)
        for phrase in GOLD_ONLY_PHRASES:
            self.assertNotIn(phrase, text)


if __name__ == '__main__':
    unittest.main()

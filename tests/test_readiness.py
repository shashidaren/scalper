"""Read-only readiness view: published counts are not approval gates."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard
from fastapi.testclient import TestClient


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patcher = patch.object(dashboard, 'LOG_DIR', self.root)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def state(self, **changes):
        data = dict(closed=69, balance=294.10, updated_at='2026-10-26 14:20:04')
        data.update(changes)
        (self.root / 'paper_account.json').write_text(json.dumps(data))

    def test_missing_and_invalid_snapshot_fail_closed(self):
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

    def test_btc_does_not_inherit_gold_gates(self):
        with patch.object(dashboard.config, 'SYMBOL', 'BTCUSD'):
            with TestClient(dashboard.app) as client:
                text = client.get('/readiness').text
        self.assertIn('applies to Gold only', text)
        self.assertNotIn('300+ trades', text)


if __name__ == '__main__':
    unittest.main()

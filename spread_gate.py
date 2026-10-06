"""Entry-gate feasibility monitor: is the spread gate even passable?

Why this exists
---------------
The engine refuses to enter while `spread_points > config.MAX_SPREAD_POINTS`
(`run.py`) and logs one `SKIP high_spread` line per cycle. When the gate is
*below the instrument's typical spread* that veto is permanent: the bot stays
connected, keeps polling, never evaluates a signal, and the only clue is a log
line that looks like normal market noise. That is exactly how the BTC instance
sat with 0 trades at ~4,000-point quotes against the `MAX_SPREAD_POINTS=1500`
placeholder (btc/HANDOFF.md §9).

"Gate is below the typical spread" is a configuration/feasibility fact, not a
market condition, and it can be measured: count quotes, count vetoes, look at
the spread distribution. This module does that in one place, shared by the live
engine (`run.py`), the dashboard (`logger.update_live_status` -> live_status.json)
and the pre-start probe (`btc/preflight.py`), so all three tell the same story.

Pure standard library, no config import, no MT5 - unit-testable offline
(`research/../tests` style: see `btc/preflight_test.py` and `btc/e2e_smoke.py`).

Verdicts
--------
* `infeasible` - every quote in the window was vetoed (>= `warn_after` samples).
  No entry is possible with this configuration; it is not a quiet market.
* `starved`    - >= `starve_pct` of quotes vetoed but not all: entries are
  possible in principle but essentially never happen.
Both are reported, never acted on: this module never changes the gate. Choosing
a gate is a research decision (btc/HANDOFF.md §5), not an engine decision.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime


class SpreadGateMonitor:
    def __init__(self, max_spread_points, window: int = 120, warn_after: int = 8,
                 rewarn_every: int = 240, starve_pct: float = 95.0,
                 symbol: str = ""):
        self.max_spread_points = float(max_spread_points)
        self.window = int(window)
        self.warn_after = int(warn_after)
        self.rewarn_every = int(rewarn_every)
        self.starve_pct = float(starve_pct)
        self.symbol = symbol
        self._recent = deque(maxlen=self.window)      # bool: quote passed the gate
        self._spreads = deque(maxlen=self.window)     # observed spread points
        self.samples = 0
        self.passed = 0
        self.vetoed = 0
        self.consecutive_vetoes = 0
        self.first_sample_at = None
        self.last_sample_at = None
        self.last_pass_at = None
        self._state = "ok"        # ok | starved | infeasible
        self._warned_state = "ok"  # last state a WARNING was emitted for
        self._was_bad = False
        self._since_warn = 0

    # -- recording ---------------------------------------------------------
    def observe(self, spread_points) -> bool:
        """Record one quote. Returns True when the gate lets it through."""
        try:
            sp = float(spread_points)
        except (TypeError, ValueError):
            return False
        passed = sp <= self.max_spread_points
        self.samples += 1
        self._recent.append(passed)
        self._spreads.append(sp)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.first_sample_at is None:
            self.first_sample_at = now
        self.last_sample_at = now
        if passed:
            self.passed += 1
            self.consecutive_vetoes = 0
            self.last_pass_at = now
        else:
            self.vetoed += 1
            self.consecutive_vetoes += 1
        self._since_warn += 1
        self._note_state()
        return passed

    # -- verdicts ----------------------------------------------------------
    @property
    def veto_pct(self) -> float:
        return 100.0 * self.vetoed / self.samples if self.samples else 0.0

    @property
    def window_veto_pct(self) -> float:
        if not self._recent:
            return 0.0
        return 100.0 * sum(1 for p in self._recent if not p) / len(self._recent)

    @property
    def infeasible(self) -> bool:
        """No quote has EVER passed the gate in this run (>= warn_after samples).

        An absolute statement about the configuration, not about the last few
        minutes: as soon as a single quote passes, entries are possible and the
        verdict downgrades to `starved` (or `ok`). `last_pass_at`/`window_veto_pct`
        carry the recency information for the dashboard.
        """
        return self.samples >= self.warn_after and self.passed == 0

    @property
    def starved(self) -> bool:
        return (self.samples >= self.warn_after and not self.infeasible
                and self.veto_pct >= self.starve_pct)

    @property
    def ever_bad(self) -> bool:
        """True once the gate has been starved/infeasible at any point."""
        return self._was_bad

    @property
    def state(self) -> str:
        if self.infeasible:
            return "infeasible"
        if self.starved:
            return "starved"
        return "ok"

    def spread_stats(self) -> dict:
        if not self._spreads:
            return {}
        s = sorted(self._spreads)
        n = len(s)
        return {
            "min": s[0],
            "median": s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2]),
            "max": s[-1],
            "window": n,
        }

    # -- reporting ---------------------------------------------------------
    def _note_state(self):
        st = self.state
        if st != "ok":
            self._was_bad = True
        self._state = st

    def warn_now(self) -> bool:
        """True when the engine should emit a one-line WARNING right now.

        Fires on the transition into `starved`/`infeasible`, then at most once
        per `rewarn_every` samples while the state stays bad - so a permanently
        impossible gate cannot flood the log the way the per-cycle SKIP line
        does, but a worsening condition is still reported promptly.
        """
        if self.samples < self.warn_after:
            return False
        state = self.state
        if state == "ok":
            self._warned_state = "ok"        # re-entering a bad state warns again
            return False
        if state != self._warned_state or self._since_warn >= self.rewarn_every:
            self._warned_state = state
            self._since_warn = 0
            return True
        return False

    def recovered_now(self) -> bool:
        """True once, when a previously starved/infeasible gate starts passing."""
        if self._was_bad and self.state == "ok":
            self._was_bad = False
            return True
        return False

    def warning_message(self, symbol: str = "") -> str:
        sym = symbol or self.symbol or "this instrument"
        st = self.spread_stats()
        head = ("SPREAD GATE INFEASIBLE" if self.infeasible
                else "SPREAD GATE STARVED")
        tail = ("No entry is possible with this configuration - the gate sits below "
                "the instrument's typical spread. This is a config/feasibility "
                "problem, not a quiet market; do not read 0 trades as 'no signal'."
                if self.infeasible else
                "Entries are technically possible but essentially never happen.")
        return (f"{head}: {self.samples} of the last {self.samples} {sym} quotes "
                f"exceeded MAX_SPREAD_POINTS={self.max_spread_points:g} "
                f"({self.veto_pct:.1f}% vetoed; window spread min/median/max = "
                f"{st.get('min', 0):.0f}/{st.get('median', 0):.0f}/{st.get('max', 0):.0f} pts). "
                f"{tail}")

    def status(self) -> dict:
        """JSON-serialisable snapshot for live_status.json / the dashboard."""
        st = self.spread_stats()
        return {
            "gate": self.max_spread_points,
            "samples": self.samples,
            "passed": self.passed,
            "vetoed": self.vetoed,
            "veto_pct": round(self.veto_pct, 2),
            "window_veto_pct": round(self.window_veto_pct, 2),
            "consecutive_vetoes": self.consecutive_vetoes,
            "min": st.get("min"), "median": st.get("median"), "max": st.get("max"),
            "window": st.get("window", 0),
            "state": self._state,
            "infeasible": self.infeasible,
            "starved": self.starved,
            "ever_bad": self._was_bad,
            "first_sample_at": self.first_sample_at,
            "last_sample_at": self.last_sample_at,
            "last_pass_at": self.last_pass_at,
        }


def summarise(max_spread_points, spreads, symbol: str = "") -> dict:
    """One-shot verdict over an iterable of spread quotes (used by preflight)."""
    spreads = list(spreads)
    mon = SpreadGateMonitor(max_spread_points, window=max(1, len(spreads)),
                            warn_after=1, symbol=symbol)
    for sp in spreads:
        mon.observe(sp)
    return mon.status()

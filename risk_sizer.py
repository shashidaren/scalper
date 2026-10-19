"""Position sizing by % of account balance — LIVE only.

Ported from gold-trading-bot's `size_lots()` (2026-10-17 pre-registration,
deployed then corrected). The important part of that history is *where* it
applies:

  * **LIVE** sizes off the broker balance, so the risk per trade is a fixed
    fraction of the account instead of a fixed lot count that means a different
    amount of money at every price and volatility.
  * **FORWARD_TEST / paper does NOT use this.** Gold replayed the %-risk rule on
    its own ledger balance and it skipped 76-91% of setups (the required lot
    fell below `volume_min`), which is a flow stop and a confound for the
    experiment, not an R-invariant no-op. The paper book keeps `LOT_SIZE`.

`RISK_PCT = 0` (the default) disables this module entirely: the engine keeps
sending `config.LOT_SIZE`, exactly as before the port.

The one deliberate difference from gold's implementation: this version FLOORS
to `volume_step` instead of rounding to nearest. Rounding to nearest can round
*up*, which would put more than `RISK_PCT` of the balance at risk on the trades
where it matters most (the wider stops). A risk cap should never round upward.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Sizing:
    """Outcome of one sizing decision.

    lots is None when the trade must be skipped; `reason` then says why and the
    caller logs it instead of sending an order.
    """
    lots: float | None
    reason: str
    risk_usd: float = 0.0        # budget: balance * risk_pct / 100
    actual_risk_usd: float = 0.0  # risk actually taken at `lots`
    risk_per_lot_usd: float = 0.0


def _positive(x):
    try:
        return float(x) > 0.0 and float(x) == float(x) and abs(float(x)) != float("inf")
    except (TypeError, ValueError):
        return False


def _floor_to_step(value, step):
    if step <= 0:
        return value
    # 1e-9 guards the classic 0.06999999999 / 0.07 float truncation.
    return int((value + 1e-9) / step) * step


def size_lots(balance, stop_price_distance, contract_size, risk_pct,
              volume_step=0.01, volume_min=0.01, volume_max=None):
    """Lots that risk `risk_pct` % of `balance` over `stop_price_distance`.

    Returns a Sizing. `lots is None` means: do not trade.

    stop_price_distance is in price units (the same units the SL is set in), so
    risk_per_lot = distance * contract_size. For XAUUSD 0.01 lots that is
    distance * 100 * 0.01 = $1 per $1 of stop distance, which is why a $3 stop
    at 0.01 lots risks $3.
    """
    if not _positive(risk_pct):
        return Sizing(None, "risk_pct_disabled")
    if not _positive(balance):
        # LIVE must refuse rather than guess: an unavailable balance means the
        # account info call failed, not that the account is empty.
        return Sizing(None, "balance_unavailable")
    if not _positive(stop_price_distance):
        return Sizing(None, "stop_distance_invalid")
    if not _positive(contract_size):
        return Sizing(None, "contract_size_invalid")

    risk_usd = float(balance) * float(risk_pct) / 100.0
    risk_per_lot = float(stop_price_distance) * float(contract_size)
    raw_lots = risk_usd / risk_per_lot

    step = float(volume_step) if _positive(volume_step) else 0.01
    lots = round(_floor_to_step(raw_lots, step), 8)

    vmin = float(volume_min) if _positive(volume_min) else step
    if lots < vmin - 1e-12:
        return Sizing(None, "below_volume_min", risk_usd, 0.0, risk_per_lot)
    if volume_max is not None and _positive(volume_max) and lots > float(volume_max):
        lots = round(_floor_to_step(float(volume_max), step), 8)

    return Sizing(
        lots=lots,
        reason="ok",
        risk_usd=risk_usd,
        actual_risk_usd=lots * risk_per_lot,
        risk_per_lot_usd=risk_per_lot,
    )

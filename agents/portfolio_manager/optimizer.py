import dataclasses
from dataclasses import dataclass
from datetime import date
from agents.portfolio_manager.reconciler_agent import (
    ReconcilerOutput, ReconcilerResult, CurrentPosition, ExitedPosition
)
from runs.io import load_json, save_json


@dataclass
class BuyOrder:
    symbol: str
    sector: str
    shares: int
    position_size: float    # $ value
    position_pct: float     # % of NAV
    stop_price: float
    stop_pct: float
    target_price: float
    target_pct: float
    confidence: float

    def __str__(self) -> str:
        return (
            f"BUY  {self.symbol:<6} | {self.shares} shares @ ${self.position_size:,.0f}"
            f" ({self.position_pct:.1%} NAV)"
            f" | stop={self.stop_pct:+.1f}%  target={self.target_pct:+.1f}%"
            f" | conf={self.confidence:.0%}"
        )


@dataclass
class SellOrder:
    symbol: str
    shares: float
    market_value: float
    unrealized_plpc: float
    reason: str

    def __str__(self) -> str:
        return (
            f"SELL {self.symbol:<6} | {self.shares:.0f} shares"
            f" @ ${self.market_value:,.0f}"
            f" | P&L={self.unrealized_plpc:+.1%}  reason={self.reason}"
        )


@dataclass
class OptimizerOutput:
    buys: list[BuyOrder]
    sells: list[SellOrder]

    def __str__(self) -> str:
        lines = [f"=== {len(self.sells)} sells, {len(self.buys)} buys ==="]
        for o in self.sells:
            lines.append(str(o))
        if self.sells and self.buys:
            lines.append("")
        for o in self.buys:
            lines.append(str(o))
        return "\n".join(lines)


class Optimizer:
    """
    Risk desk — reads pm_decisions.json + risk_data.json, enforces hard
    limits, sizes positions, and writes orders.json.

    The PM (ReconcilerAgent) has already decided WHAT to buy and sell.
    This class only decides HOW MUCH, subject to hard constraints:
      1. max_positions    — total open positions (holds + new buys)
      2. max_sector_pct  — NAV % in any one sector
      3. max_position_pct — NAV % in any one name
      4. cash_reserve    — minimum uninvested cash
    """

    def __init__(
        self,
        nav: float,
        risk_per_trade: float = 0.01,
        max_positions: int = 15,
        max_sector_pct: float = 0.25,
        max_position_pct: float = 0.10,
        scale_by_confidence: bool = True,
        min_confidence: float = 0.60,
    ):
        self.nav = nav
        self.risk_per_trade = risk_per_trade
        self.max_positions = max_positions
        self.max_sector_pct = max_sector_pct
        self.max_position_pct = max_position_pct
        self.scale_by_confidence = scale_by_confidence
        self.min_confidence = min_confidence

    def _size_shares(self, confidence: float, stop_dist: float, price: float) -> int:
        risk_dollars = self.nav * self.risk_per_trade

        if self.scale_by_confidence and (1.0 - self.min_confidence) > 0:
            scale = 0.5 + 0.5 * (confidence - self.min_confidence) / (1.0 - self.min_confidence)
            scale = max(0.5, min(1.0, scale))
            risk_dollars *= scale

        shares_by_risk = int(risk_dollars / stop_dist) if stop_dist > 0 else 0
        shares_by_pct = int((self.nav * self.max_position_pct) / price) if price > 0 else 0
        return min(shares_by_risk, shares_by_pct)

    def _load_pm_decisions(self, run_date: date | None) -> ReconcilerOutput:
        pm = load_json("pm_decisions", run_date)

        buys = [
            ReconcilerResult(
                symbol=b["symbol"],
                confidence=b["confidence"],
                pm_reasoning=b["pm_reasoning"],
                sector=b.get("sector", "Unknown"),
                stop_price=b.get("stop_price", 0.0),
                stop_pct=b.get("stop_pct", 0.0),
                target_price=b.get("target_price", 0.0),
                target_pct=b.get("target_pct", 0.0),
                atr=b.get("atr", 0.0),
                max_hold_days=b.get("max_hold_days", 20),
            )
            for b in pm["buys"]
        ]
        exits = [ExitedPosition(**e) for e in pm["exits"]]
        holds = [CurrentPosition(**h) for h in pm["holds"]]

        return ReconcilerOutput(
            buys=buys,
            exits=exits,
            holds=holds,
            investable_capital=pm["investable_capital"],
            pm_reasoning=pm["pm_reasoning"],
        )

    def run(self, run_date: date | None = None) -> OptimizerOutput:
        output = self._load_pm_decisions(run_date)

        # --- Sells: all exits with their specific reason ---
        sells = [
            SellOrder(
                symbol=p.symbol,
                shares=p.qty,
                market_value=p.market_value,
                unrealized_plpc=p.unrealized_plpc,
                reason=p.exit_reason,
            )
            for p in output.exits
        ]

        # --- Track constraint state ---
        slots_used = len(output.holds)
        deployed = 0.0

        sector_allocated: dict[str, float] = {}
        for p in output.holds:
            sector_allocated[p.symbol] = sector_allocated.get(p.symbol, 0.0) + p.market_value

        investable = output.investable_capital

        # --- Buys: size each PM-approved candidate, enforce hard limits ---
        buys: list[BuyOrder] = []

        for result in output.buys:

            if slots_used >= self.max_positions:
                print(f"[risk] {result.symbol} skipped — max positions reached")
                continue

            if deployed >= investable:
                print(f"[risk] {result.symbol} skipped — investable capital exhausted")
                break

            symbol = result.symbol
            sector = result.sector
            stop_dist = 2.0 * result.atr
            price = result.stop_price + stop_dist

            if stop_dist <= 0 or price <= 0:
                print(f"[risk] {symbol} skipped — bad risk data")
                continue

            shares = self._size_shares(result.confidence, stop_dist, price)
            if shares <= 0:
                continue

            position_value = shares * price

            # Hard limit: sector cap — trim rather than skip entirely
            current_sector_value = sector_allocated.get(sector, 0.0)
            sector_budget = self.nav * self.max_sector_pct - current_sector_value
            if sector_budget <= 0:
                print(f"[risk] {symbol} skipped — {sector} sector at cap")
                continue
            if position_value > sector_budget:
                shares = int(sector_budget / price)
                if shares <= 0:
                    print(f"[risk] {symbol} skipped — {sector} sector nearly full")
                    continue
                position_value = shares * price
                print(f"[risk] {symbol} trimmed to {shares} shares — {sector} sector cap")

            # Hard limit: remaining cash budget
            budget_left = investable - deployed
            if position_value > budget_left:
                shares = int(budget_left / price)
                if shares <= 0:
                    break
                position_value = shares * price

            buys.append(BuyOrder(
                symbol=symbol,
                sector=sector,
                shares=shares,
                position_size=round(position_value, 2),
                position_pct=round(position_value / self.nav, 4),
                stop_price=result.stop_price,
                stop_pct=result.stop_pct,
                target_price=result.target_price,
                target_pct=result.target_pct,
                confidence=result.confidence,
            ))

            sector_allocated[sector] = current_sector_value + position_value
            deployed += position_value
            slots_used += 1

        result_output = OptimizerOutput(buys=buys, sells=sells)
        save_json("orders", dataclasses.asdict(result_output))
        return result_output


if __name__ == "__main__":
    optimizer = Optimizer(nav=100_000)
    result = optimizer.run()
    print(result)

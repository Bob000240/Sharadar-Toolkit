from dataclasses import dataclass
from agents.portfolio_manager.reconciler_agent import ReconcilerOutput, CurrentPosition


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
    Risk desk — enforces hard limits and sizes positions.

    The PM (ReconcilerAgent) has already decided WHAT to buy and sell.
    This class only decides HOW MUCH, subject to hard constraints:
      1. max_positions    — total open positions (holds + new buys)
      2. max_sector_pct  — NAV % in any one sector
      3. max_position_pct — NAV % in any one name
      4. cash_reserve    — minimum uninvested cash

    Sizing: fixed-fractional risk (1% NAV risked per trade by default),
    optionally scaled by analyst confidence.
    """

    def __init__(
        self,
        nav: float,
        risk_per_trade: float = 0.01,
        max_positions: int = 15,
        max_sector_pct: float = 0.25,
        max_position_pct: float = 0.10,
        cash_reserve: float = 0.20,
        scale_by_confidence: bool = True,
        min_confidence: float = 0.60,
    ):
        self.nav = nav
        self.risk_per_trade = risk_per_trade
        self.max_positions = max_positions
        self.max_sector_pct = max_sector_pct
        self.max_position_pct = max_position_pct
        self.cash_reserve = cash_reserve
        self.scale_by_confidence = scale_by_confidence
        self.min_confidence = min_confidence

    def _size_shares(self, confidence: float, stop_dist: float, price: float) -> int:
        """Fixed-fractional sizing, optionally scaled by confidence."""
        risk_dollars = self.nav * self.risk_per_trade

        if self.scale_by_confidence and (1.0 - self.min_confidence) > 0:
            scale = 0.5 + 0.5 * (confidence - self.min_confidence) / (1.0 - self.min_confidence)
            scale = max(0.5, min(1.0, scale))
            risk_dollars *= scale

        shares_by_risk = int(risk_dollars / stop_dist) if stop_dist > 0 else 0
        shares_by_pct = int((self.nav * self.max_position_pct) / price) if price > 0 else 0
        return min(shares_by_risk, shares_by_pct)

    def run(
        self,
        output: ReconcilerOutput,
        risk_lookup: dict[str, dict],   # symbol → {stop_price, stop_pct, target_price, target_pct, atr}
        sector_lookup: dict[str, str],  # symbol → sector string
    ) -> OptimizerOutput:

        # --- Sells: close every position the PM flagged for exit ---
        sells = [
            SellOrder(
                symbol=p.symbol,
                shares=p.qty,
                market_value=p.market_value,
                unrealized_plpc=p.unrealized_plpc,
                reason="pm_exit",
            )
            for p in output.exits
        ]

        # --- Track constraint state (holds count against limits) ---
        slots_used = len(output.holds)
        invested = sum(p.market_value for p in output.holds)

        sector_allocated: dict[str, float] = {}
        for p in output.holds:
            sec = sector_lookup.get(p.symbol, "Unknown")
            sector_allocated[sec] = sector_allocated.get(sec, 0.0) + p.market_value

        investable = self.nav * (1.0 - self.cash_reserve)

        # --- Buys: size each PM-approved candidate, enforce hard limits ---
        buys: list[BuyOrder] = []

        for result in output.buys:

            # Hard limit: position count
            if slots_used >= self.max_positions:
                print(f"[risk] {result.symbol} skipped — max positions reached")
                continue

            # Hard limit: overall budget
            if invested >= investable:
                print(f"[risk] {result.symbol} skipped — cash reserve floor reached")
                break

            symbol = result.symbol
            if symbol not in risk_lookup:
                print(f"[risk] {symbol} skipped — no risk data")
                continue

            risk = risk_lookup[symbol]
            sector = sector_lookup.get(symbol, "Unknown")

            stop_dist = 2.0 * risk["atr"]
            price = risk["stop_price"] + stop_dist

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
            budget_left = investable - invested
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
                stop_price=risk["stop_price"],
                stop_pct=risk["stop_pct"],
                target_price=risk["target_price"],
                target_pct=risk["target_pct"],
                confidence=result.confidence,
            ))

            sector_allocated[sector] = current_sector_value + position_value
            invested += position_value
            slots_used += 1

        return OptimizerOutput(buys=buys, sells=sells)


if __name__ == "__main__":
    import os
    from alpaca.trading.client import TradingClient
    from agents.analyst.sa_RS import RSMomentumAgent
    from agents.portfolio_manager.reconciler_agent import ReconcilerAgent

    NAV = 100_000

    alpaca = TradingClient(
        api_key=os.environ["ALPACA_PUBLIC_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )

    rs_agent = RSMomentumAgent()
    reconciler = ReconcilerAgent([rs_agent], alpaca=alpaca)
    recon_output = reconciler.run()

    all_symbols = (
        [r.symbol for r in recon_output.buys]
        + [p.symbol for p in recon_output.holds]
    )
    risk_lookup = {
        s: rs_agent._compute_risk(s)
        for s in all_symbols
        if s in rs_agent.stock_data.index
    }
    sector_lookup = rs_agent.stock_data["sector"].to_dict()

    optimizer = Optimizer(nav=NAV)
    result = optimizer.run(recon_output, risk_lookup, sector_lookup)
    print(result)

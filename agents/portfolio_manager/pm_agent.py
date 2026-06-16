import re
import json
import dataclasses
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from alpaca.trading.client import TradingClient
from agents.analysts.sa import AgentVerdict, SignalAgent
from agents.llm_client import call_llm_analyze, REMOTE_MODEL
from runs.io import save_json

_POSITIONS_BOOK_PATH = Path(__file__).parent.parent.parent / "runs" / "positions_book.json"

_PM_SYSTEM_PROMPT = """
You are the Portfolio Manager of a discretionary momentum trading desk.

Automatic exits (stop loss, target hit, time stop) have already been applied before you see this — those positions are gone. You only see what remains.

Your job:
1. For each REMAINING POSITION: decide HOLD or EXIT
   - EXIT if the momentum signal has clearly faded (not based on P&L alone)
   - If analyst shows NO COVERAGE today, the signal has likely faded — default EXIT
2. For each NEW CANDIDATE: decide BUY or PASS
   - Avoid sub-sector concentration (e.g. two semiconductor equipment stocks)
   - Concentrated book: 10-15 positions total
   - List BUY decisions in order of conviction, highest first

OUTPUT FORMAT — one decision per line, nothing else:
HOLD: [SYMBOL] | [one sentence reason]
EXIT: [SYMBOL] | [one sentence reason]
BUY: [SYMBOL] | [one sentence reason]
PASS: [SYMBOL] | [one sentence reason]
"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CurrentPosition:
    symbol: str
    qty: float
    market_value: float
    avg_entry_price: float
    current_price: float
    unrealized_pl: float
    unrealized_plpc: float


@dataclass
class ExitedPosition(CurrentPosition):
    exit_reason: str = ""   # stop_loss | target_hit | time_stop | pm_exit


@dataclass
class ReconcilerResult:
    symbol: str
    confidence: float       # avg analyst confidence — used by optimizer for sizing
    pm_reasoning: str       # PM's one-line reason
    sector: str = "Unknown"
    stop_price: float = 0.0
    stop_pct: float = 0.0
    target_price: float = 0.0
    target_pct: float = 0.0
    atr: float = 0.0
    max_hold_days: int = 20
    verdicts: list[AgentVerdict] = field(default_factory=list)


@dataclass
class ReconcilerOutput:
    buys: list[ReconcilerResult]    # PM-approved, in conviction order
    holds: list[CurrentPosition]
    exits: list[ExitedPosition]     # forced (stop/target/time) + PM exits, with reason
    investable_capital: float       # cash available for new buys this cycle
    pm_reasoning: str               # full PM LLM output for audit


# ---------------------------------------------------------------------------
# ReconcilerAgent
# ---------------------------------------------------------------------------

class ReconcilerAgent:
    """
    Orchestrates the daily portfolio decision cycle:
      1. Fetch current positions and account from Alpaca
      2. Apply deterministic exit rules (stop / target / time stop)
      3. Run analysts on today's candidates
      4. PM (LLM) decides buys and holds for the remaining book
      5. Calculate investable capital for the optimizer
      6. Save all artifacts to JSON
    """

    def __init__(
        self,
        agents: list[SignalAgent],
        alpaca: TradingClient | None = None,
        model: str = REMOTE_MODEL,
        cash_reserve: float = 0.20,
    ):
        self.agents = agents
        self.alpaca = alpaca
        self.model = model
        self.cash_reserve = cash_reserve

    # ------------------------------------------------------------------
    # Alpaca helpers
    # ------------------------------------------------------------------

    def _get_current_positions(self) -> dict[str, CurrentPosition]:
        if self.alpaca is None:
            return {}
        try:
            raw = self.alpaca.get_all_positions()
        except Exception as e:
            print(f"[PM] positions fetch failed: {e}")
            return {}
        return {
            p.symbol: CurrentPosition(
                symbol=p.symbol,
                qty=float(p.qty),
                market_value=float(p.market_value),
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                unrealized_pl=float(p.unrealized_pl),
                unrealized_plpc=float(p.unrealized_plpc),
            )
            for p in raw
        }

    def _get_account_info(self) -> tuple[float, float]:
        """Returns (cash, nav)."""
        if self.alpaca is None:
            return 0.0, 0.0
        try:
            acct = self.alpaca.get_account()
            return float(acct.cash), float(acct.portfolio_value)
        except Exception as e:
            print(f"[PM] account fetch failed: {e}")
            return 0.0, 0.0

    # ------------------------------------------------------------------
    # Positions book (written by ExecutionAgent, read here)
    # ------------------------------------------------------------------

    def _load_positions_book(self) -> dict[str, dict]:
        if not _POSITIONS_BOOK_PATH.exists():
            return {}
        with open(_POSITIONS_BOOK_PATH) as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Deterministic exit check
    # ------------------------------------------------------------------

    def _check_exits(
        self,
        current_positions: dict[str, CurrentPosition],
        positions_book: dict[str, dict],
        today: date,
    ) -> tuple[list[ExitedPosition], list[CurrentPosition]]:
        """
        Checks stop loss, target, and time stop for every held position.
        Returns (forced_exits, remaining_positions).
        """
        forced: list[ExitedPosition] = []
        remaining: list[CurrentPosition] = []

        for symbol, pos in current_positions.items():
            book = positions_book.get(symbol)
            if book is None:
                # No entry record — hold by default (e.g. manually added position)
                remaining.append(pos)
                continue

            reason = None
            if pos.current_price <= book["stop_price"]:
                reason = "stop_loss"
            elif pos.current_price >= book["target_price"]:
                reason = "target_hit"
            else:
                entry_date = date.fromisoformat(book["entry_date"])
                if (today - entry_date).days >= book["max_hold_days"]:
                    reason = "time_stop"

            if reason:
                forced.append(ExitedPosition(**dataclasses.asdict(pos), exit_reason=reason))
            else:
                remaining.append(pos)

        if forced:
            print(f"[PM] {len(forced)} forced exits: "
                  + ", ".join(f"{p.symbol}({p.exit_reason})" for p in forced))

        return forced, remaining

    # ------------------------------------------------------------------
    # Capital calculation
    # ------------------------------------------------------------------

    def _calculate_investable(
        self,
        cash: float,
        nav: float,
        all_exits: list[ExitedPosition],
    ) -> float:
        """
        investable = (cash + exit_proceeds) - cash_reserve * NAV
        Uses post-exit projected cash; NAV is pre-exit (conservative).
        """
        exit_proceeds = sum(p.market_value for p in all_exits)
        return max(0.0, round(cash + exit_proceeds - self.cash_reserve * nav, 2))

    # ------------------------------------------------------------------
    # Analyst runner
    # ------------------------------------------------------------------

    def _run_analysts(
        self, agent_configs: dict
    ) -> dict[str, list[AgentVerdict]]:
        verdicts: dict[str, list[AgentVerdict]] = {}

        for agent in self.agents:
            cfg = agent_configs.get(agent.signal_type, {})
            try:
                candidates = agent.prefilter(**cfg.get("prefilter", {}))
            except Exception as e:
                print(f"[{agent.signal_type}] prefilter error: {e}")
                continue

            print(f"[{agent.signal_type}] {len(candidates)} candidates")

            for symbol in candidates:
                try:
                    v = agent.run(symbol)
                    verdicts.setdefault(symbol, []).append(v)
                except Exception as e:
                    print(f"[{agent.signal_type}] error on {symbol}: {e}")

        return verdicts

    # ------------------------------------------------------------------
    # PM prompt + parsing
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        verdicts_by_symbol: dict[str, list[AgentVerdict]],
        remaining_positions: list[CurrentPosition],
        forced_exits: list[ExitedPosition],
    ) -> str:
        lines = []
        held = {p.symbol for p in remaining_positions}
        covered = set(verdicts_by_symbol.keys())

        if forced_exits:
            exits_str = ", ".join(f"{p.symbol} ({p.exit_reason})" for p in forced_exits)
            lines.append(f"NOTE: {len(forced_exits)} position(s) auto-exited today: {exits_str}")
            lines.append("")

        if remaining_positions:
            lines.append("REMAINING PORTFOLIO (decide HOLD or EXIT for each):")
            for pos in remaining_positions:
                line = (
                    f"  {pos.symbol}: {pos.qty:.0f} shares  "
                    f"value=${pos.market_value:,.0f}  "
                    f"P&L={pos.unrealized_plpc:+.1%}  "
                    f"entry=${pos.avg_entry_price:.2f}"
                )
                if pos.symbol in covered:
                    v = verdicts_by_symbol[pos.symbol][0]
                    line += f"  | analyst: {v.direction.upper()} ({v.confidence:.0%})"
                else:
                    line += "  | analyst: NO COVERAGE"
                lines.append(line)
            lines.append("")

        new_candidates = {s: v for s, v in verdicts_by_symbol.items() if s not in held}
        if new_candidates:
            lines.append("NEW CANDIDATES (decide BUY or PASS, list BUYs in conviction order):")
            for symbol, verdicts in new_candidates.items():
                for v in verdicts:
                    lines.append(
                        f"\n  [{v.signal_type}] {symbol} — "
                        f"{v.direction.upper()} ({v.confidence:.0%})"
                    )
                    lines.append(f"  {v.reasoning}")

        return "\n".join(lines)

    def _parse_pm_output(
        self,
        output: str,
        verdicts_by_symbol: dict[str, list[AgentVerdict]],
        remaining_positions: dict[str, CurrentPosition],
    ) -> tuple[list[ReconcilerResult], list[CurrentPosition], list[CurrentPosition]]:
        pattern = re.compile(r"^(BUY|PASS|HOLD|EXIT):\s*([A-Z]+)\s*\|?\s*(.*)", re.MULTILINE)
        buys, pm_exits, holds = [], [], []

        for match in pattern.finditer(output):
            action = match.group(1)
            symbol = match.group(2).strip()
            reason = match.group(3).strip()

            if action == "BUY":
                verdicts = verdicts_by_symbol.get(symbol, [])
                avg_conf = (
                    sum(v.confidence for v in verdicts) / len(verdicts)
                    if verdicts else 0.65
                )
                first = verdicts[0] if verdicts else None
                buys.append(ReconcilerResult(
                    symbol=symbol,
                    confidence=round(avg_conf, 4),
                    pm_reasoning=reason,
                    sector=first.sector if first else "Unknown",
                    stop_price=first.stop_price if first else 0.0,
                    stop_pct=first.stop_pct if first else 0.0,
                    target_price=first.target_price if first else 0.0,
                    target_pct=first.target_pct if first else 0.0,
                    atr=first.atr if first else 0.0,
                    max_hold_days=first.max_hold_days if first else 20,
                    verdicts=verdicts,
                ))
            elif action == "EXIT":
                if symbol in remaining_positions:
                    pm_exits.append(remaining_positions[symbol])
            elif action == "HOLD":
                if symbol in remaining_positions:
                    holds.append(remaining_positions[symbol])

        return buys, pm_exits, holds

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, agent_configs: dict | None = None) -> ReconcilerOutput:
        today = date.today()
        agent_configs = agent_configs or {}

        # 1. Fetch portfolio and account
        current_positions = self._get_current_positions()
        cash, nav = self._get_account_info()

        # 2. Deterministic exit check
        positions_book = self._load_positions_book()
        forced_exits, remaining = self._check_exits(current_positions, positions_book, today)
        remaining_map = {p.symbol: p for p in remaining}

        # 3. Run analysts
        verdicts_by_symbol = self._run_analysts(agent_configs)
        save_json("analyst_verdicts", {
            "verdicts": {
                s: [dataclasses.asdict(v) for v in vs]
                for s, vs in verdicts_by_symbol.items()
            }
        })

        # 4. PM decides buys and holds for remaining book
        user_prompt = self._build_prompt(verdicts_by_symbol, remaining, forced_exits)
        print("[PM] Calling portfolio manager...")
        pm_output = call_llm_analyze(_PM_SYSTEM_PROMPT, user_prompt, self.model)

        buys, pm_exits, holds = self._parse_pm_output(
            pm_output, verdicts_by_symbol, remaining_map
        )

        # 6. Combine exits and calculate investable capital
        all_exits = forced_exits + [
            ExitedPosition(**dataclasses.asdict(p), exit_reason="pm_exit")
            for p in pm_exits
        ]
        investable = self._calculate_investable(cash, nav, all_exits)

        print(
            f"[PM] {len(buys)} buys  {len(holds)} holds  "
            f"{len(all_exits)} exits  investable=${investable:,.0f}"
        )

        # 7. Save and return
        output = ReconcilerOutput(
            buys=buys,
            holds=holds,
            exits=all_exits,
            investable_capital=investable,
            pm_reasoning=pm_output,
        )
        save_json("pm_decisions", dataclasses.asdict(output))
        return output


if __name__ == "__main__":
    import os
    from alpaca.trading.client import TradingClient
    from agents.analysts.sa_RS import RSMomentumAgent

    alpaca = TradingClient(
        api_key=os.environ["ALPACA_PUBLIC_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )

    agent = RSMomentumAgent()
    reconciler = ReconcilerAgent([agent], alpaca=alpaca)
    output = reconciler.run()

    print(f"\n=== PM DECISION ===\n{output.pm_reasoning}\n")
    print(f"Buys ({len(output.buys)}):  {[r.symbol for r in output.buys]}")
    print(f"Holds ({len(output.holds)}): {[p.symbol for p in output.holds]}")
    print(f"Exits ({len(output.exits)}): {[(p.symbol, p.exit_reason) for p in output.exits]}")
    print(f"Investable: ${output.investable_capital:,.0f}")

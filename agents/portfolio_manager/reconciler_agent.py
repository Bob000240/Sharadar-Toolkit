import re
from dataclasses import dataclass, field
from alpaca.trading.client import TradingClient
from agents.analyst.sa import AgentVerdict, SignalAgent
from agents.llm_client import call_llm_analyze, ANALYSIS_MODEL


_PM_SYSTEM_PROMPT = """
You are the Portfolio Manager of a discretionary momentum trading desk.

Your analysts screen the universe daily using quantitative momentum criteria and submit entry recommendations for stocks that passed. Your job is to make the final portfolio decisions.

YOUR DECISION FRAMEWORK:
- Run a concentrated book: 10–15 positions maximum
- Avoid sub-sector concentration: do not hold two highly correlated names (e.g. two semiconductor equipment stocks, two regional banks)
- Momentum exits: exit a held position when the analyst no longer covers it (signal faded) or when a stronger opportunity displaces it — not based on P&L alone
- Quality over quantity: fewer clean setups beat a crowded book of mediocre ones
- If a held position did not receive analyst coverage today, assume signal has faded — default EXIT unless you have strong reason to hold

For each CURRENT POSITION: output HOLD or EXIT
For each NEW CANDIDATE: output BUY or PASS

OUTPUT FORMAT — one decision per line, nothing else:
HOLD: [SYMBOL] | [one sentence reason]
EXIT: [SYMBOL] | [one sentence reason]
BUY: [SYMBOL] | [one sentence reason]
PASS: [SYMBOL] | [one sentence reason]
"""


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
class ReconcilerResult:
    symbol: str
    confidence: float           # avg analyst confidence — used by optimizer for sizing
    pm_reasoning: str           # PM's one-line reason for the buy
    verdicts: list[AgentVerdict] = field(default_factory=list)


@dataclass
class ReconcilerOutput:
    buys: list[ReconcilerResult]
    exits: list[CurrentPosition]
    holds: list[CurrentPosition]
    pm_reasoning: str           # full PM output for audit trail


class ReconcilerAgent:
    """
    The Portfolio Manager. Reads analyst verdicts and the current Alpaca book,
    then decides what to buy, hold, and exit via LLM judgment.

    Analysts (SignalAgents) don't know about the portfolio — they just cover
    their candidates. The PM sees everything and makes holistic decisions.
    """

    def __init__(
        self,
        agents: list[SignalAgent],
        alpaca: TradingClient | None = None,
        model: str = ANALYSIS_MODEL,
    ):
        self.agents = agents
        self.alpaca = alpaca
        self.model = model

    # ------------------------------------------------------------------
    # Portfolio fetch
    # ------------------------------------------------------------------

    def _get_current_positions(self) -> dict[str, CurrentPosition]:
        if self.alpaca is None:
            return {}
        try:
            raw = self.alpaca.get_all_positions()
        except Exception as e:
            print(f"[PM] Alpaca fetch failed: {e}")
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

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        verdicts_by_symbol: dict[str, list[AgentVerdict]],
        current_positions: dict[str, CurrentPosition],
    ) -> str:
        lines = []

        if current_positions:
            lines.append("CURRENT PORTFOLIO:")
            for pos in current_positions.values():
                lines.append(
                    f"  {pos.symbol}: {pos.qty:.0f} shares  "
                    f"value=${pos.market_value:,.0f}  "
                    f"P&L={pos.unrealized_plpc:+.1%}  "
                    f"entry=${pos.avg_entry_price:.2f}"
                )
            lines.append("")

        # Candidates that passed the analyst screen
        covered = set(verdicts_by_symbol.keys())

        if verdicts_by_symbol:
            lines.append("ANALYST RECOMMENDATIONS (new candidates):")
            for symbol, verdicts in verdicts_by_symbol.items():
                for v in verdicts:
                    lines.append(
                        f"\n  [{v.signal_type}] {symbol} — "
                        f"{v.direction.upper()} ({v.confidence:.0%})"
                    )
                    lines.append(f"  {v.reasoning}")
            lines.append("")

        # Held positions not covered by any analyst today
        uncovered_holds = [s for s in current_positions if s not in covered]
        if uncovered_holds:
            lines.append("HELD POSITIONS WITH NO ANALYST COVERAGE TODAY:")
            for symbol in uncovered_holds:
                pos = current_positions[symbol]
                lines.append(
                    f"  {symbol}: did not pass today's momentum screen "
                    f"(P&L {pos.unrealized_plpc:+.1%})"
                )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _parse_pm_output(
        self,
        output: str,
        verdicts_by_symbol: dict[str, list[AgentVerdict]],
        current_positions: dict[str, CurrentPosition],
    ) -> tuple[list[ReconcilerResult], list[CurrentPosition], list[CurrentPosition]]:

        pattern = re.compile(r"^(BUY|PASS|HOLD|EXIT):\s*([A-Z]+)\s*\|?\s*(.*)", re.MULTILINE)
        buys, exits, holds = [], [], []

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
                buys.append(ReconcilerResult(
                    symbol=symbol,
                    confidence=round(avg_conf, 4),
                    pm_reasoning=reason,
                    verdicts=verdicts,
                ))

            elif action == "EXIT":
                if symbol in current_positions:
                    exits.append(current_positions[symbol])

            elif action == "HOLD":
                if symbol in current_positions:
                    holds.append(current_positions[symbol])

            # PASS: no action needed

        return buys, exits, holds

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, agent_configs: dict | None = None) -> ReconcilerOutput:
        agent_configs = agent_configs or {}
        verdicts_by_symbol: dict[str, list[AgentVerdict]] = {}

        # Run all analysts
        for agent in self.agents:
            cfg = agent_configs.get(agent.signal_type, {})
            prefilter_cfg = cfg.get("prefilter", {})

            try:
                candidates = agent.prefilter(**prefilter_cfg)
            except Exception as e:
                print(f"[{agent.signal_type}] prefilter error: {e}")
                continue

            print(f"[{agent.signal_type}] {len(candidates)} candidates")

            for symbol in candidates:
                try:
                    verdict = agent.run(symbol)
                    verdicts_by_symbol.setdefault(symbol, []).append(verdict)
                except Exception as e:
                    print(f"[{agent.signal_type}] error on {symbol}: {e}")

        # Fetch current portfolio
        current_positions = self._get_current_positions()

        # Build PM prompt and call LLM
        user_prompt = self._build_prompt(verdicts_by_symbol, current_positions)
        print("[PM] Calling portfolio manager LLM...")
        pm_output = call_llm_analyze(_PM_SYSTEM_PROMPT, user_prompt, self.model)

        # Parse PM decisions
        buys, exits, holds = self._parse_pm_output(
            pm_output, verdicts_by_symbol, current_positions
        )

        print(
            f"[PM] decisions → {len(buys)} buys, "
            f"{len(holds)} holds, {len(exits)} exits"
        )

        return ReconcilerOutput(
            buys=buys,
            exits=exits,
            holds=holds,
            pm_reasoning=pm_output,
        )


if __name__ == "__main__":
    import os
    from alpaca.trading.client import TradingClient
    from agents.analyst.sa_RS import RSMomentumAgent

    alpaca = TradingClient(
        api_key=os.environ["ALPACA_PUBLIC_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )

    agent = RSMomentumAgent()
    reconciler = ReconcilerAgent([agent], alpaca=alpaca)
    output = reconciler.run()

    print(f"\n=== PM DECISION ===\n{output.pm_reasoning}\n")
    print(f"Buys ({len(output.buys)}): {[r.symbol for r in output.buys]}")
    print(f"Holds ({len(output.holds)}): {[p.symbol for p in output.holds]}")
    print(f"Exits ({len(output.exits)}): {[p.symbol for p in output.exits]}")

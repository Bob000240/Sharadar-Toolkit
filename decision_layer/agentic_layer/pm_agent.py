# import dataclasses
# from dataclasses import dataclass
# from datetime import date
# from pathlib import Path
# from typing import Optional
# import json

# from alpaca.trading.client import TradingClient
# from alpaca.trading.requests import MarketOrderRequest
# from alpaca.trading.enums import OrderSide, TimeInForce
# from decision_layer.det_layer.pre_filter import AgentVerdict
# from decision_layer.agentic_layer.llm_client import call_llm_analyze, REMOTE_MODEL

# _RUNS_ROOT = Path(__file__).parent.parent.parent / "data_agentic" / "runs"
# _POSITIONS_BOOK_PATH = _RUNS_ROOT / "positions_book.json"
# _TRADE_LOG_PATH = _RUNS_ROOT / "trade_log.json"


# # --- Data classes ---


# @dataclass
# class Position:
#     symbol: str
#     qty: float
#     market_value: float
#     avg_entry_price: float
#     current_price: float
#     unrealized_pl: float
#     unrealized_plpc: float
#     stop_price: float = 0.0
#     target_price: float = 0.0
#     entry_date: str = ""
#     max_hold_days: int = 20
#     atr: float = 0.0
#     high_water_mark: float = 0.0
#     strategy: str = ""


# @dataclass
# class BuyDecision:
#     verdict: AgentVerdict
#     rationale: str


# @dataclass
# class BuyOrder:
#     symbol: str
#     shares: int
#     entry_price: float
#     stop_price: float
#     target_price: float
#     stop_pct: float
#     target_pct: float
#     atr: float
#     max_hold_days: int
#     strategy: str = ""


# # --- Persistence ---


# def load_positions_book() -> dict:
#     if not _POSITIONS_BOOK_PATH.exists():
#         return {}
#     with open(_POSITIONS_BOOK_PATH) as f:
#         content = f.read().strip()
#     return json.loads(content) if content else {}


# def save_positions_book(book: dict) -> None:
#     _POSITIONS_BOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
#     with open(_POSITIONS_BOOK_PATH, "w") as f:
#         json.dump(book, f, indent=2)


# # --- StrategyReceiver ---


# class StrategyReceiver:
#     """LLM gate: filters analyst verdicts before position sizing."""

#     def __init__(self, model: str = REMOTE_MODEL):
#         self.model = model

#     def run(
#         self, verdicts: list[AgentVerdict], existing_symbols: set[str]
#     ) -> list[BuyDecision]:
#         candidates = [
#             v
#             for v in verdicts
#             if v.direction == "bullish"
#             and v.confidence >= 0.6
#             and v.symbol not in existing_symbols
#         ]
#         decisions = []
#         for verdict in candidates:
#             decision = self._evaluate(verdict)
#             if decision:
#                 decisions.append(decision)
#         return decisions

#     def _evaluate(self, verdict: AgentVerdict) -> Optional[BuyDecision]:
#         system = (
#             "You are a portfolio manager reviewing analyst signals. "
#             "Given a verdict, decide BUY or PASS. "
#             'Reply with JSON only: {"action": "BUY" or "PASS", "rationale": "one sentence"}'
#         )
#         user = (
#             f"Symbol: {verdict.symbol}\n"
#             f"Signal: {verdict.strategy}\n"
#             f"Direction: {verdict.direction}\n"
#             f"Confidence: {verdict.confidence:.0%}\n"
#             f"Stop: ${verdict.stop_price:.2f} ({verdict.stop_pct:.1f}%)\n"
#             f"Target: ${verdict.target_price:.2f} (+{verdict.target_pct:.1f}%)\n"
#             f"Max hold: {verdict.max_hold_days}d\n"
#             f"Reasoning: {verdict.reasoning}"
#         )
#         print(f"[PM] Evaluating {verdict.symbol}...")
#         raw = call_llm_analyze(system=system, user=user, model=self.model)
#         text = raw.strip()
#         if "```" in text:
#             text = text.split("```")[1].lstrip("json").strip()
#         data = json.loads(text)
#         action = data.get("action")
#         print(f"[PM] {verdict.symbol} → {action}")
#         if action == "BUY":
#             return BuyDecision(verdict=verdict, rationale=data.get("rationale", ""))
#         return None


# # --- PositionSizer ---


# class PositionSizer:
#     def __init__(self, cash: float, nav: float, max_position_pct: float = 0.10):
#         self.cash = cash
#         self.nav = nav
#         self.max_position_pct = max_position_pct

#     def size(self, decisions: list[BuyDecision]) -> list[BuyOrder]:
#         investable = self.cash
#         orders = []
#         for d in decisions:
#             v = d.verdict
#             if not v.stop_pct:
#                 continue
#             entry_price = v.stop_price / (1 + v.stop_pct / 100)
#             dollars = min(investable, self.nav * self.max_position_pct)
#             shares = int(dollars / entry_price)
#             if shares < 1:
#                 continue
#             orders.append(
#                 BuyOrder(
#                     symbol=v.symbol,
#                     shares=shares,
#                     entry_price=round(entry_price, 2),
#                     stop_price=v.stop_price,
#                     target_price=v.target_price,
#                     stop_pct=v.stop_pct,
#                     target_pct=v.target_pct,
#                     atr=v.atr,
#                     max_hold_days=v.max_hold_days,
#                     strategy=v.strategy,
#                 )
#             )
#             investable -= shares * entry_price
#         return orders


# # --- PMAgent ---


# class PMAgent:
#     def __init__(self, alpaca: TradingClient, debug: bool = False):
#         self.alpaca = alpaca
#         self.debug = debug
#         self.analysts_model = REMOTE_MODEL

#     def _reconcile_book(self) -> None:
#         book = load_positions_book()
#         if not book:
#             return
#         positions = {p.symbol: p for p in self.alpaca.get_all_positions()}
#         dirty = False
#         for symbol, entry in book.items():
#             if symbol not in positions:
#                 continue
#             actual = round(float(positions[symbol].avg_entry_price), 2)
#             stored = entry.get("avg_entry_price", actual)
#             if abs(actual - stored) < 0.01:
#                 continue
#             atr = entry.get("atr", 0.0)
#             stop_dist = 2 * atr
#             book[symbol]["avg_entry_price"] = actual
#             book[symbol]["stop_price"] = round(actual - stop_dist, 2)
#             book[symbol]["target_price"] = round(actual + 3 * stop_dist, 2)
#             book[symbol]["high_water_mark"] = actual
#             dirty = True
#             print(
#                 f"Reconciled {symbol}: fill=${actual} (was ${stored}) → stop=${book[symbol]['stop_price']} target=${book[symbol]['target_price']}"
#             )
#         if dirty:
#             save_positions_book(book)

#     def _execute_buy(
#         self, order: BuyOrder, time_in_force: TimeInForce = TimeInForce.DAY
#     ) -> dict:
#         if self.debug:
#             print(
#                 f"[DEBUG] BUY {order.shares} {order.symbol} @ ~${order.entry_price:.2f}"
#             )
#             return {"symbol": order.symbol, "shares": order.shares, "status": "debug"}
#         req = MarketOrderRequest(
#             symbol=order.symbol,
#             qty=order.shares,
#             side=OrderSide.BUY,
#             time_in_force=time_in_force,
#         )
#         resp = self.alpaca.submit_order(req)
#         print(f"BUY {order.shares} {order.symbol} order_id={resp.id}")
#         return {
#             "symbol": order.symbol,
#             "shares": order.shares,
#             "order_id": str(resp.id),
#             "status": "submitted",
#         }

#     def optimize(self) -> None:
#         # Reserved for future: rebalancing, sector exposure limits, etc.
#         if self.debug:
#             print(
#                 "Total portfolio value: ${:.2f}".format(
#                     float(self.alpaca.get_account().portfolio_value)
#                 )
#             )
#             print(
#                 "Cash available: ${:.2f}".format(float(self.alpaca.get_account().cash))
#             )

#         pass

#     def set_analysts_model(self, model: str) -> None:
#         self.analysts_model = model

#     def buy(self) -> None:
#         from decision_layer.det_layer.pre_RS import RSMomentumAgent

#         analyst = RSMomentumAgent(analysis_model=self.analysts_model)
#         candidates = analyst.prefilter()
#         print(f"RSMomentumAgent: {len(candidates)} candidates")
#         if not candidates:
#             print("No candidates — skipping buy")
#             return

#         held = {p.symbol for p in self.alpaca.get_all_positions()}
#         verdicts = [analyst.run(s) for s in candidates]

#         if self.debug:
#             print("\n--- Verdicts ---")
#             for v in verdicts:
#                 print(
#                     f"  {v.symbol} | {v.direction} | confidence={v.confidence:.0%} | stop=${v.stop_price} target=${v.target_price}"
#                 )
#                 print(f"    {v.reasoning}")
#             print()

#         decisions = StrategyReceiver().run(verdicts, held)
#         print(f"StrategyReceiver: {len(decisions)} decisions")

#         if self.debug:
#             print("\n--- Decisions ---")
#             for d in decisions:
#                 print(f"  BUY {d.verdict.symbol} — {d.rationale}")
#             print()

#         acct = self.alpaca.get_account()
#         orders = PositionSizer(float(acct.cash), float(acct.portfolio_value)).size(
#             decisions
#         )
#         print(f"PositionSizer: {len(orders)} orders")

#         if self.debug:
#             print("\n--- Orders ---")
#             for o in orders:
#                 print(
#                     f"  {o.symbol}: {o.shares} shares @ ~${o.entry_price} | stop=${o.stop_price} target=${o.target_price} | hold={o.max_hold_days}d"
#                 )
#             print()

#         book = load_positions_book()
#         today = date.today().isoformat()
#         for order in orders:
#             result = self._execute_buy(order)
#             if result["status"] in ("submitted", "debug"):
#                 book[order.symbol] = {
#                     "stop_price": order.stop_price,
#                     "target_price": order.target_price,
#                     "entry_date": today,
#                     "max_hold_days": order.max_hold_days,
#                     "atr": order.atr,
#                     "avg_entry_price": order.entry_price,
#                     "high_water_mark": order.entry_price,
#                     "strategy": order.strategy,
#                 }
#         save_positions_book(book)

from dotenv import load_dotenv
load_dotenv()

import json
import os
from datetime import datetime
from pathlib import Path
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def load_orders(orders_path: str) -> dict:
    """Load orders from JSON file."""
    with open(orders_path) as f:
        return json.load(f)


def execute_orders(orders: dict, alpaca: TradingClient, dry_run: bool = False) -> dict:
    """Execute buy and sell orders from the orders dict.

    Args:
        orders: Dict with 'buys' and 'sells' lists
        alpaca: Alpaca TradingClient instance
        dry_run: If True, log orders without executing

    Returns:
        Dict with executed order results
    """
    results = {
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
        "buys_executed": [],
        "buys_failed": [],
        "sells_executed": [],
        "sells_failed": [],
    }

    # Execute buys
    for order in orders.get("buys", []):
        symbol = order["symbol"]
        shares = int(order["shares"])

        if dry_run:
            print(f"[DRY RUN] BUY {shares} {symbol}")
            results["buys_executed"].append({
                "symbol": symbol,
                "shares": shares,
                "status": "dry_run",
            })
            continue

        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            resp = alpaca.submit_order(req)
            print(f"✓ BUY {shares} {symbol} @ order_id={resp.id}")
            results["buys_executed"].append({
                "symbol": symbol,
                "shares": shares,
                "order_id": str(resp.id),
                "status": "submitted",
            })
        except Exception as e:
            print(f"✗ BUY {symbol} failed: {e}")
            results["buys_failed"].append({
                "symbol": symbol,
                "shares": shares,
                "error": str(e),
            })

    # Execute sells
    for order in orders.get("sells", []):
        symbol = order["symbol"]
        shares = int(order["shares"])
        reason = order.get("reason", "unknown")

        if dry_run:
            print(f"[DRY RUN] SELL {shares} {symbol} ({reason})")
            results["sells_executed"].append({
                "symbol": symbol,
                "shares": shares,
                "reason": reason,
                "status": "dry_run",
            })
            continue

        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=shares,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            resp = alpaca.submit_order(req)
            print(f"✓ SELL {shares} {symbol} ({reason}) @ order_id={resp.id}")
            results["sells_executed"].append({
                "symbol": symbol,
                "shares": shares,
                "reason": reason,
                "order_id": str(resp.id),
                "status": "submitted",
            })
        except Exception as e:
            print(f"✗ SELL {symbol} failed: {e}")
            results["sells_failed"].append({
                "symbol": symbol,
                "shares": shares,
                "reason": reason,
                "error": str(e),
            })

    return results


def main():
    # Find latest orders.json
    runs_dir = Path(__file__).parent / "runs"
    orders_files = sorted(runs_dir.glob("*/orders.json"), reverse=True)

    if not orders_files:
        print("No orders.json found")
        return

    orders_path = orders_files[0]
    print(f"Loading orders from: {orders_path}")

    orders = load_orders(orders_path)
    print(f"  {len(orders['buys'])} buys, {len(orders['sells'])} sells")

    # Initialize Alpaca client
    alpaca = TradingClient(
        api_key=os.environ["ALPACA_PUBLIC_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )

    # Execute orders (set dry_run=True to preview without executing)
    results = execute_orders(orders, alpaca, dry_run=False)

    # Save execution results
    results_dir = orders_path.parent
    results_file = results_dir / "execution_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {results_file}")

    # Summary
    print(f"\n=== EXECUTION SUMMARY ===")
    print(f"Buys:  {len(results['buys_executed'])} executed, {len(results['buys_failed'])} failed")
    print(f"Sells: {len(results['sells_executed'])} executed, {len(results['sells_failed'])} failed")


if __name__ == "__main__":
    main()

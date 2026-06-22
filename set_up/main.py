import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from decision_layer.agentic_layer.pm_agent import PMAgent

load_dotenv()


def main(debug: bool = False):
    alpaca = TradingClient(
        api_key=os.environ["ALPACA_PUBLIC_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )
    pm = PMAgent(alpaca, debug=debug)
    pm.sell()
    pm.optimize()
    pm.set_analysts_model("qwen3:14b")
    pm.buy()


if __name__ == "__main__":
    main(debug=True)

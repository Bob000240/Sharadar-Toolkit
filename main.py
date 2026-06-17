from dotenv import load_dotenv
load_dotenv()

import os
from alpaca.trading.client import TradingClient
from agents.pm_agent import PMAgent


def main(debug: bool = False):
    alpaca = TradingClient(
        api_key=os.environ["ALPACA_PUBLIC_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
        paper=True,
    )
    pm = PMAgent(alpaca, debug=debug)
    pm.sell()
    pm.optimize()
    pm.buy()


if __name__ == "__main__":
    main(debug=True)

from polymarket_api import AsyncMarketDataClient
from kalshi_api import KalshiWebSocketClient, Environment
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
import asyncio
import math
import os
from dotenv import load_dotenv

def load_private_key_from_file(file_path: str) -> rsa.RSAPrivateKey:
    with open(file_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )
    return private_key

async def message_consumer(queue: asyncio.Queue):
    """Centralized consumer of all WS messages."""
    polymarket_offers = {}
    kalshi_offers = {}
    inverse_markets = {"polymarket": "kalshi", "kalshi": "polymarket"} # {"Thunder": "KXNBAGAME-25MAY09OKCDEN-DEN", "Nuggets": "KXNBAGAME-25MAY09OKCDEN-OKC"}
    while True:
        source_name, payload = await queue.get()
        # e.g. combine Polymarket + Kalshi data, or forward to UI, DB, etc.
        print(f"[{source_name}]", payload['best_offers'])
        if source_name == "polymarket":
            polymarket_offers = payload['best_offers']
        elif source_name == "kalshi":
            kalshi_offers = payload['best_offers']
        # Check for arbitrage opportunities
        if polymarket_offers and kalshi_offers:
            result = check_markets_arbitrage(polymarket_offers["Thunder"]["best_ask"][0]*100, polymarket_offers["Nuggets"]["best_ask"][0]*100, kalshi_offers[inverse_markets["Thunder"]]["best_ask"][0], kalshi_offers[inverse_markets["Nuggets"]]["best_ask"][0], 100.0)
            print("Is arbitrage possible?", result["is_arbitrage"])
            if result["is_arbitrage"]:
                print(f"Arbitrage opportunity found! {result['strategy']}")
                print(f"Profit if win: {result['profit_market1']}, Profit if lose: {result['profit_market2']}")
            else:
                print("No arbitrage opportunity found.")
        queue.task_done()


def check_arbitrage(market1_price, market2_inverse_price, shares=100):
    market2_fee = calculate_kalshi_fees(market2_inverse_price, shares)
    profit_if_win_market1 = (1 - market1_price) * shares
    profit_if_win_market2 = (1 - market2_inverse_price) * shares - market2_fee
    cost_market1 = market1_price * shares
    cost_market2 = market2_inverse_price * shares + market2_fee

    pnl_if_win_market1 = profit_if_win_market1 - cost_market2
    pnl_if_lose_market1 = profit_if_win_market2 - cost_market1


    return {
        "is_arbitrage": pnl_if_lose_market1 > 0 and pnl_if_win_market1 > 0,
        "pnl_if_win": pnl_if_win_market1,
        "pnl_if_lose": pnl_if_lose_market1,
    }


def check_markets_arbitrage(m1_yes, m1_no, m2_yes, m2_no, shares=100.0):
    pm1 = check_arbitrage(m1_yes, m2_no,  shares)
    pm2 = check_arbitrage(m1_no, m2_yes,  shares)

    # profit is the same in both outcomes whenever arbitrage exists
    profit1 = pm1["pnl_if_win"]
    profit2 = pm2["pnl_if_win"]

    is_arbitrage = pm1["is_arbitrage"] or pm2["is_arbitrage"]
    strategy = "fade"
    if is_arbitrage:
        if pm1["pnl_if_win"] > pm2["pnl_if_win"]:
            strategy = f"bet yes on market 1 @ {m1_yes} and no on market 2 @ {m2_no}"
        else:
            strategy = f"bet no on market 1 @ {m1_no} and yes on market 2 @ {m2_yes}"


    return {
        "is_arbitrage": pm1["is_arbitrage"] or pm2["is_arbitrage"],
        "profit_market1": profit1,
        "profit_market2": profit2,
        "strategy": strategy,
        
    }


def round_up(value, decimal_places=2):
    multiplier = 10 ** decimal_places
    return math.ceil(value * multiplier) / multiplier
    
def calculate_kalshi_fees(contract_price, shares, fee_rate=0.07):
    fee = round_up(fee_rate * shares * contract_price * (1-contract_price))
    return fee
result = check_markets_arbitrage(0.22, 0.81, 0.19, 0.86, 100.0)
async def main():
    load_dotenv()
    env = Environment.PROD
    
    kalshi_api_key_id = os.getenv("KALSHI_TEST_API_ID")
    private_key = load_private_key_from_file(os.getenv("KALSHI_TEST_PRIVATE_KEY_PATH"))
    queue = asyncio.Queue()
    
    polymarket_client = AsyncMarketDataClient(callback=lambda data: queue.put_nowait(("polymarket", data)))
    kalshi_client = KalshiWebSocketClient(kalshi_api_key_id, private_key, env, callback=lambda data: queue.put_nowait(("kalshi", data)))

    tasks = [
        asyncio.create_task(polymarket_client.connect("0xfa48a99317daef1654d5b03e30557c4222f276657275628d9475e141c64b545d")),
        asyncio.create_task(kalshi_client.connect()),
        asyncio.create_task(message_consumer(queue))
    ]

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    
if __name__ == "__main__":
    asyncio.run(main())
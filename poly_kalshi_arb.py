from polymarket_api import AsyncMarketDataClient
from kalshi_api import KalshiWebSocketClient, Environment
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
import asyncio
import math
import os
from decimal import Decimal, getcontext
from dotenv import load_dotenv
getcontext().prec = 8

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
    markets = ['Nuggets', 'Thunder', 'KXNBAGAME-25MAY13DENOKC-DEN', 'KXNBAGAME-25MAY13DENOKC-OKC']
    while True:
        source_name, payload = await queue.get()
        # e.g. combine Polymarket + Kalshi data, or forward to UI, DB, etc.
        print(f"[{source_name}]", payload['best_offers'])
        if source_name == "polymarket":
            polymarket_offers = payload['best_offers']
        elif source_name == "kalshi":
            kalshi_offers = payload['best_offers']
        # Check for arbitrage opportunities
        if not polymarket_offers or not kalshi_offers:
            continue
        result = check_markets_arbitrage(polymarket_offers[markets[0]]["best_ask"][0], polymarket_offers[markets[1]]["best_ask"][0], kalshi_offers[markets[2]]["best_ask"][0]/100.0, kalshi_offers[markets[3]]["best_ask"][0]/100.0, shares=1.0)
        if result["is_arbitrage"]:
            m1_action, m2_action, profit_per_share = result["market1_action"], result["market2_action"], result["profit_per_share"]
            print("arbitrage opportunity found! Strategy:", result["strategy"])
            print("Market prices:", polymarket_offers[markets[m1_action]]["best_ask"], kalshi_offers[markets[m2_action+2]]["best_ask"])
            max_size_without_slippage = min(Decimal(polymarket_offers[markets[m1_action]]["best_ask"][1]), Decimal(kalshi_offers[markets[m2_action+2]]["best_ask"][1]))
            print(f"Max size without slippage: {max_size_without_slippage}, Max Profit: {profit_per_share * max_size_without_slippage}")
        queue.task_done()


def check_arbitrage(market1_price: Decimal, market2_inverse_price: Decimal, shares: Decimal):
    market2_fee = calculate_kalshi_fees(market2_inverse_price, shares)
    market2_fee = 0
    profit_if_win_market1 = (1 - market1_price) * shares
    profit_if_win_market2 = (1 - market2_inverse_price) * shares - market2_fee
    cost_market1 = market1_price * shares
    cost_market2 = market2_inverse_price * shares + market2_fee

    pnl_if_win_market1 = profit_if_win_market1 - cost_market2
    pnl_if_lose_market1 = profit_if_win_market2 - cost_market1


    return {
        "is_arbitrage": (pnl_if_lose_market1 > 0) and (pnl_if_win_market1 > 0),
        "pnl_if_win": pnl_if_win_market1,
        "pnl_if_lose": pnl_if_lose_market1,
    }


def check_markets_arbitrage(m1_yes, m1_no, m2_yes, m2_no, shares=100.0):
    m1_yes, m1_no, m2_yes, m2_no, shares = Decimal(m1_yes), Decimal(m1_no), Decimal(m2_yes), Decimal(m2_no), Decimal(shares)
    pm1 = check_arbitrage(m1_yes, m2_no,  shares)
    pm2 = check_arbitrage(m1_no, m2_yes,  shares)

    # profit is the same in both outcomes whenever arbitrage exists
    profit1 = pm1["pnl_if_win"]
    profit2 = pm2["pnl_if_win"]

    is_arbitrage = profit1 > 0 or profit2 > 0
    strategy = None
    market1_action, market2_action, profit_per_share = None, None, None
    if is_arbitrage:
        if profit1 > profit2:
            strategy = f"bet yes on market 1 @ {m1_yes} and no on market 2 @ {m2_no}. Profit Per Share: {profit1}"
            market1_action = 0
            market2_action = 1
            profit_per_share = profit1
        else:
            strategy = f"bet no on market 1 @ {m1_no} and yes on market 2 @ {m2_yes}. Profit Per Share: {profit2}"
            market1_action = 1
            market2_action = 0
            profit_per_share = profit2

    return {
        "is_arbitrage": is_arbitrage,
        "strategy": strategy,
        "market1_action": market1_action,
        "market2_action": market2_action,
        "profit_per_share": profit_per_share,
    }


def round_up(value, decimal_places=2):
    multiplier = 10 ** decimal_places
    return math.ceil(value * multiplier) / multiplier
    
def calculate_kalshi_fees(contract_price: Decimal, shares: Decimal, fee_rate=0.07) -> Decimal:
    shares, contract_price, fee_rate = Decimal(shares), Decimal(contract_price), Decimal(fee_rate)
    fee = (fee_rate * shares * contract_price * (1-contract_price)).quantize(Decimal('0.01'), rounding="ROUND_UP")
    return fee

async def main():
    load_dotenv()
    env = Environment.PROD
    kalshi_api_key_id = os.getenv("KALSHI_TEST_API_ID")
    private_key = load_private_key_from_file(os.getenv("KALSHI_TEST_PRIVATE_KEY_PATH"))
    queue = asyncio.Queue()
    
    polymarket_client = AsyncMarketDataClient(callback=lambda data: queue.put_nowait(("polymarket", data)))
    kalshi_client = KalshiWebSocketClient(kalshi_api_key_id, private_key, env, callback=lambda data: queue.put_nowait(("kalshi", data)))

    tasks = [
        asyncio.create_task(polymarket_client.connect("0xd6f4deb24ebb0b924d9531d239d62e2b18230c3f74d8b789735651a729cb662c")),
        asyncio.create_task(kalshi_client.connect(tickers=["KXNBAGAME-25MAY13DENOKC-DEN", "KXNBAGAME-25MAY13DENOKC-OKC"])),
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
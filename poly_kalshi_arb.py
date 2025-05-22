from polymarket_api import AsyncMarketDataClient
from kalshi_api import KalshiWebSocketClient, Environment
from py_clob_client.clob_types import ApiCreds
from py_clob_client.order_builder.constants import BUY
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
import asyncio
import math
import os
from decimal import Decimal, getcontext
from dotenv import load_dotenv
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
getcontext().prec = 8

class RealTimeGraph:
    def __init__(self, master, market_labels):
        self.master = master
        master.title("Real-time Market Prices")

        self.fig, self.ax = plt.subplots()
        self.canvas = FigureCanvasTkAgg(self.fig, master=master)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)

        self.market_labels = market_labels
        
        self.ax.set_ylabel("Price (0-1)")
        self.ax.set_xticks(range(len(self.market_labels)))
        self.ax.set_xticklabels(self.market_labels, rotation=15, ha="right")
        self.ax.set_ylim(0, 1.05) 
        self.fig.tight_layout()

        self.bars = self.ax.bar(range(len(self.market_labels)), [0]*len(self.market_labels), width=0.8, color='skyblue')
        self.bar_labels = self.ax.bar_label(self.bars)
        self.canvas.draw_idle()

    def update_graph(self, p1, p2, k1, k2):
        data_values = [float(p1), float(p2), float(k1), float(k2)]
        
        for bar_obj, height in zip(self.bars, data_values):
            bar_obj.set_height(height)
        
        for label in self.bar_labels:
            label.remove()
        self.bar_labels = self.ax.bar_label(self.bars)
        self.canvas.draw_idle()


def load_private_key_from_file(file_path: str) -> rsa.RSAPrivateKey:
    with open(file_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )
    return private_key

async def run_tk_event_loop(root, interval=0.01):
    try:
        while root.winfo_exists():
            root.update_idletasks()
            root.update()
            await asyncio.sleep(interval)
        print("Tkinter window was closed.")
    except tk.TclError as e:
        if "application has been destroyed" not in str(e).lower():
            print(f"Unexpected TclError in tk_event_loop: {e}")
        else:
            print("Tkinter application destroyed (tk_event_loop).")
    except asyncio.CancelledError:
        print("Tkinter event loop task cancelled.")
        if root.winfo_exists():
            root.destroy()
        raise
async def message_consumer(
    queue: asyncio.Queue, 
    polymarket_client: AsyncMarketDataClient, 
    kalshi_client: KalshiWebSocketClient,
    real_time_graph: RealTimeGraph     
):
    """Centralized consumer of all WS messages."""
    polymarket_offers = {}
    kalshi_offers = {}
    prev_price_levels = []
    prev_levels = []
    total_profit = Decimal('0') # Use Decimal for profit/cost
    total_cost = Decimal('0')

    # These are Polymarket outcomes and Kalshi tickers
    

    markets = ['Dodgers', 'Diamondbacks', "KXMLBGAME-25MAY21AZLAD-LAD", "KXMLBGAME-25MAY21AZLAD-AZ"]
    
    # Mapping Polymarket outcomes to their corresponding "yes" token_id.
    # This will be populated when the first Polymarket message with token_ids arrives.
    # Or, ideally, the AsyncMarketDataClient could provide a method to get token_id by outcome.
    # For now, we rely on token_id being in polymarket_offers after client modification.
    arbitrage_regime = False
    arbitrage_start = None
    arbitrage_times = []
    #plot 

    while True:
        source_name, payload = await queue.get()
        
        if source_name == "polymarket":
            polymarket_offers = payload['best_offers']
        elif source_name == "kalshi":
            kalshi_offers = payload['best_offers']

        # Check for arbitrage opportunities
        # Ensure all necessary keys (outcomes/tickers) are present in the offers
        required_pm_keys = markets[:2]
        required_kalshi_keys = markets[2:]

        if not all(m in polymarket_offers for m in required_pm_keys) or \
           not all(m in kalshi_offers for m in required_kalshi_keys):
            # print("[INFO] Missing market data for arbitrage check. Waiting for more data.")
            await asyncio.sleep(0.1) # Avoid busy-looping if data is temporarily missing
            queue.task_done()
            continue
        
        # Ensure best_ask is available
        try:
            p1_data = polymarket_offers[markets[0]]["best_ask"]
            p2_data = polymarket_offers[markets[1]]["best_ask"]
            k1_data = kalshi_offers[markets[2]]["best_ask"]
            k2_data = kalshi_offers[markets[3]]["best_ask"]
            
            if not all([p1_data, p2_data, k1_data, k2_data]):
                # print("[INFO] Missing best_ask data in one of the offers.")
                await asyncio.sleep(0.1)
                queue.task_done()
                continue

            p1 = Decimal(p1_data[0])
            p2 = Decimal(p2_data[0])
            k1 = Decimal(k1_data[0]) / Decimal("100") # Kalshi prices are 1-99, convert to 0.01-0.99 for check_arbitrage
            k2 = Decimal(k2_data[0]) / Decimal("100")
            real_time_graph.update_graph(p1, p2, k1, k2) # Update the graph with new data
        except (KeyError, TypeError, IndexError) as e:
            print(f"[ERROR] Could not extract price data: {e}. Offers: PM={polymarket_offers}, Kalshi={kalshi_offers}")
            queue.task_done()
            continue
        
        
        result = check_markets_arbitrage(p1, p2, k1, k2, shares=Decimal("1.0")) # Use Decimal for shares
        
        cur_levels = [p1_data, p2_data, k1_data, k2_data]
        if not prev_levels or cur_levels != prev_levels:
            print(f"{markets[0]}: {p1_data}, {markets[1]}: {p2_data}, {markets[2][-3:]}: {k1_data}, {markets[3][-3:]}: {k2_data}, Arb PNLs: M1={result['market1_pnl']:.4f}, M2={result['market2_pnl']:.4f}")
        prev_levels = cur_levels

        if result["is_arbitrage"]:
            if not arbitrage_regime:
                print(f"[INFO] Arbitrage regime started at {result['strategy']}")
                arbitrage_regime = True
                arbitrage_start = asyncio.get_event_loop().time()
            m1_action_idx = result["market1_action"] # 0 for markets[0] (e.g. Phillies), 1 for markets[1] (e.g. Rockies)
            m2_action_idx = result["market2_action"] # 0 for Kalshi's version of markets[0], 1 for Kalshi's version of markets[1]
            profit_per_share = result["profit_per_share"]

            # Current prices for comparison with previous
            current_price_levels = [p1_data[0], p2_data[0], k1_data[0], k2_data[0]]
            if prev_price_levels and current_price_levels == prev_price_levels:
                print(f"No price change, skipping arbitrage opportunity. Total profit: {total_profit:.4f}, Total cost: {total_cost:.4f}")
                queue.task_done()
                continue
            
            # Polymarket details
            pm_outcome_name = markets[m1_action_idx]
            pm_order_details = polymarket_offers[pm_outcome_name]
            pm_token_id = pm_order_details.get("token_id") 
            
            if not pm_token_id:
                print(f"[ERROR] Missing token_id for Polymarket outcome {pm_outcome_name}. Offers: {pm_order_details}")
                queue.task_done()
                continue

            pm_price_to_buy = Decimal(pm_order_details["best_ask"][0])
            pm_available_size = Decimal(pm_order_details["best_ask"][1])

            # Kalshi details
            # If m2_action_idx = 0, we use markets[2] (e.g. KXMLBGAME-25MAY19PHICOL-PHI)
            # If m2_action_idx = 1, we use markets[3] (e.g. KXMLBGAME-25MAY19PHICOL-COL)
            kalshi_ticker_to_buy = markets[m2_action_idx + 2] 
            kalshi_order_details = kalshi_offers[kalshi_ticker_to_buy]
            kalshi_price_to_buy_cents = Decimal(kalshi_order_details["best_ask"][0]) # This is already in cents (1-99)
            kalshi_available_size = Decimal(kalshi_order_details["best_ask"][1])

            print(f"Arbitrage found: {result['strategy']}. PM Ask: {pm_order_details['best_ask']}, Kalshi Ask: {kalshi_order_details['best_ask']}")

            max_size_without_slippage = min(pm_available_size, kalshi_available_size)
            
            if max_size_without_slippage <= Decimal("0"): # Or some minimum trade size
                print(f"Calculated max size is {max_size_without_slippage}, too small to trade.")
                queue.task_done()
                continue

            # For now, let's cap the trade size for testing, e.g., 1 contract/share
            # trade_size = min(max_size_without_slippage, Decimal("1.0")) 
            trade_size = max_size_without_slippage # Uncomment for full size

            cost_pm = pm_price_to_buy * trade_size
            cost_kalshi = (kalshi_price_to_buy_cents / Decimal("100")) * trade_size
            total_potential_cost_for_arb = cost_pm + cost_kalshi
            potential_profit_for_arb = profit_per_share * trade_size
            
            print(f"Max size: {max_size_without_slippage}, Trading size: {trade_size}, Potential Profit: {potential_profit_for_arb:.4f}, Potential Cost: {total_potential_cost_for_arb:.4f}")

            # --- Attempt to place orders ---
            try:
                print(f"Attempting to place Polymarket order: BUY {float(trade_size)} of {pm_outcome_name} (TokenID: {pm_token_id}) @ {float(pm_price_to_buy)}")
                '''
                await polymarket_client.place_order(
                    token_id=pm_token_id,
                    price=float(pm_price_to_buy), # py_clob_client expects float
                    size=float(trade_size),       # py_clob_client expects float
                    side=BUY,                     # We are always buying the ASK in this arb setup
                    use_proxy=True                # Use proxy to bypass geo-blocking
                )
                print("Polymarket order attempt successful.")

                print(f"Attempting to place Kalshi order: BUY {int(trade_size)} of {kalshi_ticker_to_buy} @ {int(kalshi_price_to_buy_cents)}c, side 'yes'")
                #fill or kill currently not supported in Kalshi api 2.0.4, will be added in 2.0.5
                await kalshi_client.place_order(
                    ticker=kalshi_ticker_to_buy,
                    price=int(kalshi_price_to_buy_cents), # Kalshi expects price in cents (integer)
                    size=int(trade_size),                 # Kalshi expects integer size
                    side="yes",                           # Always buy "yes"
                    post_only=True,                       # Taker for this arbitrage
                    time_in_force="fill_or_kill"          # FOK for immediate execution
                )
                await kalshi_client.place_order(
                    ticker=kalshi_ticker_to_buy,
                    price=int(kalshi_price_to_buy_cents), # Kalshi expects price in cents (integer)
                    size=int(trade_size),                 # Kalshi expects integer size
                    side="yes",                           # Always buy "yes"
                    expiration_ts=0                       # Expiration set in the past, IOC order   
                )
                print("Kalshi order attempt successful.")
                '''
                # If both orders are successfully submitted (not necessarily filled yet, but FOK helps)
                total_cost += total_potential_cost_for_arb
                total_profit += potential_profit_for_arb
                prev_price_levels = current_price_levels # Update price levels to avoid re-trading same opportunity immediately
                print(f"Arbitrage orders submitted. Current Total Profit: {total_profit:.4f}, Current Total Cost: {total_cost:.4f}")

            except Exception as e:
                print(f"Error during order placement: {e}")
                # Not updating prev_price_levels here, so it might retry if the error was transient
        else:
            if arbitrage_regime:
                print(f"[INFO] Arbitrage regime ended. Total profit: {total_profit:.4f}, Total cost: {total_cost:.4f}")
                arbitrage_regime = False
                arbitrage_times.append(asyncio.get_event_loop().time() - arbitrage_start)
                arbitrage_start = None
                print(f"Arbitrage times: {arbitrage_times}")
        queue.task_done()


def check_arbitrage(market1_price: Decimal, market2_inverse_price: Decimal, shares: Decimal):
    market2_fee = calculate_kalshi_fees(market2_inverse_price, shares)
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
        "market1_pnl": profit1,
        "market2_pnl": profit2,
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
    env = Environment.PROD # Or Environment.DEMO
    kalshi_api_key_id = os.getenv("KALSHI_API_ID") 
    kalshi_private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    
    if not all([kalshi_api_key_id, kalshi_private_key_path]):
        print("Kalshi API ID or Private Key Path not found in .env")
        return
    kalshi_private_key = load_private_key_from_file(kalshi_private_key_path)

    POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")
    POLY_PROXY_ADDRESS = os.getenv("POLY_PROXY_ADDRESS") # Funder address for Polymarket
    
    # Ensure Polymarket API creds are loaded
    poly_api_key = os.getenv("POLY_API_KEY")
    poly_api_secret = os.getenv("POLY_API_SECRET")
    poly_api_passphrase = os.getenv("POLY_API_PASSPHRASE")

    if not all([POLY_PRIVATE_KEY, poly_api_key, poly_api_secret, poly_api_passphrase]):
        print("Polymarket credentials or private key not found in .env")
        return
        
    api_creds = ApiCreds(
        api_key=poly_api_key,
        api_secret=poly_api_secret,
        api_passphrase=poly_api_passphrase,
    )

    polymarket_order_proxies = {
        "http": os.getenv("PROXY"),
        "https": os.getenv("PROXY"),
    }
    queue = asyncio.Queue()
    
    # Initialize clients
    polymarket_client = AsyncMarketDataClient(
        api_creds=api_creds, 
        private_key=POLY_PRIVATE_KEY, 
        funder=POLY_PROXY_ADDRESS,
        proxies=polymarket_order_proxies,
        callback=lambda data: queue.put_nowait(("polymarket", data))
    )
    kalshi_client = KalshiWebSocketClient(
        kalshi_api_key_id, 
        kalshi_private_key, 
        env, 
        callback=lambda data: queue.put_nowait(("kalshi", data))
    )

    # Polymarket condition ID
    polymarket_condition_id = "0x8c85f2635638f08e8e0c3c1114489424dc120c4eba66233884ae54c815f19d08" 



    # Kalshi tickers
    kalshi_tickers = ["KXMLBGAME-25MAY21AZLAD-LAD", "KXMLBGAME-25MAY21AZLAD-AZ"] 

    root = tk.Tk()
    root.geometry("800x600")
    real_time_graph = RealTimeGraph(root, market_labels=["PM LA Dodgers", "PM AZ Diamondbacks", "Kalshi LA Dodgers", "Kalshi AZ Diamondbacks"])
    tasks = [
        asyncio.create_task(run_tk_event_loop(root), name="TkinterLoop"),
        asyncio.create_task(polymarket_client.connect(polymarket_condition_id)),
        asyncio.create_task(kalshi_client.connect(tickers=kalshi_tickers)),
        asyncio.create_task(message_consumer(queue, polymarket_client, kalshi_client, real_time_graph)) 
    ]

    try:
        print("Starting arbitrage bot...")
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("Shutting down arbitrage bot...")
    finally:
        print("Cancelling tasks...")
        for task in tasks:
            task.cancel()
        # Wait for tasks to acknowledge cancellation
        await asyncio.gather(*tasks, return_exceptions=True)
        print("All tasks cancelled.")
    
if __name__ == "__main__":
    if os.path.exists(".env"):
        load_dotenv()
        print(".env file loaded.")
    else:
        print(".env file not found. Please ensure your API keys and other configurations are set as environment variables or in a .env file.")
    
    asyncio.run(main())
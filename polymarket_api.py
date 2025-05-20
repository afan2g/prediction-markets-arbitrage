from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL
import asyncio
import json
import websockets  # Need to use asyncio-compatible websockets library
from decimal import *

class AsyncMarketDataClient:
    """
    A client for connecting to and processing CLOB (Central Limit Order Book) market data
    through both REST API and WebSocket connections using asyncio.
    """
    
    def __init__(self, rest_url="https://clob.polymarket.com/", 
                 ws_url="wss://ws-subscriptions-clob.polymarket.com/ws/", 
                 private_key=None, funder=None,
                 api_creds=None, chain_id=137, callback=None):
        """
        Initialize the AsyncMarketDataClient with connection parameters.
        
        Args:
            rest_url (str): The REST API endpoint URL
            ws_url (str): The WebSocket endpoint URL
            api_key (str): API key for authentication
            chain_id (int): Blockchain chain ID
        """
        self.REST = rest_url
        self.WSS = ws_url
        self.chain_id = chain_id
        self.orderbook = {}
        self.client = ClobClient(self.REST, key=private_key, chain_id=self.chain_id, signature_type=2, funder=funder, creds=api_creds)
        self.websocket = None
        self._running = False
        self._task = None
        self._callback = callback
        self.tick_size = None
        self.decimal_places = 2




    def parse_message(self, messages):
        """
        Parse incoming WebSocket messages and update the orderbook accordingly.
        
        Args:
            messages (list): List of message dictionaries
        """
        for message in messages:
            if message["event_type"] == "book":
                self.update_orderbook(message)
            elif message["event_type"] == "price_change":
                self.update_orderbook_from_price_change(message)
            elif message["event_type"] == "tick_size_change":
                print("[polymarket] received tick size change")
                self.tick_size = message["new_tick_size"]
                self.decimal_places = len(str(self.tick_size).split(".")[1]) if "." in str(self.tick_size) else 0
                getcontext().prec = self.decimal_places + 2
            # elif message["event_type"] == "last_trade_price":
            #     print("last trade price")
            # else:
            #     print("received unknown message", message)

    async def on_connect(self, websocket, condition_id):
        """
        WebSocket connection opened handler. Subscribes to market data.
        
        Args:
            websocket: WebSocket connection object
        """
        print("[polymarket] WebSocket connection opened.")
        asset_ids = self.get_markets(condition_id)
        # Subscribe to the desired channels
        subscribe_message = {
            "type": "market",
            "assets_ids": [asset[0] for asset in asset_ids],
        }
        print("[polymarket] Subscribing to assets:", asset_ids)
        await websocket.send(json.dumps(subscribe_message))

    def get_markets(self, condition_id):
        """
        Get market data for a given condition ID and initialize orderbook.
        
        Args:
            condition_id (str): The market condition ID
            
        Returns:
            list: List of asset IDs in the market
        """
        print("[polymarket] Getting Polymarket markets for Condition ID:", condition_id)
        market = self.client.get_market(condition_id)
        print("[polymarket] market retrieved:", market)
        self.tick_size = market["minimum_tick_size"]
        self.decimal_places = len(str(self.tick_size).split(".")[1]) if "." in str(self.tick_size) else 0
        getcontext().prec = self.decimal_places + 2
        asset_ids = []
        for token in market["tokens"]:
            token_id, outcome = token["token_id"], token["outcome"]
            asset_ids.append((token["token_id"], outcome))
            self.orderbook[token_id] = self.client.get_order_book(token_id).__dict__
            self.orderbook[token_id]["outcome"] = outcome

        # print("Parsed Orderbook:", self.orderbook)
        return asset_ids

    def update_orderbook(self, message):
        """
        Update orderbook with full book information.
        
        Args:
            message (dict): Message containing book data
        """


        asset_id = message["asset_id"]
        self.orderbook[asset_id]["bids"] = message["bids"]
        self.orderbook[asset_id]["asks"] = message["asks"]
        self.orderbook[asset_id]["timestamp"] = message["timestamp"]
        self.orderbook[asset_id]["spread"] = Decimal(message["asks"][-1]["price"]) - Decimal(message["bids"][-1]["price"])
        self.orderbook[asset_id]["mid"] = (Decimal(message["asks"][-1]["price"]) + Decimal(message["bids"][-1]["price"])) / Decimal("2")

    def update_orderbook_from_price_change(self, message):
        """
        Update orderbook from price change messages.
        
        Args:
            message (dict): Message containing price changes
        """
        asset_id, changes = message["asset_id"], message["changes"]
        for change in changes:
            price, side, size = change["price"], change["side"], change["size"]
            self.update_orderbook_levels(asset_id, price, side, size)

        self.orderbook[asset_id]["timestamp"] = message["timestamp"]
        self.orderbook[asset_id]["spread"] = Decimal(self.orderbook[asset_id]["asks"][-1]["price"]) - Decimal(self.orderbook[asset_id]["bids"][-1]["price"])
        self.orderbook[asset_id]["mid"] = (Decimal(self.orderbook[asset_id]["asks"][-1]["price"]) + Decimal(self.orderbook[asset_id]["bids"][-1]["price"])) / Decimal("2")

    def update_orderbook_levels(self, asset_id, price, side, size):
        """
        Update specific price levels in the orderbook.
        
        Args:
            asset_id (str): Asset ID
            price (str): Price level
            side (str): "BUY" or "SELL"
            size (str): Size at the price level
        """
        trade_side = "bids" if side == "BUY" else "asks"
        index = self.find_index(price, asset_id, trade_side)
        if index == len(self.orderbook[asset_id][trade_side]):
            self.orderbook[asset_id][trade_side].append({"price": price, "size": size})
            return
        if self.orderbook[asset_id][trade_side][index]["price"] != price:
            self.orderbook[asset_id][trade_side].insert(index, {"price": price, "size": size})
        else:
            if size == 0:
                self.orderbook[asset_id][trade_side].pop(index)
            else:
                self.orderbook[asset_id][trade_side][index]["size"] = size

    def get_best_bidasks(self):
        """
        Get the best bid and ask for each asset in the orderbook.
        
        Returns:
            dict: Dictionary mapping outcomes to their best bid/ask data including token_id
        """
        best_bidasks = {}
        for asset_id, book in self.orderbook.items(): 
            if book.get("bids") and book.get("asks") and book["bids"] and book["asks"]:
                best_bid = book["bids"][-1]
                best_ask = book["asks"][-1]
                best_bidasks[book["outcome"]] = {
                    "token_id": asset_id,  
                    "best_bid": (best_bid['price'], best_bid["size"]),
                    "best_ask": (best_ask['price'], best_ask["size"]),
                    "spread": str(Decimal(best_ask["price"]) - Decimal(best_bid["price"])),
                    "timestamp": book["timestamp"],
                }
        return best_bidasks
    
    async def place_order(self, token_id: str, price: float, size: float, side: str): 
        print(f"[polymarket] placing order: {side} {size} of {token_id} @ {price}")
        order_args = OrderArgs(
            token_id=token_id,
            price=price,  # py_clob_client expects float for price
            size=size,    # py_clob_client expects float for size
            side=side     
        )
        
        loop = asyncio.get_running_loop()
        try:
            # self.client methods are synchronous, run them in an executor
            signed_order = await loop.run_in_executor(None, self.client.create_order, order_args)
            print(f"[polymarket] Signed order: {signed_order}")
            response = await loop.run_in_executor(None, self.client.post_order, signed_order, OrderType.FOK) # Use FOK for arbs
            print(f"[polymarket] Order placement response: {response}")

            if isinstance(response, dict) and response.get("status") == "error": # py_clob_client might return dict on error
                 raise Exception(f"Polymarket order placement failed: {response.get('message', 'Unknown error')}")
            

        except Exception as e:
            print(f"[polymarket] Error placing order: {e}")
            raise  
    
    async def websocket_handler(self, condition_id=None):
        """
        Main coroutine that handles WebSocket connection and message processing.
        
        Args:
            condition_id (str, optional): Market condition ID to subscribe to.
        """

            
        uri = self.WSS + "market"
        async with websockets.connect(uri) as websocket:
            self.websocket = websocket
            self._running = True
            
            # Subscribe to channels upon connection
            await self.on_connect(websocket, condition_id)
            
            # Message processing loop
            try:
                while self._running:
                    message = await websocket.recv()
                    message_data = json.loads(message)
                    self.parse_message(message_data)
                    best_bids = self.get_best_bidasks()
                    result =  {
                        "market": "Polymarket",
                        "best_offers": best_bids,
                    }

                    if self._callback:
                        self._callback(result)
                    
                
            except websockets.exceptions.ConnectionClosed:
                print("[polymarket] WebSocket connection closed.")
                print("[polymarket] orderbook:", self.orderbook)
            except Exception as e:
                print(f"[polymarket] Error in Polymarket WebSocket handler: {e}")
            finally:
                self._running = False
                self.websocket = None
    
    async def connect(self, condition_id=None):
        """
        Connect to the WebSocket and start processing messages.
        
        Args:
            condition_id (str, optional): Market condition ID to subscribe to.
                                         If None, you'll need to call get_markets later.
        """
        if self._running:
            print("[polymarket] Already connected")
            return
            
        # Start WebSocket handler as a task
        self._task = asyncio.create_task(self.websocket_handler(condition_id))
        
    async def disconnect(self):
        """Close the WebSocket connection."""
        self._running = False
        if self.websocket:
            await self.websocket.close()
        
        if self._task:
            await self._task
            
    def is_connected(self):
        """
        Check if the WebSocket connection is active.
        
        Returns:
            bool: True if connected, False otherwise
        """
        return self._running and self.websocket is not None

    async def place_order(self, token_id: str, price: float, size: float):
        print("[polymarket] placing order")
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=BUY
        )
        signed_order = self.client.create_order(order_args)
        self.client.post_order(signed_order, OrderType.FOK)

    def find_index(self, price, asset_id, side):
        arr = self.orderbook[asset_id][side]
        price = Decimal(price)
        l,r = 0, len(arr)-1
        while l <= r:
            mid = (l+r)// 2
            if Decimal(arr[mid]["price"]) == price:
                return mid
            elif Decimal(arr[mid]["price"]) < price:
                l = mid + 1
            else:
                r = mid - 1
        return l
# Example usage:
async def main():
    # Create client instance
    client = AsyncMarketDataClient()
    
    # Connect with a specific condition ID
    await client.connect("0xfa48a99317daef1654d5b03e30557c4222f276657275628d9475e141c64b545d")
    
    try:
        # Keep the main coroutine running
        while client.is_connected():
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        # Graceful shutdown on Ctrl+C
        pass
    finally:
        # Ensure clean disconnect
        await client.disconnect()
        print("[polymarket] Client disconnected.")

if __name__ == "__main__":
    asyncio.run(main())
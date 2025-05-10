from py_clob_client.client import ClobClient
import asyncio
import json
import websockets  # Need to use asyncio-compatible websockets library


class AsyncMarketDataClient:
    """
    A client for connecting to and processing CLOB (Central Limit Order Book) market data
    through both REST API and WebSocket connections using asyncio.
    """
    
    def __init__(self, rest_url="https://clob.polymarket.com/", 
                 ws_url="wss://ws-subscriptions-clob.polymarket.com/ws/", 
                 api_key="", chain_id=137, callback=None):
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
        self.key = api_key
        self.chain_id = chain_id
        self.orderbook = {}
        self.client = ClobClient(self.REST, key=self.key, chain_id=self.chain_id)
        self.websocket = None
        self._running = False
        self._task = None
        self._callback = callback




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
            # elif message["event_type"] == "tick_size_change":
            #     print("received tick size change")
            # elif message["event_type"] == "last_trade_price":
            #     print("last trade price")
            # else:
            #     print("received unknown message", message)

    async def on_connect(self, websocket):
        """
        WebSocket connection opened handler. Subscribes to market data.
        
        Args:
            websocket: WebSocket connection object
        """
        print("WebSocket connection opened.")
        # Subscribe to the desired channels
        asset_ids = self.get_markets("0xfc0c7d71b0a6fba179e4b37db95648faa37eadbfb48e611006c92a0ec30b12d2")
        subscribe_message = {
            "type": "market",
            "assets_ids": asset_ids,
        }
        print("Subscribing to assets:", asset_ids)
        await websocket.send(json.dumps(subscribe_message))

    def get_markets(self, condition_id):
        """
        Get market data for a given condition ID and initialize orderbook.
        
        Args:
            condition_id (str): The market condition ID
            
        Returns:
            list: List of asset IDs in the market
        """
        print("Condition ID:", condition_id)
        market = self.client.get_market(condition_id)
        self.tick_size = market["minimum_tick_size"]
        asset_ids = []
        for token in market["tokens"]:
            if token["outcome"] != "Yes" and token["outcome"] != "No":
                asset_ids.append(token["token_id"])
                self.orderbook[token["token_id"]] = self.client.get_order_book(token["token_id"]).__dict__
                self.orderbook[token["token_id"]]["outcome"] = token["outcome"]

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
        self.orderbook[asset_id]["spread"] = round(float(message["asks"][-1]["price"]) - float(message["bids"][-1]["price"]),2)
        self.orderbook[asset_id]["mid"] = round((float(message["asks"][-1]["price"]) + float(message["bids"][-1]["price"])) / 2,2)
        # print("Orderbook updated from book")

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
        self.orderbook[asset_id]["spread"] = round(float(self.orderbook[asset_id]["asks"][-1]["price"]) - float(self.orderbook[asset_id]["bids"][-1]["price"]),2)
        self.orderbook[asset_id]["mid"] = round((float(self.orderbook[asset_id]["asks"][-1]["price"]) + float(self.orderbook[asset_id]["bids"][-1]["price"])) / 2,2)
        # print("Orderbook updated from price change")

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
        n = len(self.orderbook[asset_id][trade_side])
        for i in range(n-1, -1, -1):
            if self.orderbook[asset_id][trade_side][i]["price"] == price:
                self.orderbook[asset_id][trade_side][i]["size"] = size
                break

    def get_best_bidasks(self):
        """
        Get the best bid and ask for each asset in the orderbook.
        
        Returns:
            dict: Dictionary mapping outcomes to their best bid/ask data
        """
        best_bidasks = {}
        for asset_id, book in self.orderbook.items():
            if book["bids"] and book["asks"]:
                best_bid = book["bids"][-1]
                best_ask = book["asks"][-1]
                best_bidasks[book["outcome"]] = {
                    "best_bid": (round(float(best_bid['price']),2), round(float(best_bid["size"]),2)),
                    "best_ask": (round(float(best_ask['price']),2), round(float(best_ask["size"]),2)),
                    "spread": round(float(best_ask["price"]) - float(best_bid["price"]), 2),
                    "timestamp": book["timestamp"],
                }
        return best_bidasks
    
    async def websocket_handler(self, condition_id=None):
        """
        Main coroutine that handles WebSocket connection and message processing.
        
        Args:
            condition_id (str, optional): Market condition ID to subscribe to.
        """
        if condition_id:
            # Pre-fetch market data so it's ready when WS connects
            self.get_markets(condition_id)
            
        uri = self.WSS + "market"
        async with websockets.connect(uri) as websocket:
            self.websocket = websocket
            self._running = True
            
            # Subscribe to channels upon connection
            await self.on_connect(websocket)
            
            # Message processing loop
            try:
                while self._running:
                    message = await websocket.recv()
                    message_data = json.loads(message)
                    self.parse_message(message_data)
                    best_bids = self.get_best_bidasks()
                    # for outcome, bidasks in best_bids.items():
                    #     print(f"Polymarket {outcome}: best bid: {bidasks['bid']} best ask: {bidasks['ask']} spread: {round(bidasks['spread'], 2)} timestamp: {bidasks['timestamp']}")
                    result =  {
                        "market": "Polymarket",
                        "best_offers": best_bids,
                    }

                    if self._callback:
                        self._callback(result)
                    
                
            except websockets.exceptions.ConnectionClosed:
                print("WebSocket connection closed.")
                print("orderbook:", self.orderbook)
            except Exception as e:
                print(f"Error in WebSocket handler: {e}")
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
            print("Already connected")
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
        print("Client disconnected.")

if __name__ == "__main__":
    asyncio.run(main())
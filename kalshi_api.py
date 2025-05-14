import time
from datetime import datetime, timedelta
from enum import Enum
import json
from typing import Dict, Any, Optional
import base64
from dotenv import load_dotenv
import os
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature

import websockets
import asyncio

class Environment(Enum):
    DEMO = "demo"
    PROD = "prod"


class KalshiBaseClient:
    """Base client class for interacting with the Kalshi API."""
    def __init__(
        self,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.DEMO,
    ):
        """Initializes the client with the provided API key and private key.

        Args:
            key_id (str): Your Kalshi API key ID.
            private_key (rsa.RSAPrivateKey): Your RSA private key.
            environment (Environment): The API environment to use (DEMO or PROD).
        """
        self.key_id = key_id
        self.private_key = private_key
        self.environment = environment
        self.last_api_call = datetime.now()
        self.orderbook = {}
        self.best_offers = {
            "market": "Kalshi",
            "best_offers": None,
            "timestamp": int(round(time.time() * 1000))
        }

        if self.environment == Environment.DEMO:
            self.HTTP_BASE_URL = "https://demo-api.kalshi.co"
            self.WS_BASE_URL = "wss://demo-api.kalshi.co"
        elif self.environment == Environment.PROD:
            self.HTTP_BASE_URL = "https://api.elections.kalshi.com"
            self.WS_BASE_URL = "wss://api.elections.kalshi.com"
        else:
            raise ValueError("Invalid environment")

    def request_headers(self, method: str, path: str) -> Dict[str, Any]:
        """Generates the required authentication headers for API requests."""
        current_time_milliseconds = int(time.time() * 1000)
        timestamp_str = str(current_time_milliseconds)

        # Remove query params from path
        path_parts = path.split('?')

        msg_string = timestamp_str + method + path_parts[0]
        signature = self.sign_pss_text(msg_string)

        headers = {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
        }
        return headers

    def sign_pss_text(self, text: str) -> str:
        """Signs the text using RSA-PSS and returns the base64 encoded signature."""
        message = text.encode('utf-8')
        try:
            signature = self.private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            return base64.b64encode(signature).decode('utf-8')
        except InvalidSignature as e:
            raise ValueError("RSA sign PSS failed") from e

class KalshiWebSocketClient(KalshiBaseClient):
    """Client for handling WebSocket connections to the Kalshi API."""
    def __init__(
        self,
        key_id: str,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.DEMO,
        callback: Optional[callable] = None,
    ):
        super().__init__(key_id, private_key, environment)
        self.ws = None
        self.url_suffix = "/trade-api/ws/v2"
        self.message_id = 1  # Add counter for message IDs
        self._callback = callback
        self.tickers = None

    async def connect(self, tickers: Optional[list] = None):
        """Establishes a WebSocket connection using authentication."""
        host = self.WS_BASE_URL + self.url_suffix
        auth_headers = self.request_headers("GET", self.url_suffix)
        self.tickers = tickers
        async with websockets.connect(host, additional_headers=auth_headers) as websocket:
            self.ws = websocket
            await self.on_open()
            await self.handler()

    async def on_open(self):
        """Callback when WebSocket connection is opened."""
        print("Kalshi WebSocket connection opened.")
        await self.subscribe_to_tickers()

    async def subscribe_to_tickers(self):
        """Subscribe to ticker updates for all markets."""
        print("Subscribing to tickers:", self.tickers)
        subscription_message = {
            "id": self.message_id,
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker_v2", "orderbook_delta"],
                "market_tickers": self.tickers
            }
        }
        await self.ws.send(json.dumps(subscription_message))
        self.message_id += 1


    async def handler(self):
        """Handle incoming messages."""
        try:
            async for message in self.ws:
                await self.on_message(message)
        except websockets.ConnectionClosed as e:
            await self.on_close(e.code, e.reason)
        except Exception as e:
            await self.on_error(e)


    async def on_error(self, error):
        """Callback for handling errors."""
        print("Kalshi WebSocket error:", error)

    async def on_close(self, close_status_code, close_msg):
        """Callback when WebSocket connection is closed."""
        print("WebSocket connection closed with code:", close_status_code, "and message:", close_msg)



    async def on_message(self, message):
        """Callback for handling incoming messages."""
        json_message = json.loads(message)
        if json_message["type"] == "orderbook_snapshot":
            self.update_orderbook_from_snapshot(json_message["msg"])
        elif json_message["type"] == "orderbook_delta":
            self.update_orderbook_from_delta(json_message["msg"])
        # elif json_message["type"] == "ticker_v2":
        #     print("Ticker update received")
        best_offers = self.get_best_offers()
        # for market_ticker, data in best_offers.items():
        #     print(f"Kalshi {market_ticker[-3::]}: best bid: {data['best_bid']} best ask: {data['best_ask']} spread: {data['spread']} ")
        result =  {
            "market": "Kalshi",
            "best_offers": best_offers,
            "timestamp": int(round(time.time() * 1000))
        }

        if self._callback and best_offers != self.best_offers['best_offers']:
            self.best_offers = result
            self._callback(self.best_offers)
        
    def update_orderbook_from_delta(self, message):
        """Update the orderbook with the latest data."""
        market_ticker = message["market_ticker"]
        side = message["side"]
        price = message["price"]
        delta = message["delta"]
        idx = self.find_index(price, market_ticker, side)
        if idx == len(self.orderbook[market_ticker][side]):
            self.orderbook[market_ticker][side].append((price, delta))
            return
        
        orderbook_level = self.orderbook[market_ticker][side][idx]
        if orderbook_level[0] == price:
            new_quantity = orderbook_level[1] + delta
            if new_quantity <= 0:
                self.orderbook[market_ticker][side].pop(idx)
            else:
                self.orderbook[market_ticker][side][idx] = (price, new_quantity)
        else:
            if delta > 0:
                self.orderbook[market_ticker][side].insert(idx, (price, delta))
                        

    def find_index(self, price: int, ticker: str, side: str) -> int:
        arr = self.orderbook[ticker][side]
        l,r = 0, len(arr)-1
        while l <= r:
            mid = (l+r)// 2
            if arr[mid][0] == price:
                return mid
            elif arr[mid][0] < price:
                l = mid + 1
            else:
                r = mid - 1
        return l
    def update_orderbook_from_snapshot(self, message):
        """Update the orderbook with the latest snapshot."""
        market_ticker = message["market_ticker"]
        self.orderbook[market_ticker] = message


    def get_best_offers(self) -> Dict[str, Dict[str, Any]]:
        """Get the best offers from the orderbook."""
        best_offers = {}
        for market_ticker, data in self.orderbook.items():
            best_bid = data["yes"][-1][0] if data["yes"] else None
            best_ask = 100-data["no"][-1][0] if data["no"] else None
            spread = best_ask - best_bid if best_bid and best_ask else None
            best_offers[market_ticker] = {
                "best_bid": (best_bid, data["yes"][-1][1]) if best_bid else None,
                "best_ask": (best_ask, data["no"][-1][1]) if best_ask else None,
                "spread": spread,
            }
        return best_offers
def load_private_key_from_file(file_path: str) -> rsa.RSAPrivateKey:
    with open(file_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )
    return private_key


if __name__ == "__main__":
    # Example usage
    load_dotenv()
    env = Environment.PROD
    KEYID = os.getenv("KALSHI_TEST_API_ID")
    private_key = load_private_key_from_file("kalshi_test.pem")
    client = KalshiWebSocketClient(KEYID, private_key, Environment.PROD)

    asyncio.run(client.connect())
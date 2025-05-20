import requests
from dotenv import load_dotenv
import os
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType, BalanceAllowanceParams, AssetType, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY, SELL
from py_clob_client.headers.headers import create_level_2_headers
load_dotenv()

host = "https://clob.polymarket.com/"
POLY_PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")
POLY_PROXY_ADDRESS = os.getenv("POLY_PROXY_ADDRESS").lower()
print("POLY_PROXY_ADDRESS:", POLY_PROXY_ADDRESS)
api_creds = ApiCreds(
    api_key=os.getenv("POLY_API_KEY"),
    api_secret=os.getenv("POLY_API_SECRET"),
    api_passphrase=os.getenv("POLY_API_PASSPHRASE"),
)
proxies = {
    "http": os.getenv("PROXY"),
    "https": os.getenv("PROXY"),
}
balance_params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
client = ClobClient(host, key=POLY_PRIVATE_KEY, chain_id=137, signature_type=2, funder=POLY_PROXY_ADDRESS)

print("L1 Client initialized")
client.set_api_creds(client.create_or_derive_api_creds())
print("L2 Client initialized")
print("client balance:", client.get_balance_allowance(balance_params))

order_args = OrderArgs(
    token_id="104173557214744537570424345347209544585775842950109756851652855913015295701992",
    price=0.36,
    size=5.0,
    side=BUY
)



signed_order = client.create_order(order_args)
print("signed order:", signed_order)

response = client.post_order(signed_order, OrderType.GTC, proxies=proxies)
print("Response:", response)


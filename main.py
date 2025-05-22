import requests
from dotenv import load_dotenv
import os
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType, BalanceAllowanceParams, AssetType, PartialCreateOrderOptions, MarketOrderArgs
from py_clob_client.order_builder.constants import BUY, SELL
from py_clob_client.headers.headers import create_level_2_headers
import time
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

yes = "104173557214744537570424345347209544585775842950109756851652855913015295701992"
no = "44528029102356085806317866371026691780796471200782980570839327755136990994869"
market_order_args = MarketOrderArgs(
    token_id=yes,
    price=0.88,  # py_clob_client expects float for price
    amount=10*0.88,
    side=BUY,     
)

limit_order_args = OrderArgs(
    token_id=yes,
    price=0.35,  # py_clob_client expects float for price
    size=10,    # py_clob_client expects float for size
    side=BUY,     
)
partial_args = PartialCreateOrderOptions(

)


# signed_market_order = client.create_market_order(market_order_args)
start_create = time.time()
signed_limit_order = client.create_order(limit_order_args)
finish_create = time.time()
# print("Signed Market Order:", signed_market_order.dict())
# print("Signed Limit Order:", signed_limit_order.dict())

start_create_next = time.time()
signed_limit_order_next = client.create_order(limit_order_args)
finish_create_next = time.time()

start_create_3 = time.time()
signed_limit_order_3 = client.create_order(limit_order_args)
finish_create_3 = time.time()

# market_order_resp = client.post_order(signed_market_order, OrderType.FOK, proxies=proxies)
start_send = time.time()
limit_order_resp = client.post_order(signed_limit_order_next, OrderType.GTC, proxies=proxies)
finish_send = time.time()

start_send_next = time.time()
limit_order_next_resp = client.post_order(signed_limit_order, OrderType.GTC, proxies=proxies)
finish_send_next = time.time()

start_send_3 = time.time()
limit_order_3_resp = client.post_order(signed_limit_order_3, OrderType.GTC, proxies=proxies)
finish_send_3 = time.time()


start_address = time.time()
address = client.get_address()
finish_address = time.time()



start_cancel = time.time()
cancel_resp = client.cancel_all()
finish_cancel = time.time()
print("Cancel Response:", cancel_resp)
print("Time to create order:", finish_create - start_create)
print("Time to create next order:", finish_create_next - start_create_next)
print("Time to create 3rd order:", finish_create_3 - start_create_3)
print("Time to send order:", finish_send - start_send)
print("Time to send next order:", finish_send_next - start_send_next)
print("Time to send 3rd order:", finish_send_3 - start_send_3)
print("Time to get address:", finish_address - start_address)
print("Time to cancel order:", finish_cancel - start_cancel)
# print("Market Order Response:", market_order_resp)
# print("Limit Order Response:", limit_order_resp)
# response = client.post_order(signed_order, OrderType.GTC, proxies=proxies)
# print("Response:", response)


# market = client.get_market("0x3807c516773b31a512d6cd72d4e42ff192878a29e79760b48c4757fd57d3623c")
# print("Market:", market)

# d = {'enable_order_book': True, 'active': True, 'closed': False, 'archived': False, 'accepting_orders': True, 'accepting_order_timestamp': '2025-05-19T01:00:43Z', 'minimum_order_size': 5, 'minimum_tick_size': 0.01, 'condition_id': '0xd065c6382e5514a9085ccbe033c41a7546d64e25e4e5f15ce1f09e7fe29c38bd', 'question_id': '0x354a4f0dbecedc7302eb5704953504b564a25461f68a4d940348baf3203d3208', 'question': 'Timberwolves vs. Thunder', 'description': 'In the upcoming NBA game, scheduled for May 20 at 8:30PM ET:\nIf the Minnesota Timberwolves win, the market will resolve to “Timberwolves”.\nIf the Oklahoma City Thunder win, the market will resolve to “Thunder”.\nIf the game is postponed, this market will remain open until the game has been completed.\nIf the game is canceled entirely, with no make-up game, this market will resolve 50-50.', 'market_slug': 'nba-min-okc-2025-05-20', 'end_date_iso': '2025-05-28T00:00:00Z', 'game_start_time': '2025-05-21T00:30:00Z', 'seconds_delay': 3, 'fpmm': '', 'maker_base_fee': 0, 'taker_base_fee': 0, 'notifications_enabled': False, 'neg_risk': False, 'neg_risk_market_id': '', 'neg_risk_request_id': '', 'icon': 'https://polymarket-upload.s3.us-east-2.amazonaws.com/super+cool+basketball+in+red+and+blue+wow.png', 'image': 'https://polymarket-upload.s3.us-east-2.amazonaws.com/super+cool+basketball+in+red+and+blue+wow.png', 'rewards': {'rates': None, 'min_size': 0, 'max_spread': 0}, 'is_50_50_outcome': False, 'tokens': [{'token_id': '45250181518294950968312447895111202368371060559300586901244169566455386600698', 'outcome': 'Timberwolves', 'price': 0.125, 'winner': False}, {'token_id': '18709145334926801647146694965678554303153338741699706310633545373656653992367', 'outcome': 'Thunder', 'price': 0.875, 'winner': False}], 'tags': ['Sports', 'NBA', 'Games']}

'''
-Matched orders (market orders, limit orders that match a resting order) are delayed by 3 seconds
-Non-matched orders (limit orders that do not match a resting order) are live immediately
-cancelling an unmatched order is instant
'''
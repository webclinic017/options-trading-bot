import math
import time
import pandas as pd
import asyncio
import nest_asyncio
import redis
import sqlite3
import constants
import json
from ib_insync import util, IB, Stock, Option, MarketOrder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

nest_asyncio.apply()

pd.options.display.width = None
pd.options.display.max_columns = None
pd.set_option('display.max_rows', 3000)
pd.set_option('display.max_columns', 3000)

# Redis connection
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('tradingview')

conn = sqlite3.connect('trade.db')
cursor = conn.cursor()
cursor.execute(constants.CREATE_TABLE)

conn.commit()

print("Starting up bot...")
print("Started Redis Server...")
print("Getting initial option chains...")
print("First Stock:", constants.AMAZON)
print("Second Stock:", constants.NVIDIA)

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)
ib.reqMarketDataType(1)
amazon_stock_contract = Stock(constants.AMAZON, constants.SMART, constants.USD, primaryExchange='NASDAQ')
nvidia_stock_contract = Stock(constants.NVIDIA, constants.SMART, constants.USD, primaryExchange='NASDAQ')
ib.qualifyContracts(amazon_stock_contract)
ib.qualifyContracts(nvidia_stock_contract)

# request a list of option chains
amazon_option_chains = ib.reqSecDefOptParams(amazon_stock_contract.symbol, '', amazon_stock_contract.secType,
                                             amazon_stock_contract.conId)
nvidia_option_chains = ib.reqSecDefOptParams(nvidia_stock_contract.symbol, '', nvidia_stock_contract.secType,
                                             nvidia_stock_contract.conId)

current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
print("Running Live...")
print(current_time)


async def check_messages():
    """
        On an interval set to 1 second, and constantly checks for new
        messages from redis.  Once the message is received, it will
        then parse it and then check what to do such as Buy or Sell
        an Options Contract.
    """
    # print("checking messages...")

    message = p.get_message()

    if message is not None and message['type'] == 'message':
        message_data = json.loads(message['data'])

        symbol = message_data['symbol']
        condition = message_data['order']['condition']
        price = message_data['order']['price']
        stoploss = message_data['order']['stoploss']
        take_profit = message_data['order']['takeProfit']
        right = message_data['order']['right']
        contracts = message_data['order']['contracts']
        action = message_data['order']['action']
        result = message_data['order']['result']
        afterhours = message_data['order']['afterhours']

        print("This is a", right, "option to", action, "for", symbol, "@", price, "and", contracts, "contracts")
        print("Condition:", condition)
        print("Stoploss:", stoploss)
        print("Take Profit:", take_profit)
        print("Afterhours?:", afterhours)
        print("Won/Loss/Pending?:", result)

        if action == constants.BUY:
            if symbol == constants.AMAZON:
                for options_chain in amazon_option_chains:
                    call_strikes = [strike for strike in options_chain.strikes
                                    if strike > price]
                    put_strikes = [strike for strike in options_chain.strikes
                                   if price - 7 < strike < price]
                    print("All the call strikes for the current chain:", call_strikes[:7])
                    print("All the put strikes for the current chain:", put_strikes)
                    if right == constants.CALL:
                        call_strike = call_strikes[5]
                        call_options_contract = create_options_contract(symbol, options_chain.expirations[0],
                                                                        call_strike, right)
                        options_order = MarketOrder(action, contracts)
                        placed_order = ib.placeOrder(call_options_contract, options_order)
                        print("Options order to place:", options_order)
                        print("Final Placed order:", placed_order)
                        save_data(message_data, call_strike)
                        return
                    else:
                        put_strike = put_strikes[5]
                        put_options_contract = create_options_contract(symbol, options_chain.expirations[0], put_strike,
                                                                       right)
                        options_order = MarketOrder(action, contracts)
                        placed_order = ib.placeOrder(put_options_contract, options_order)
                        print("Options order to place:", options_order)
                        print("Final Placed order:", placed_order)
                        save_data(message_data, put_strike)
                        return
            elif symbol == constants.NVIDIA:
                for options_chain in nvidia_option_chains:
                    call_strikes = [strike for strike in options_chain.strikes
                                    if strike > price]
                    put_strikes = [strike for strike in options_chain.strikes
                                   if price - 7 < strike < price]
                    print("All the call strikes for the current chain:", call_strikes[:7])
                    print("All the put strikes for the current chain:", put_strikes)
                    if right == constants.CALL:
                        call_strike = call_strikes[5]
                        call_options_contract = create_options_contract(symbol, options_chain.expirations[0],
                                                                        call_strike, right)
                        options_order = MarketOrder(action, contracts)
                        placed_order = ib.placeOrder(call_options_contract, options_order)
                        print("Options order to place:", options_order)
                        print("Final Placed order:", placed_order)
                        save_data(message_data, call_strike)
                        return
                    else:
                        put_strike = put_strikes[5]
                        put_options_contract = create_options_contract(symbol, options_chain.expirations[0], put_strike,
                                                                       right)
                        options_order = MarketOrder(action, contracts)
                        placed_order = ib.placeOrder(put_options_contract, options_order)
                        print("Options order to place:", options_order)
                        print("Final Placed order:", placed_order)
                        save_data(message_data, put_strike)
                        return
        elif action == constants.SELL:
            options_order = MarketOrder(action, contracts)
            open_trades = ib.openTrades()
            print(open_trades)

            matching_trade_strike_price = get_matching_trade(symbol, condition, right, result)

            if open_trades:
                for open_trade in open_trades:
                    if open_trade.contract.symbol == symbol and open_trade.contract.right == right and open_trade.contract.strike == matching_trade_strike_price :
                        print("Selling contract for: ", symbol)
                        print(open_trade.contract)
                        ib.placeOrder(open_trade.contract, options_order)
                        update_data(result, condition, action)
                        return
            else:
                print("No open contracts to sell.")
        else:
            print("Only action known is BUY and SELL, we don't do anything with this:", action)


def create_options_contract(symbol, expiration, strike, right):
    return Option(
        symbol,
        expiration,
        strike,
        right,
        constants.SMART,
        tradingClass=symbol
    )

def save_data(message_data, strike_price):
    print("Saving to database...")

    cursor = conn.cursor()
    sqlite_insert_with_param = constants.INSERT_DATA
    sqlite_data = (
        message_data['symbol'],
        message_data['order']['condition'],
        message_data['order']['action'],
        message_data['order']['right'],
        message_data['order']['contracts'],
        message_data['order']['price'],
        strike_price,
        message_data['order']['stoploss'],
        message_data['order']['takeProfit'],
        message_data['order']['result'],
        message_data['order']['afterhours'],
        time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
    )

    cursor.execute(sqlite_insert_with_param, sqlite_data)

    conn.commit()

    print("Saved to database!")

def get_matching_trade(symbol, condition, right, result):
    cursor = conn.cursor()
    if result == "W":
        cursor.execute(constants.MATCHING_TRADE_PROFIT, (symbol, condition, right))
    else:
        cursor.execute(constants.MATCHING_TRADE_STOPLOSS, (symbol, condition, right))

def update_data(result, condition, action):
    cursor = conn.cursor()
    cursor.execute(constants.UPDATE_DATA, (result, condition, action))

# Update options chains
async def update_options_chains():
    try:
        sched.print_jobs()
        print("Updating options chains")
        print(current_time)
        amazon_option_chains = ib.reqSecDefOptParams(amazon_stock_contract.symbol, '', amazon_stock_contract.secType,
                                                     amazon_stock_contract.conId)
        nvidia_option_chains = ib.reqSecDefOptParams(nvidia_stock_contract.symbol, '', nvidia_stock_contract.secType,
                                                     nvidia_stock_contract.conId)
        print("Updated chains: ", amazon_option_chains)
        print("Updated chains: ", nvidia_option_chains)
    except Exception as e:
        print(str(e))


async def run_periodically(interval, periodic_function):
    """
        This runs a function on a specific interval.
    """
    while True:
        await asyncio.gather(asyncio.sleep(interval), periodic_function())


if __name__ == "__main__":
    sched = AsyncIOScheduler(daemon=True)
    sched.add_job(update_options_chains, 'cron', day_of_week='mon-fri', hour='9-16', minute='*/15')
    sched.start()

    asyncio.run(run_periodically(1, check_messages))
    ib.run()

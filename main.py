import math
import time
import pandas as pd
import asyncio
import nest_asyncio
import redis
import sqlite3
import constants
import json
from ib_insync import util, IB, Stock, Option
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
print("Getting initial option chains...")
print("First Stock:", constants.AMAZON)

ib = IB()
ib.connect('127.0.0.1', 7496, clientId=1)
ib.reqMarketDataType(1)
contract = Stock(constants.AMAZON, 'SMART', 'USD', primaryExchange='NASDAQ')
ib.qualifyContracts(contract)

# request a list of option chains
amazon_chains = ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)

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
        print("Message here on backend...")

        message_data = json.loads(message['data'])

        symbol = message_data['symbol']
        price = message_data['order']['price']
        stoploss = message_data['order']['stoploss']
        take_profit = message_data['order']['takeProfit']
        right = message_data['order']['right']
        contracts = message_data['order']['contracts']
        action = message_data['order']['action']
        result = message_data['order']['result']
        afterhours = message_data['order']['afterhours']

        print("This is a", right, "option to", action, "for", symbol, "@", price, "and", contracts, "contracts")
        print("Stoploss:", stoploss)
        print("Take Profit:", take_profit)
        print("Afterhours?:", afterhours)
        print("Won/Loss/Pending?:", result)

        # save_data(message_data, 150.0)

        if action == constants.BUY:
            if symbol == constants.AMAZON:
                for optionschain in amazon_chains:
                    call_strikes = [strike for strike in optionschain.strikes
                               if strike > price]
                    put_strikes = [strike for strike in optionschain.strikes
                               if price - 7 < strike < price]
                    print("All the call strikes for the current chain:", call_strikes[:7])
                    print("All the put strikes for the current chain:", put_strikes)
                    if right == constants.CALL:
                        options_contract = Option(
                            symbol,
                            optionschain.expirations[0],
                            call_strikes[5],
                            right,
                            constants.SMART,
                            tradingClass=symbol
                        )
                        print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
                        ticker_data = ib.reqTickers(options_contract)
                        print(ticker_data)
                        ask = ticker_data[0].ask
                        delta = ticker_data[0].modelGreeks.delta
                        gamma = ticker_data[0].modelGreeks.gamma
                        print("All Ticker Data:", ticker_data)
                        print("Ask price:", ask)
                        print("Delta:", delta)
                        print("Gamma:", gamma)
                        print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
                        # Ask + ((delta + (Gama * rounddown) * (profit - entry))

                        profit = ask + ((delta + (math.floor(gamma))) * take_profit)
                        sloss = ask - ((delta + (math.floor(gamma))) * stoploss)

                        print("Options Profit:", profit)
                        print("Options Stoploss:", sloss)

                        # options_order = MarketOrder(action, contracts)
                        # ib.placeOrder(options_contract, options_order)
                        return
                    else:
                        options_contract = Option(
                            symbol,
                            optionschain.expirations[0],
                            put_strikes[5],
                            right,
                            constants.SMART,
                            tradingClass=symbol
                        )

                        print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
                        ticker_data = ib.reqTickers(options_contract)
                        ask = ticker_data[0].ask
                        delta = ticker_data[0].modelGreeks.delta
                        gamma = ticker_data[0].modelGreeks.gamma
                        print("All Ticker Data:", ticker_data)
                        print("Ask price:", ask)
                        print("Delta:", delta)
                        print("Gamma:", gamma)
                        print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
                        # Ask + ((delta + (Gama * rounddown) * (profit - entry))

                        profit = ask + ((delta + (math.floor(gamma))) * take_profit)
                        sloss = ask - ((delta + (math.floor(gamma))) * stoploss)

                        print("Options Profit:", profit)
                        print("Options Stoploss:", sloss)
                        # options_order = MarketOrder(action, contracts)
                        # ib.placeOrder(options_contract, options_order)
                        return
        else:
            print("Only action known is BUY, we don't do anything with", action)

def save_data(message_data, strike_price):
    print("Saving to database...")

    cursor = conn.cursor()
    sqlite_insert_with_param = constants.INSERT_DATA
    sqlite_data = (
        message_data['symbol'],
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

# Update options chains
async def update_options_chains():
    try:
        sched.print_jobs()
        print("Updating options chains")
        print(current_time)
        amazon_chains = ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
        print("Updated chains: ", amazon_chains)
    except Exception as e:
        print(str(e))

# async def update_tickers():
#     try:
#         sched.print_jobs()
#         print("Updating tickers")
#         print(current_time)
#         ticker_data = ib.reqTickers(option_contract)
#         print("Current ticker data: ", ticker_data)
#     except Exception as e:
#         print(str(e))

async def run_periodically(interval, periodic_function):
    """
        This runs a function on a specific interval.
    """
    while True:
        await asyncio.gather(asyncio.sleep(interval), periodic_function())

if __name__ == "__main__":
    sched = AsyncIOScheduler(daemon=True)
    sched.add_job(update_options_chains, 'cron', minute='15')
    sched.start()

    asyncio.run(run_periodically(1, check_messages))
    ib.run()

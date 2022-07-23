import time
import pandas as pd
import nest_asyncio
from flask import Flask, request, views, json
from ib_insync import *
from apscheduler.schedulers.asyncio import AsyncIOScheduler

nest_asyncio.apply()

app = Flask(__name__)

pd.options.display.width = None
pd.options.display.max_columns = None
pd.set_option('display.max_rows', 3000)
pd.set_option('display.max_columns', 3000)

ib = IB()
ib.connect('127.0.0.1', 7496, clientId=1)
ib.reqMarketDataType(1)
contract = Stock('AAPL', 'SMART', 'USD', primaryExchange='NASDAQ')
ib.qualifyContracts(contract)

[ticker] = ib.reqTickers(contract)
print(ticker)

# request a list of option chains
chains = ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
# print(chains[0])
print(util.df(chains))

chain = next(c for c in chains if c.exchange == 'NASDAQBX')

# print a full matrix of expirations and strikes, from this we can build all the option contracts that meet our conditions
print(chain)

# if entry price was 146.50
entry_price = 146.50
strikes = [strike for strike in chain.strikes
           if strike > entry_price]

print(strikes)

expirations = sorted(exp for exp in chain.expirations)[:3]
rights = ['P', 'C']

print("First 3 Expirations: ", expirations)
print("Rights: ", rights)

# contracts = [Option('AAPL', chain.expiration[0], strike, right, 'SMART', tradingClass='AAPL')
#              for right in rights
#              for expiration in expirations
#              for strike in strikes]
#
# contracts = ib.qualifyContracts(*contracts)

option_contract = Option('AAPL', expirations[0], strikes[5], 'C', 'SMART', tradingClass='AAPL')
# option_contract = ib.qualifyContracts()
print("Example Option Contract: ", option_contract)

tickers = ib.reqTickers(option_contract)
print("Data: ", tickers[0])

current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
print("Running Live...")
print(current_time)

count = 0

# Update options chains
async def update_options_chains():
    try:
        sched.print_jobs()
        print("Updating options chains")
        chainz = ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
        print("Inside update option chains: ", chainz)
    except Exception as e:
        print(str(e))

async def update_tickers():
    try:
        sched.print_jobs()
        print("Updating tickers")
        ticker_data = ib.reqTickers(option_contract)
        print(ticker_data)
        print("Inside ticker data")
    except Exception as e:
        print(str(e))

@views.route('/tradingview', methods=['POST'])
def alert():
    """
        This route retrieves alerts from TradingView.

        Any alert is then published to redis server, which the message then
        gets picked up by broker.py to buy or sell to Interactive Brokers.

        We also store the trade into the database.  Will need to update the
        same row if we won or lost instead of inserting a new row.
    """

    print("Testing trading view endpoint.")

    data = request.data

    if data:
        tradeview_message = json.loads(request.data)

        symbol = tradeview_message['symbol']
        price = tradeview_message['order']['price']
        stoploss = tradeview_message['order']['stoploss']
        take_profit = tradeview_message['order']['takeProfit']
        right = tradeview_message['order']['right']
        contracts = tradeview_message['order']['contracts']
        action = tradeview_message['order']['action']
        result = tradeview_message['order']['result']
        afterhours = tradeview_message['order']['afterhours']

        print("This is a", right, "option to", action, "for", symbol, "@", price, "and", contracts, "contracts")
        print("Stoploss:", stoploss)
        print("Take Profit:", take_profit)
        print("Afterhours?:", afterhours)
        print("Won/Loss/Pending?:", result)

        return data

    return "success"


if __name__ == "__main__":
    sched = AsyncIOScheduler(daemon=True)
    sched.add_job(update_options_chains, 'cron', minute='*')
    sched.start()

    ib.run()

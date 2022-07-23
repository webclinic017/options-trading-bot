import time
import pandas as pd
import asyncio
import nest_asyncio
import redis
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

print("Starting up bot...")
print("Getting initial option chains...")

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

option_contract = Option('AAPL', expirations[0], strikes[5], 'C', 'SMART', tradingClass='AAPL')
print("Example Option Contract: ", option_contract)

tickers = ib.reqTickers(option_contract)
print("Data: ", tickers[0])

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

async def run_periodically(interval, periodic_function):
    """
        This runs a function on a specific interval.
    """
    while True:
        await asyncio.gather(asyncio.sleep(interval), periodic_function())

if __name__ == "__main__":
    sched = AsyncIOScheduler(daemon=True)
    sched.add_job(update_options_chains, 'cron', minute='*')
    sched.start()

    # Redis connection
    r = redis.Redis(host='localhost', port=6379, db=0)

    asyncio.run(run_periodically(1, check_messages))
    ib.run()

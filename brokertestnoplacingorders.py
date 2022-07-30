import time
import pandas as pd
import asyncio
import nest_asyncio
import redis
import sqlite3
import constants
import json
from ib_insync import IB, Stock, Option, MarketOrder
from apscheduler.schedulers.asyncio import AsyncIOScheduler


class OptionsBot:
    def __init__(self):
        print("Starting up bot...")

        self.breakout_amazon_call_options_contract = None
        self.breakout_amazon_put_options_contract = None
        self.breakout_nvidia_call_options_contract = None
        self.breakout_nvidia_put_options_contract = None

        self.sma_nvidia_call_options_contract = None
        self.sma_nvidia_put_options_contract = None
        self.sma_amazon_call_options_contract = None
        self.sma_amazon_put_options_contract = None

        self.breakout_apple_call_options_contract = None
        self.breakout_apple_put_options_contract = None
        self.sma_apple_call_options_contract = None
        self.sma_apple_put_options_contract = None

        nest_asyncio.apply()

        pd.options.display.width = None
        pd.options.display.max_columns = None
        pd.set_option('display.max_rows', 3000)
        pd.set_option('display.max_columns', 3000)

        # Redis connection
        self.r = redis.Redis(host='localhost', port=6379, db=0)
        print("Starting Redis Server...")

        try:
            self.r.ping()
            print('Successfully Connected to Redis "{}"'.format(self.r.client()))
        except redis.exceptions.ConnectionError as redis_conn_error:
            print(str(redis_conn_error))

        self.p = self.r.pubsub()
        self.p.subscribe('tradingview')

        # sqlite3 connection
        try:
            print("Connecting to SQLite3 Database...")
            self.conn = sqlite3.connect('trade.db')
            self.cursor = self.conn.cursor()
            self.cursor.execute(constants.CREATE_TABLE)
            self.conn.commit()
            print("Successfully Connected to SQLite3 Database!")
        except sqlite3.Error as error:
            print("Error occurred:", error)

        print("Getting initial option chains...")
        print("First Stock:", constants.AMAZON)
        print("Second Stock:", constants.NVIDIA)
        print("Third Stock:", constants.APPLE)

        try:
            self.ib = IB()
            self.ib.connect('127.0.0.1', 7497, clientId=1)
        except Exception as e:
            print(str(e))

        self.ib.reqMarketDataType(1)
        self.amazon_stock_contract = Stock(constants.AMAZON, 'NASDAQ', constants.USD, primaryExchange='NASDAQ')
        self.nvidia_stock_contract = Stock(constants.NVIDIA, constants.SMART, constants.USD, primaryExchange='NASDAQ')
        self.apple_stock_contract = Stock(constants.APPLE, constants.SMART, constants.USD, primaryExchange='NASDAQ')
        self.ib.qualifyContracts(self.amazon_stock_contract)
        self.ib.qualifyContracts(self.nvidia_stock_contract)
        self.ib.qualifyContracts(self.apple_stock_contract)

        # request a list of option chains
        self.amazon_option_chains = self.ib.reqSecDefOptParams(self.amazon_stock_contract.symbol, '',
                                                               self.amazon_stock_contract.secType,
                                                               self.amazon_stock_contract.conId)
        self.nvidia_option_chains = self.ib.reqSecDefOptParams(self.nvidia_stock_contract.symbol, '',
                                                               self.nvidia_stock_contract.secType,
                                                               self.nvidia_stock_contract.conId)
        self.apple_option_chains = self.ib.reqSecDefOptParams(self.apple_stock_contract.symbol, '',
                                                               self.apple_stock_contract.secType,
                                                               self.apple_stock_contract.conId)

        current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
        print("Running Live...")
        print(current_time)
        self.sched = AsyncIOScheduler(daemon=True)
        self.sched.add_job(self.update_options_chains, 'cron', day_of_week='mon-fri', hour='9-16', minute='*/15')
        self.sched.start()

        asyncio.run(self.run_periodically(1, self.check_messages))
        self.ib.run()

    async def check_messages(self):
        """
            On an interval set to 1 second, and constantly checks for new
            messages from redis.  Once the message is received, it will
            then parse it and then check what to do such as Buy or Sell
            an Options Contract.
        """
        message = self.p.get_message()

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
                    for options_chain in self.amazon_option_chains:
                        if options_chain.exchange == constants.EXCHANGE:
                            call_strikes = [strike for strike in options_chain.strikes
                                            if strike > price]
                            put_strikes = [strike for strike in options_chain.strikes
                                           if strike < price]
                            print("All the call strikes for the current chain:", call_strikes)
                            print("All the put strikes for the current chain:", put_strikes)
                            if right == constants.CALL:
                                call_strike = call_strikes[constants.STRIKE_PRICE_DIFFERENCE]

                                if condition == "breakout":
                                    self.breakout_amazon_call_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        call_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    # self.insert_option_contract(condition, self.breakout_amazon_call_options_contract)
                                    print("Contract placed:", self.breakout_amazon_call_options_contract)
                                    print("Options order to place:", options_order)
                                elif condition == "sma":
                                    self.sma_amazon_call_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        call_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    # self.insert_option_contract(condition, self.sma_amazon_call_options_contract)
                                    print("Contract placed:", self.sma_amazon_call_options_contract)
                                    print("Options order to place:", options_order)
                                self.save_data(message_data, call_strike)
                                return
                            else:
                                put_strike = put_strikes[-constants.STRIKE_PRICE_DIFFERENCE]

                                if condition == "breakout":
                                    self.breakout_amazon_put_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        put_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    print("Contract placed:", self.breakout_amazon_put_options_contract)
                                    print("Options order to place:", options_order)
                                elif condition == "sma":
                                    self.sma_amazon_put_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        put_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    print("Contract placed:", self.sma_amazon_put_options_contract)
                                    print("Options order to place:", options_order)
                                self.save_data(message_data, put_strike)
                                return
                elif symbol == constants.NVIDIA:
                    for options_chain in self.nvidia_option_chains:
                        if options_chain.exchange == constants.EXCHANGE:
                            call_strikes = [strike for strike in options_chain.strikes
                                            if strike > price]
                            put_strikes = [strike for strike in options_chain.strikes
                                           if strike < price]
                            print("All the call strikes for the current chain:", call_strikes)
                            print("All the put strikes for the current chain:", put_strikes)
                            if right == constants.CALL:
                                call_strike = call_strikes[constants.STRIKE_PRICE_DIFFERENCE]
                                if condition == "breakout":
                                    self.breakout_nvidia_call_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        call_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    print("Contract placed:", self.breakout_nvidia_call_options_contract)
                                    print("Options order to place:", options_order)
                                elif condition == "sma":
                                    self.sma_nvidia_call_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        call_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    print("Contract placed:", self.sma_nvidia_call_options_contract)
                                    print("Options order to place:", options_order)
                                self.save_data(message_data, call_strike)
                                return
                            else:
                                put_strike = put_strikes[-constants.STRIKE_PRICE_DIFFERENCE]

                                if condition == "breakout":
                                    self.breakout_nvidia_put_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        put_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    print("Contract placed:", self.breakout_nvidia_put_options_contract)
                                    print("Options order to place:", options_order)
                                elif condition == "sma":
                                    self.sma_nvidia_put_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        put_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    print("Contract placed:", self.sma_nvidia_put_options_contract)
                                    print("Options order to place:", options_order)
                                self.save_data(message_data, put_strike)
                                return
                elif symbol == constants.APPLE:
                    for options_chain in self.apple_option_chains:
                        if options_chain.exchange == constants.EXCHANGE:
                            call_strikes = [strike for strike in options_chain.strikes
                                            if strike > price]
                            put_strikes = [strike for strike in options_chain.strikes
                                           if strike < price]
                            print("All the call strikes for the current chain:", call_strikes)
                            print("All the put strikes for the current chain:", put_strikes)
                            if right == constants.CALL:
                                call_strike = call_strikes[constants.STRIKE_PRICE_DIFFERENCE]

                                if condition == "breakout":
                                    self.breakout_apple_call_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        call_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    # self.insert_option_contract(condition, self.breakout_amazon_call_options_contract)
                                    print("Contract placed:", self.breakout_apple_call_options_contract)
                                    print("Options order to place:", options_order)
                                elif condition == "sma":
                                    self.sma_apple_call_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        call_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    # self.insert_option_contract(condition, self.sma_amazon_call_options_contract)
                                    print("Contract placed:", self.sma_apple_call_options_contract)
                                    print("Options order to place:", options_order)
                                self.save_data(message_data, call_strike)
                                return
                            else:
                                put_strike = put_strikes[-constants.STRIKE_PRICE_DIFFERENCE]

                                if condition == "breakout":
                                    self.breakout_apple_put_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        put_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    print("Contract placed:", self.breakout_apple_put_options_contract)
                                    print("Options order to place:", options_order)
                                elif condition == "sma":
                                    self.sma_apple_put_options_contract = self.create_options_contract(
                                        symbol,
                                        options_chain.expirations[0],
                                        put_strike,
                                        right)
                                    options_order = MarketOrder(action, contracts)
                                    print("Contract placed:", self.sma_apple_put_options_contract)
                                    print("Options order to place:", options_order)
                                self.save_data(message_data, put_strike)
                                return
            elif action == constants.SELL:
                options_order = MarketOrder(action, contracts)

                if symbol == constants.AMAZON:
                    if condition == "breakout":
                        if right == "CALL":
                            print("Contract to sell:", self.breakout_amazon_call_options_contract)
                            print("Sold!")
                            self.breakout_amazon_call_options_contract = None
                        if right == "PUT":
                            print("Contract to sell:", self.breakout_amazon_put_options_contract)
                            print("Sold!")
                            self.breakout_amazon_put_options_contract = None
                    if condition == "sma":
                        if right == "CALL":
                            print("Contract to sell:", self.sma_amazon_call_options_contract)
                            print("Sold!")
                            self.sma_amazon_call_options_contract = None
                        if right == "PUT":
                            print("Contract to sell:", self.sma_amazon_put_options_contract)
                            print("Sold!")
                            self.sma_amazon_put_options_contract = None
                elif symbol == constants.NVIDIA:
                    if condition == "breakout":
                        if right == "CALL":
                            print("Contract to sell:", self.breakout_nvidia_call_options_contract)
                            print("Sold!")
                            self.breakout_nvidia_call_options_contract = None
                        if right == "PUT":
                            print("Contract to sell:", self.breakout_nvidia_put_options_contract)
                            print("Sold!")
                            self.breakout_nvidia_put_options_contract = None
                    if condition == "sma":
                        if right == "CALL":
                            print("Contract to sell:", self.sma_nvidia_call_options_contract)
                            print("Sold!")
                            self.sma_nvidia_call_options_contract = None
                        if right == "PUT":
                            print("Contract to sell:", self.sma_nvidia_put_options_contract)
                            print("Sold!")
                            self.sma_nvidia_put_options_contract = None
                elif symbol == constants.APPLE:
                    if condition == "breakout":
                        if right == "CALL":
                            print("Contract to sell:", self.breakout_apple_call_options_contract)
                            print("Sold!")
                            self.breakout_apple_call_options_contract = None
                        if right == "PUT":
                            print("Contract to sell:", self.breakout_apple_put_options_contract)
                            print("Sold!")
                            self.breakout_apple_put_options_contract = None
                    if condition == "sma":
                        if right == "CALL":
                            print("Contract to sell:", self.sma_apple_call_options_contract)
                            print("Sold!")
                            self.sma_apple_call_options_contract = None
                        if right == "PUT":
                            print("Contract to sell:", self.sma_apple_put_options_contract)
                            print("Sold!")
                            self.sma_apple_put_options_contract = None
                # need to only do this if correct data was sent and ACTUALLY sold a trade.  If not, don't update.
                self.update_data(result, condition, symbol)
            else:
                print("Only action known is BUY and SELL, we don't do anything with this:", action)

    def create_options_contract(self, symbol, expiration, strike, right):
        return Option(
            symbol,
            expiration,
            strike,
            right,
            constants.SMART,
            tradingClass=symbol
        )

    def save_data(self, message_data, strike_price):
        print("Saving to database...")

        cursor = self.conn.cursor()
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

        self.conn.commit()

        print("Saved to database!")

    def get_matching_trade(self, symbol, condition, right, result):
        cursor = self.conn.cursor()
        if result == "W":
            cursor.execute(constants.MATCHING_TRADE_PROFIT, (symbol, condition, right))
        else:
            cursor.execute(constants.MATCHING_TRADE_STOPLOSS, (symbol, condition, right))

    def update_data(self, result, condition, symbol):
        print("Updating database...")

        cursor = self.conn.cursor()
        cursor.execute(constants.UPDATE_DATA, (result, condition, symbol))
        self.conn.commit()

        rows_affected = self.cursor.rowcount

        print("Updated", rows_affected, "rows in the database Successfully!")

    def insert_option_contract(self, condition, contract):
        cursor = self.conn.cursor()
        print("Inserting option contract into database...")

        sqlite_insert_with_param = constants.INSERT_OPTION
        sqlite_data = (
            condition,
            contract.symbol,
            contract.lastTradeDateOrContractMonth,
            contract.strike,
            contract.right,
            contract.exchange,
            contract.tradingClass,
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
        )

        cursor.execute(sqlite_insert_with_param, sqlite_data)

        self.conn.commit()

        print("Inserted into Database:", sqlite_data)

    def end_of_day_results(self):
        print("Retrieving end of day results...")

        cursor = self.conn.cursor()
        rows = cursor.execute(constants.END_OF_DAY_RESULTS).fetchall()

        # for row in cursor:
        #     print(row)

        df = pd.DataFrame.from_records(rows, columns=[x[0] for x in cursor.description])
        print(df)

    # Update options chains
    async def update_options_chains(self):
        try:
            self.sched.print_jobs()
            print("Updating options chains")
            print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
            self.amazon_option_chains = self.ib.reqSecDefOptParams(
                                                            self.amazon_stock_contract.symbol, '',
                                                            self.amazon_stock_contract.secType,
                                                            self.amazon_stock_contract.conId)
            self.nvidia_option_chains = self.ib.reqSecDefOptParams(
                                                            self.nvidia_stock_contract.symbol, '',
                                                            self.nvidia_stock_contract.secType,
                                                            self.nvidia_stock_contract.conId)
            self.apple_option_chains = self.ib.reqSecDefOptParams(
                                                            self.apple_stock_contract.symbol, '',
                                                            self.apple_stock_contract.secType,
                                                            self.apple_stock_contract.conId)

            print("Updated chains: ", self.amazon_option_chains)
            print("Updated chains: ", self.nvidia_option_chains)
            print("Updated chains: ", self.apple_option_chains)
        except Exception as e:
            print(str(e))

    async def run_periodically(self, interval, periodic_function):
        """
            This runs a function on a specific interval.
        """
        while True:
            await asyncio.gather(asyncio.sleep(interval), periodic_function())


# start the options bot
OptionsBot()

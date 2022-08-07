import math
import time
import pandas as pd
import asyncio
import nest_asyncio
import redis
import sqlite3
import constants
import json
from ib_insync import IB, Stock, Option, LimitOrder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# TODO: create single method for each condition to reduce code
# TODO: get closest contract expiration date, unless it's a zero day, get the next one.  Either [0] or [1]
# TODO: check connection every so often?  Besides when we start a trade. Once it restarts every night, the connection auto closes, and needs reconnected
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
            self.conn = sqlite3.connect('trade.db', check_same_thread=False)
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
        self.amazon_stock_contract = Stock(constants.AMAZON, constants.SMART, constants.USD)
        self.nvidia_stock_contract = Stock(constants.NVIDIA, constants.SMART, constants.USD)
        self.apple_stock_contract = Stock(constants.APPLE, constants.SMART, constants.USD)
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
        self.sched.add_job(self.update_options_chains, 'cron', day_of_week='mon-fri', hour='8')
        self.sched.add_job(self.end_of_day_results, 'cron', day_of_week='mon-fri', hour='16')
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
            # check if need to reconnect
            if not self.ib.isConnected() or not self.ib.client.isConnected():
                print("Reconnecting...")
                self.ib.disconnect()
                self.ib = IB()
                self.ib.connect('127.0.0.1', 7497, clientId=1)
                print("Reconnected! @", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))

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
                    # start initial value
                    number_of_contracts = 0

                    # the first options chain in list of 16
                    options_chain = next(c for c in self.amazon_option_chains if c.exchange == 'SMART' and c.tradingClass == constants.AMAZON)

                    # get all the call strikes and put strikes
                    call_strikes = [strike for strike in options_chain.strikes
                                    if strike > price]
                    put_strikes = [strike for strike in options_chain.strikes
                                   if strike < price]
                    expirations = sorted(exp for exp in options_chain.expirations)[:1]

                    print("selected chain:", options_chain)
                    print("All the call strikes for the current chain:", call_strikes)
                    print("All the put strikes for the current chain:", put_strikes)

                    if right == constants.CALL:
                        rights = ['C']

                        contracts = [Option(symbol, expiration, strike, right, 'SMART', tradingClass=symbol)
                                     for right in rights
                                     for expiration in expirations
                                     for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]

                        contracts = self.ib.qualifyContracts(*contracts)
                        print("Number of valid contracts:", len(contracts))
                        print(contracts)

                        if condition == "breakout":
                            self.breakout_amazon_call_options_contract = contracts[0]

                            # ask, delta, number_of_contracts = await self.ticker_info(number_of_contracts)
                            ticker_data = self.ib.reqTickers(self.breakout_amazon_call_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", delta)
                            print("Contract placed:", self.breakout_amazon_call_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.breakout_amazon_call_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)
                        elif condition == "sma":
                            self.sma_amazon_call_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.sma_amazon_call_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", ask_greeks.delta)
                            print("Contract placed:", self.sma_amazon_call_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.sma_amazon_call_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)

                        self.save_data(message_data, number_of_contracts, contracts[0].strike)
                        return
                    else:
                        rights = ['P']

                        contracts = [Option(symbol, expiration, strike, right, 'SMART', tradingClass=symbol)
                                     for right in rights
                                     for expiration in expirations
                                     for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        contracts = self.ib.qualifyContracts(*contracts)
                        print("Number of valid contracts:", len(contracts))
                        print(contracts)

                        if condition == "breakout":
                            self.breakout_amazon_put_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.breakout_amazon_put_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", ask_greeks.delta)
                            print("Contract placed:", self.breakout_amazon_put_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.breakout_amazon_put_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)
                        elif condition == "sma":
                            self.sma_amazon_put_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.sma_amazon_put_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", ask_greeks.delta)
                            print("Contract placed:", self.sma_amazon_put_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.sma_amazon_put_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)

                        self.save_data(message_data, number_of_contracts, contracts[0].strike)
                        return
                elif symbol == constants.NVIDIA:
                    # initial value
                    number_of_contracts = 0

                    # the first options chain in list of 16
                    options_chain = next(c for c in self.nvidia_option_chains if c.exchange == 'SMART' and c.tradingClass == constants.NVIDIA)

                    # get all the call strikes and put strikes
                    call_strikes = [strike for strike in options_chain.strikes
                                    if strike > price]
                    put_strikes = [strike for strike in options_chain.strikes
                                   if strike < price]
                    expirations = sorted(exp for exp in options_chain.expirations)[:1]

                    print("selected chain:", options_chain)
                    print("All the call strikes for the current chain:", call_strikes)
                    print("All the put strikes for the current chain:", put_strikes)

                    if right == constants.CALL:
                        rights = ['C']

                        contracts = [Option(symbol, expiration, strike, right, 'SMART', tradingClass=symbol)
                                     for right in rights
                                     for expiration in expirations
                                     for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]

                        contracts = self.ib.qualifyContracts(*contracts)
                        print("Number of valid contracts:", len(contracts))
                        print(contracts)

                        if condition == "breakout":
                            self.breakout_nvidia_call_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.breakout_nvidia_call_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", ask_greeks.delta)
                            print("Contract placed:", self.breakout_nvidia_call_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.sma_amazon_call_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)
                        elif condition == "sma":
                            self.sma_nvidia_call_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.sma_nvidia_call_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", ask_greeks.delta)
                            print("Contract placed:", self.sma_nvidia_call_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.sma_amazon_call_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)

                        self.save_data(message_data, number_of_contracts, contracts[0].strike)
                        # TODO: only need 1 return per symbol, change this
                        return
                    else:
                        rights = ['P']

                        contracts = [Option(symbol, expiration, strike, right, 'SMART', tradingClass=symbol)
                                     for right in rights
                                     for expiration in expirations
                                     for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        contracts = self.ib.qualifyContracts(*contracts)
                        print("Number of valid contracts:", len(contracts))
                        print(contracts)

                        if condition == "breakout":
                            self.breakout_nvidia_put_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.breakout_nvidia_put_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", ask_greeks.delta)
                            print("Contract placed:", self.breakout_nvidia_put_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.breakout_nvidia_put_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)
                        elif condition == "sma":
                            self.sma_nvidia_put_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.sma_nvidia_put_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", ask_greeks.delta)
                            print("Contract placed:", self.sma_nvidia_put_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.sma_nvidia_put_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)

                        self.save_data(message_data, number_of_contracts, contracts[0])
                        return
                elif symbol == constants.APPLE:
                    # initial value
                    number_of_contracts = 0

                    # the first options chain in list of 16
                    options_chain = next(c for c in self.apple_option_chains if
                                         c.exchange == 'SMART' and c.tradingClass == constants.APPLE)

                    # get all the call strikes and put strikes
                    call_strikes = [strike for strike in options_chain.strikes
                                    if strike > price]
                    put_strikes = [strike for strike in options_chain.strikes
                                   if strike < price]
                    expirations = sorted(exp for exp in options_chain.expirations)[:1]

                    print("selected chain:", options_chain)
                    print("All the call strikes for the current chain:", call_strikes)
                    print("All the put strikes for the current chain:", put_strikes)

                    if right == constants.CALL:
                        rights = ['C']

                        contracts = [Option(symbol, expiration, strike, right, 'SMART', tradingClass=symbol)
                                     for right in rights
                                     for expiration in expirations
                                     for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]

                        contracts = self.ib.qualifyContracts(*contracts)
                        print("Number of valid contracts:", len(contracts))
                        print(contracts)

                        if condition == "breakout":
                            self.breakout_apple_call_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.breakout_apple_call_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", delta)
                            print("Contract placed:", self.breakout_apple_call_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(self.breakout_apple_call_options_contract, limit_order)

                            print("The final placed order for this trade:", placed_order)
                        elif condition == "sma":
                            self.sma_apple_call_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.sma_apple_call_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", delta)
                            print("Contract placed:", self.sma_apple_call_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.sma_apple_call_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)

                        self.save_data(message_data, number_of_contracts, contracts[0].strike)
                        return
                    else:
                        rights = ['P']

                        contracts = [Option(symbol, expiration, strike, right, 'SMART', tradingClass=symbol)
                                     for right in rights
                                     for expiration in expirations
                                     for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        contracts = self.ib.qualifyContracts(*contracts)
                        print("Number of valid contracts:", len(contracts))
                        print(contracts)

                        if condition == "breakout":
                            self.breakout_apple_put_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.breakout_apple_put_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", delta)
                            print("Contract placed:", self.breakout_apple_put_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.breakout_apple_put_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)
                        elif condition == "sma":
                            self.sma_apple_put_options_contract = contracts[0]

                            # get required tick data for greeks for the option contract
                            ticker_data = self.ib.reqTickers(self.sma_apple_put_options_contract)

                            # all greeks, then get ask and delta
                            ask_greeks = ticker_data[0].askGreeks
                            ask = ticker_data[0].ask
                            delta = ask_greeks.delta

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # create limit order with the ask price
                            limit_order = LimitOrder(action, number_of_contracts, ask)

                            print("All ticker data:", ticker_data)
                            print("Ask Price:", ask)
                            print("Ask Greek delta", delta)
                            print("Contract placed:", self.sma_apple_put_options_contract)
                            print("Options LimitOrder to place:", limit_order)

                            placed_order = self.ib.placeOrder(
                                self.sma_apple_put_options_contract,
                                limit_order
                            )

                            print("The final placed order for this trade:", placed_order)

                        self.save_data(message_data, number_of_contracts, contracts[0].strike)
                        return
            elif action == constants.SELL:
                if symbol == constants.AMAZON:
                    if condition == "breakout":
                        if right == "CALL":
                            if not self.breakout_amazon_call_options_contract == None:
                                # await self.sell_contract(action, condition, symbol)
                                ticker_data = self.ib.reqTickers(self.breakout_amazon_call_options_contract)

                                print("Contract to sell:", self.breakout_amazon_call_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.breakout_amazon_call_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.breakout_amazon_call_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                        if right == "PUT":
                            if not self.breakout_amazon_put_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.breakout_amazon_put_options_contract)

                                print("Contract to sell:", self.breakout_amazon_put_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.breakout_amazon_put_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.breakout_amazon_put_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                    if condition == "sma":
                        if right == "CALL":
                            if not self.sma_amazon_call_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.sma_amazon_call_options_contract)

                                print("Contract to sell:", self.sma_amazon_call_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.sma_amazon_call_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.sma_amazon_call_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                        if right == "PUT":
                            if not self.sma_amazon_put_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.sma_amazon_put_options_contract)

                                print("Contract to sell:", self.sma_amazon_put_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.sma_amazon_put_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.sma_amazon_put_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                elif symbol == constants.NVIDIA:
                    if condition == "breakout":
                        if right == "CALL":
                            if not self.breakout_nvidia_call_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.breakout_nvidia_call_options_contract)

                                print(ticker_data)

                                print("Contract to sell:", self.breakout_nvidia_call_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.breakout_nvidia_call_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.breakout_nvidia_call_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                        if right == "PUT":
                            if not self.breakout_nvidia_put_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.breakout_nvidia_put_options_contract)

                                print("Contract to sell:", self.breakout_nvidia_put_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.breakout_nvidia_put_options_contract,
                                                                sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.breakout_nvidia_put_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                    if condition == "sma":
                        if right == "CALL":
                            if not self.sma_nvidia_call_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.sma_nvidia_call_options_contract)

                                print("Contract to sell:", self.sma_nvidia_call_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.sma_nvidia_call_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.sma_nvidia_call_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                        if right == "PUT":
                            if not self.sma_nvidia_put_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.sma_nvidia_put_options_contract)

                                print("Contract to sell:", self.sma_nvidia_put_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.sma_nvidia_put_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.sma_nvidia_put_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                elif symbol == constants.APPLE:
                    if condition == "breakout":
                        if right == "CALL":
                            if not self.breakout_apple_call_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.breakout_apple_call_options_contract)

                                print("Contract to sell:", self.breakout_apple_call_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.breakout_apple_call_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.breakout_apple_call_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                        if right == "PUT":
                            if not self.breakout_apple_put_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.breakout_apple_put_options_contract)

                                print("Contract to sell:", self.breakout_apple_put_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                                sell_trade = self.ib.placeOrder(self.breakout_apple_put_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.breakout_apple_put_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                    if condition == "sma":
                        if right == "CALL":
                            if not self.sma_apple_call_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.sma_apple_call_options_contract)

                                print("Contract to sell:", self.sma_apple_call_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)

                                print(action)
                                print(contracts_from_buy_trade)
                                print(ticker_data[0].ask)
                                print(sell_limit_order)

                                sell_trade = self.ib.placeOrder(self.sma_apple_call_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.sma_apple_call_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)
                        if right == "PUT":
                            if not self.sma_apple_put_options_contract == None:
                                ticker_data = self.ib.reqTickers(self.sma_apple_put_options_contract)

                                print("Contract to sell:", self.sma_apple_put_options_contract)
                                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                                sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)

                                print(action)
                                print(contracts_from_buy_trade)
                                print(ticker_data[0].ask)
                                print(sell_limit_order)

                                sell_trade = self.ib.placeOrder(self.sma_apple_put_options_contract, sell_limit_order)
                                print("Sold! Trade:", sell_trade)

                                self.sma_apple_put_options_contract = None
                            else:
                                print("Can't find a contract for", symbol, " with condition", condition)

                # need to only do this if correct data was sent and ACTUALLY sold a trade.  If not, don't update.
                self.update_data(result, condition, symbol)
            else:
                print("Only action known is BUY and SELL, we don't do anything with this:", action)

    async def sell_contract(self, action, condition, symbol, contract):
        ticker_data = self.ib.reqTickers(contract)
        print("Contract to sell:", contract)

        contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
        sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
        sell_trade = None

        try:
            sell_trade = self.ib.placeOrder(contract, sell_limit_order)
            print("Sold! Trade:", sell_trade)
        except Exception as e:
            print(str(e))
            print("Couldn't sell the option.")
            print(sell_trade)

    async def ticker_info(self, contract):
        # get required tick data for greeks for the option contract
        ticker_data = self.ib.reqTickers(contract)

        print(ticker_data)

        # all greeks, then get ask and delta
        ask_greeks = ticker_data[0].askGreeks
        ask = ticker_data[0].ask
        delta = ask_greeks.delta
        gamma = ask_greeks.gamma

        # calculate number of contracts
        number_of_contracts = self.calculate_contracts(delta)

        return number_of_contracts, delta, gamma

    async def get_strike_price(self, strikes, symbol, expiration, right, profit_target):
        # get the delta and gamma for each of those
        # calculate the number of contracts and profit for them
        # choose which has the highest profit and return that back to use as the contract to buy!
        # formula to get profit from delta, gamma - ((delta + (gamma * math.floor(profit_target))) * profit_target) * contracts

        print(strikes)

        # Error 200, reqId 83: No security definition has been found for the request, contract: Option(symbol='AMZN', lastTradeDateOrContractMonth='20220805', strike=141.5, right='CALL', exchange='SMART')

        contract_a = None
        contract_b = None
        contract_c = None
        contract_d = None

        contract_array = [contract_a, contract_b, contract_c, contract_d]
        number_of_contracts_array = []
        profit_array = []

        print(contract_array)
        print(len(contract_array))

        print(len(strikes))

        for i in range(4):
            contract_array[i] = self.create_options_contract(symbol, expiration, strikes[i], right)
            number_of_contracts, delta, gamma = await self.ticker_info(contract_array[i])
            number_of_contracts_array.append(number_of_contracts)
            profit_array.append(self.calculate_estimated_profit(delta, gamma, profit_target, number_of_contracts))

        new_dict = {strikes[i]: profit_array[i] for i in range(len(strikes))}
        print("Created Dictionary:", new_dict)

        max_profit = max(new_dict.values)
        print(max_profit)

        max_key = max(new_dict.values, key = new_dict.get())

        return max_key

    def calculate_estimated_profit(self, delta, gamma, profit_target, number_of_contracts):
        print("Calculating Estimated Profit...")

        estimated_profit = ((delta + (gamma * math.floor(profit_target))) * profit_target) * number_of_contracts

        print("Estimated Profit =", estimated_profit)

        return estimated_profit

    def calculate_contracts(self, delta):
        print("Calculating the correct Strike price...")

        risk_amount = 0

        if constants.BALANCE <= 1000:
            risk_amount = constants.BALANCE * .05
        elif 3000 >= constants.BALANCE > 1000:
            risk_amount = constants.BALANCE * .02
        else:
            risk_amount = constants.BALANCE * .01

        number_of_contracts = risk_amount / ((delta * 100) / 2)
        rounded_contracts = math.floor(number_of_contracts)

        print("The number of contracts for delta of [", delta, "] =", number_of_contracts)
        print("Rounded down the number of contracts is", rounded_contracts)

        # on test day, just return 1 for the number contracts
        if rounded_contracts < 0:
            rounded_contracts = rounded_contracts * -1

        return rounded_contracts

    def create_options_contract(self, symbol, expiration, strike, right):
        return Option(
            symbol,
            expiration,
            strike,
            right,
            constants.SMART
        )

    def save_data(self, message_data, number_of_contracts, strike_price):
        print("Saving to database...")

        sqlite_insert_with_param = constants.INSERT_DATA
        sqlite_data = (
            message_data['symbol'],
            message_data['order']['condition'],
            message_data['order']['action'],
            message_data['order']['right'],
            number_of_contracts,
            message_data['order']['price'],
            strike_price,
            message_data['order']['stoploss'],
            message_data['order']['takeProfit'],
            message_data['order']['result'],
            message_data['order']['afterhours'],
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
        )

        print(sqlite_insert_with_param)
        print(sqlite_data)

        self.conn.cursor().execute(sqlite_insert_with_param, sqlite_data)
        self.conn.commit()

        print("Saved to database!")

    def get_matching_trade(self, symbol, condition, right, result):
        cursor = self.conn.cursor()
        if result == "W":
            cursor.execute(constants.MATCHING_TRADE_PROFIT, (symbol, condition, right))
        else:
            cursor.execute(constants.MATCHING_TRADE_STOPLOSS, (symbol, condition, right))

    def get_trade_contracts(self, symbol, condition):
        self.conn.row_factory = lambda cursor, row: row[0]
        cursor = self.conn.cursor()

        sqlite_insert_with_param = constants.GET_MATCHING_TRADE
        sqlite_data = (
            symbol,
            condition
        )

        number_of_contracts = cursor.execute(sqlite_insert_with_param, sqlite_data).fetchall()

        print("Number of contracts returned from database for", symbol, "and condition", condition, "is", number_of_contracts[0])

        return number_of_contracts[0]

    def update_data(self, result, condition, symbol):
        print("Updating database...")

        cursor = self.conn.cursor()
        cursor.execute(constants.UPDATE_DATA, (result, condition, symbol))
        self.conn.commit()

        rows_affected = cursor.rowcount

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

        # cursor = self.conn.cursor()
        rows = self.cursor.execute(constants.END_OF_DAY_RESULTS).fetchall()

        # for row in cursor:
        #     print(row)

        df = pd.DataFrame.from_records(rows, columns=[x[0] for x in self.cursor.description])
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

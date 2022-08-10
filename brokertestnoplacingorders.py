import math
import time
import pandas as pd
import asyncio
import nest_asyncio
import redis
import constants
import json
import mysql.connector
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

        self.cnx = mysql.connector.connect(**constants.config)
        self.cursor = self.cnx.cursor(buffered=True)

        try:
            self.cursor.execute(constants.CREATE_TABLE)
            self.cursor.execute(constants.CREATE_OPTIONS_TABLE)
            self.cnx.commit()
        except mysql.connector.Error as err:
            print("Failed creating table: {}".format(err))
            exit(1)

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
            action = message_data['order']['action']
            result = message_data['order']['result']

            print("This is a", right, "option to", action, "for", symbol, "@", price)
            print("Condition:", condition)
            print("Stoploss:", stoploss)
            print("Take Profit:", take_profit)
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

                            # ticker_data = self.ib.reqTickers(self.breakout_amazon_call_options_contract)
                            #
                            # # all greeks, then get ask and delta
                            # ask_greeks = ticker_data[0].askGreeks
                            # ask = ticker_data[0].ask
                            # delta = ask_greeks.delta
                            #
                            # # calculate number of contracts
                            # number_of_contracts = self.calculate_contracts(delta)
                            #
                            # # insert the option for later use if needed in database
                            # self.insert_option_contract(
                            #     condition,
                            #     self.breakout_amazon_call_options_contract,
                            #     number_of_contracts
                            # )
                            #
                            # # create limit order with the ask price
                            # limit_order = LimitOrder(action, number_of_contracts, ask)
                            #
                            # print("All ticker data:", ticker_data)
                            # print("Ask Price:", ask)
                            # print("Ask Greek delta", delta)
                            print("Contract placed:", self.breakout_amazon_call_options_contract)
                            # print("Options LimitOrder to place:", limit_order)

                            # placed_order = self.ib.placeOrder(
                            #     self.breakout_amazon_call_options_contract,
                            #     limit_order
                            # )

                            print("The final placed order for this trade:")
                        elif condition == "sma":
                            self.sma_amazon_call_options_contract = contracts[0]

                            # insert the option for later use if needed in database
                            self.insert_option_contract(condition, self.sma_amazon_call_options_contract)

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.sma_amazon_call_options_contract,
                                number_of_contracts
                            )

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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.breakout_amazon_put_options_contract,
                                number_of_contracts
                            )

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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.sma_amazon_put_options_contract,
                                number_of_contracts
                            )

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

                            # calculate number of contracts
                            number_of_contracts = self.calculate_contracts(delta)

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.breakout_nvidia_call_options_contract,
                                number_of_contracts
                            )

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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.sma_nvidia_call_options_contract,
                                number_of_contracts
                            )

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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.breakout_nvidia_put_options_contract,
                                number_of_contracts
                            )

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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.sma_nvidia_put_options_contract,
                                number_of_contracts
                            )

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

                        self.save_data(message_data, number_of_contracts, contracts[0].strike)
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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.breakout_apple_call_options_contract,
                                number_of_contracts
                            )

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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.sma_apple_call_options_contract,
                                number_of_contracts
                            )

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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.breakout_apple_put_options_contract,
                                number_of_contracts
                            )

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

                            # insert the option for later use if needed in database
                            self.insert_option_contract(
                                condition,
                                self.sma_apple_put_options_contract,
                                number_of_contracts
                            )

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
                # await self.sell_contract(action, condition, symbol, self.breakout_amazon_call_options_contract)
                if symbol == constants.AMAZON:
                    if condition == "breakout":
                        if right == "CALL":
                            await self.sell_contract(action, condition, symbol,
                                                     self.breakout_amazon_call_options_contract)
                            self.breakout_amazon_call_options_contract = None
                            print(self.breakout_amazon_call_options_contract)
                            # foundInDatabase = False
                            # contracts_from_buy_trade = 0
                            #
                            # if self.breakout_amazon_call_options_contract is None:
                            #     print("Didn't have contract stored in session, checking database.")
                            #     retrieved_contract, number_of_contracts = self.check_for_options_contract(symbol, condition)
                            #
                            #     if retrieved_contract:
                            #         foundInDatabase = True
                            #         contracts_from_buy_trade = number_of_contracts
                            #         self.breakout_amazon_call_options_contract = retrieved_contract
                            #
                            # if self.breakout_amazon_call_options_contract:
                            #     ticker_data = self.ib.reqTickers(self.breakout_amazon_call_options_contract)
                            #
                            #     print("Contract to sell:", self.breakout_amazon_call_options_contract)
                            #
                            #     if not foundInDatabase:
                            #         contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)
                            #
                            #     sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
                            #     sell_trade = self.ib.placeOrder(self.breakout_amazon_call_options_contract,
                            #                                     sell_limit_order)
                            #     print("Sold! Trade:", sell_trade)
                            #
                            #     self.breakout_amazon_call_options_contract = None
                            #     self.delete_options_contract(symbol, condition)
                            # else:
                            #     print("Couldn't find in database and didn't have in current session to sell.")
                        if right == "PUT":
                            await self.sell_contract(action, condition, symbol,
                                                     self.breakout_amazon_put_options_contract)
                            self.breakout_amazon_put_options_contract = None
                            print(self.breakout_amazon_put_options_contract)

                    if condition == "sma":
                        if right == "CALL":
                            if self.sma_amazon_call_options_contract != None:
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
                            if self.sma_amazon_put_options_contract != None:
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
                            if self.breakout_nvidia_call_options_contract != None:
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
                            if self.breakout_nvidia_put_options_contract != None:
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
                            if self.sma_nvidia_call_options_contract != None:
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
                            if self.sma_nvidia_put_options_contract != None:
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
                            if self.breakout_apple_call_options_contract != None:
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
                            if self.breakout_apple_put_options_contract != None:
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
                            if self.sma_apple_call_options_contract != None:
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
                            if self.sma_apple_put_options_contract != None:
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

    def check_for_option_in_database(self, condition, symbol):
        print("Checking for Option in database...")

        cursor = self.cnx.cursor()
        sql_query = constants.GET_OPTION_CONTRACT
        sql_input = (condition, symbol)

        cursor.execute(sql_query, sql_input)
        contract = cursor.fetchone()

        print(contract)

    async def sell_contract(self, action, condition, symbol, contract):
        foundInDatabase = False
        contracts_from_buy_trade = 0

        if contract is None:
            print("Didn't have contract stored in session, checking database.")
            retrieved_contract, number_of_contracts = self.check_for_options_contract(symbol, condition)

            if retrieved_contract:
                foundInDatabase = True
                contracts_from_buy_trade = number_of_contracts
                contract = retrieved_contract

        if contract:
            ticker_data = self.ib.reqTickers(contract)

            print("Contract to sell:", contract)

            if not foundInDatabase:
                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)

            sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
            # sell_trade = self.ib.placeOrder(contract,
            #                                 sell_limit_order)
            # print("Sold! Trade:", sell_trade)

            print("Sold trade!")

            self.delete_options_contract(symbol, condition)
        else:
            print("Couldn't find in database and didn't have in current session to sell.")

    async def ticker_info(self, contract):
        # get required tick data for greeks for the option contract
        ticker_data = self.ib.reqTickers(contract)

        print(ticker_data)

        # all greeks, then get ask and delta
        ask_greeks = ticker_data[0].askGreeks
        delta = ask_greeks.delta
        gamma = ask_greeks.gamma

        # calculate number of contracts
        number_of_contracts = self.calculate_contracts(delta)

        return number_of_contracts, delta, gamma

    async def get_strike_price(self, strikes, symbol, expiration, right, profit_target, contracts):
        # get the delta and gamma for each of those
        # calculate the number of contracts and profit for them
        # choose which has the highest profit and return that back to use as the contract to buy!
        # formula to get profit from delta, gamma - ((delta + (gamma * math.floor(profit_target))) * profit_target) * contracts

        print(strikes)

        # Error 200, reqId 83: No security definition has been found for the request, contract: Option(symbol='AMZN', lastTradeDateOrContractMonth='20220805', strike=141.5, right='CALL', exchange='SMART')

        number_of_contracts_array = []
        profit_array = []

        print(len(strikes))
        print(len(contracts))

        for i in range(len(contracts)):
            contracts[i] = self.create_options_contract(symbol, expiration, strikes[i], right)
            number_of_contracts, delta, gamma = await self.ticker_info(contracts[i])
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
        positive_delta = delta

        if delta < 0:
            positive_delta = delta * -1
            print("This was a PUT order, so we are calculating delta given:", delta, " with positive delta:", positive_delta)

        if constants.BALANCE <= 1000:
            risk_amount = constants.BALANCE * .05
        elif 3000 >= constants.BALANCE > 1000:
            risk_amount = constants.BALANCE * .02
        else:
            risk_amount = constants.BALANCE * .01

        number_of_contracts = risk_amount / ((positive_delta * 100) / 2)
        rounded_contracts = math.floor(number_of_contracts)

        print("The number of contracts for delta of [", delta, "] =", number_of_contracts)
        print("Rounded down the number of contracts is", rounded_contracts)

        # on test day, just return 1 for the number contracts
        return rounded_contracts

    def create_options_contract(self, symbol, expiration, strike, right):
        return Option(
            symbol,
            expiration,
            strike,
            right,
            constants.SMART
        )

    def delete_options_contract(self, symbol, condition):
        print("Deleting Option Contract from database since we sold!")

        sql_query = constants.DELETE_OPTION
        sql_input = (symbol, condition)

        self.cnx.cursor().execute(sql_query, sql_input)
        self.cnx.commit()

        print("Successfully deleted from database!")

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
            message_data['order']['result']
        )

        print(sqlite_insert_with_param)
        print(sqlite_data)

        self.cnx.cursor().execute(sqlite_insert_with_param, sqlite_data)
        self.cnx.commit()

        print("Saved to database!")

    def get_trade_contracts(self, symbol, condition):
        self.cnx.row_factory = lambda cursor, row: row[0]
        cursor = self.cnx.cursor()

        sqlite_insert_with_param = constants.GET_MATCHING_TRADE
        sqlite_data = (
            symbol,
            condition
        )

        cursor.execute(sqlite_insert_with_param, sqlite_data)
        number_of_contracts = cursor.fetchone()

        print(number_of_contracts[0])

        print("Number of contracts returned from database for", symbol, "and condition", condition, "is", number_of_contracts[0])

        return number_of_contracts[0]


    def update_data(self, result, condition, symbol):
        print("Updating database...")

        cursor = self.cnx.cursor()
        sql_update_query = constants.UPDATE_DATA
        sql_input_data = (result, condition, symbol)
        cursor.execute(sql_update_query, sql_input_data)
        self.cnx.commit()

        rows_affected = cursor.rowcount

        print("Updated", rows_affected, "rows in the database Successfully!")

    def insert_option_contract(self, condition, contract, number_of_contracts):
        # have a static db connection and then get cursor from that
        cursor = self.cnx.cursor()
        print("Inserting option contract into database...")
        print("The contract to insert:", contract)

        sqlite_insert_with_param = constants.INSERT_OPTION
        sqlite_data = (
            condition,
            contract.symbol,
            contract.lastTradeDateOrContractMonth,
            contract.strike,
            contract.right,
            contract.exchange,
            contract.tradingClass,
            number_of_contracts
        )

        cursor.execute(sqlite_insert_with_param, sqlite_data)

        self.cnx.commit()

        print("Inserted into Database:", sqlite_data)

    def check_for_options_contract(self, symbol, condition):
        print("Didn't have contract to Sell stored in session, checking database...")

        cursor = self.cnx.cursor()
        sql_query = constants.GET_OPTION_CONTRACT
        sql_input = (symbol, condition)
        cursor.execute(sql_query, sql_input)

        fsymbol, fexpiration, fstrike, fright, number_of_contracts = cursor.fetchone()

        found_contract = self.create_options_contract(fsymbol, fexpiration, fstrike, fright)
        self.ib.qualifyContracts(found_contract)

        print(found_contract)

        return found_contract, number_of_contracts


    def end_of_day_results(self):
        print("Retrieving end of day results...")

        cursor = self.cnx.cursor()
        cursor.execute(constants.END_OF_DAY_RESULTS)

        rows = cursor.fetchall()

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

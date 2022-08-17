import datetime
import time
import pandas as pd
import numpy
import asyncio
import nest_asyncio
import redis
import constants
import json
import mysql.connector
import os
from twilio.rest import Client
from ib_insync import IB, Stock, Option, LimitOrder
from apscheduler.schedulers.asyncio import AsyncIOScheduler


def get_correct_options_expiration(expirations):
    today_date = datetime.date.today().strftime("%Y%m%d")

    if expirations[0] == today_date:
        print("This is a zero day expiration date, so use the next expiration date.")
        expiration = expirations[1]
    else:
        expiration = expirations[0]

    print("The correct expiration chosen from list {} based on today's date: {} is {}."
          .format(expiration, today_date, expiration))

    return expiration


def create_options_contract(symbol, expiration, strike, right):
    """
    Create an Option Contract with following parameters:

    Parameters:
        symbol: Symbol name.
        expiration: The option's last trading day or contract month.
            YYYYMMDD format
        strike: The option's strike price.
        right: Put or call option.
            Valid values are 'P', 'PUT', 'C' or 'CALL'.
    """
    return Option(
        symbol,
        expiration,
        strike,
        right,
        constants.SMART
    )


class OptionsBot:
    def __init__(self):
        current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
        print("************************************")
        print("*       Starting Trading Bot       *")
        print("*      ", current_time, "       *")
        print("************************************")

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
        print("Connecting Redis Server...")

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

        print("Retrieving initial option chains...")
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

        print("Running Live!")

        self.sched = AsyncIOScheduler(daemon=True)
        self.sched.add_job(self.update_options_chains, 'cron', day_of_week='mon-fri', hour='8')
        self.sched.add_job(self.check_connection, 'cron', day_of_week='mon-fri', hour='9')
        # self.sched.add_job(self.check_account_balance, 'cron', day_of_week='mon-fri', hour='10')
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
            await self.check_connection()

            message_data = json.loads(message['data'])

            symbol = message_data['symbol']
            condition = message_data['order']['condition']
            price = message_data['order']['price']
            right = message_data['order']['right']
            action = message_data['order']['action']
            result = message_data['order']['result']

            print("This Trade is a(n) {} - {} [{}] option to {} @ {} with result: {}"
                  .format(symbol, condition, right, action, price, result))

            if action == constants.BUY:
                if symbol == constants.AMAZON:
                    # the first options chain in list of 16
                    options_chain = next(c for c in self.amazon_option_chains if
                                         c.exchange == constants.SMART and
                                         c.tradingClass == constants.AMAZON)

                    # get all the call strikes and put strikes
                    call_strikes = [strike for strike in options_chain.strikes
                                    if strike > price]
                    put_strikes = [strike for strike in options_chain.strikes
                                   if strike < price]
                    expirations = sorted(exp for exp in options_chain.expirations)[:2]

                    correct_expiration = get_correct_options_expiration(expirations)

                    call_above_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['C']
                        for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]
                    call_below_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['C']
                        for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]
                    put_above_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['P']
                        for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]
                    put_below_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['P']
                        for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]

                    call_contracts = numpy.concatenate((call_below_entry_price, call_above_entry_price))
                    put_contracts = numpy.concatenate((put_below_entry_price, put_above_entry_price))

                    if right == constants.CALL:
                        valid_contracts = self.ib.qualifyContracts(*call_contracts)

                        print("Number of valid contracts:", len(valid_contracts))
                        print("All valid contracts:", valid_contracts)

                        if condition == "breakout":
                            self.breakout_amazon_call_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.breakout_amazon_call_options_contract
                            )
                        elif condition == "sma":
                            self.sma_amazon_call_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.sma_amazon_call_options_contract
                            )
                    else:
                        valid_contracts = self.ib.qualifyContracts(*put_contracts)

                        print("Number of valid contracts:", len(valid_contracts))
                        print(valid_contracts)

                        if condition == "breakout":
                            self.breakout_amazon_put_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.breakout_amazon_put_options_contract
                            )
                        elif condition == "sma":
                            self.sma_amazon_put_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.sma_amazon_put_options_contract
                            )
                elif symbol == constants.NVIDIA:
                    options_chain = next(c for c in self.nvidia_option_chains if
                                         c.exchange == 'SMART' and c.tradingClass == constants.NVIDIA)

                    # get all the call strikes and put strikes
                    call_strikes = [strike for strike in options_chain.strikes
                                    if price < strike < price - constants.STRIKE_PRICE_CHECK_IN_THE_MONEY]
                    put_strikes = [strike for strike in options_chain.strikes
                                   if price > strike > price + constants.STRIKE_PRICE_CHECK_IN_THE_MONEY]
                    expirations = sorted(exp for exp in options_chain.expirations)[:2]

                    correct_expiration = get_correct_options_expiration(expirations)

                    call_above_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['C']
                        for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]
                    call_below_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['C']
                        for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]
                    put_above_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['P']
                        for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]
                    put_below_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['P']
                        for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]

                    call_contracts = numpy.concatenate((call_below_entry_price, call_above_entry_price))
                    put_contracts = numpy.concatenate((put_below_entry_price, put_above_entry_price))

                    if right == constants.CALL:
                        valid_contracts = self.ib.qualifyContracts(*call_contracts)

                        print("Number of valid contracts:", len(valid_contracts))
                        print(valid_contracts)

                        if condition == "breakout":
                            self.breakout_nvidia_call_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.breakout_nvidia_call_options_contract
                            )
                        elif condition == "sma":
                            self.sma_nvidia_call_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.sma_nvidia_call_options_contract
                            )
                    else:
                        valid_contracts = self.ib.qualifyContracts(*put_contracts)

                        print("Number of valid contracts:", len(valid_contracts))
                        print(valid_contracts)

                        if condition == "breakout":
                            self.breakout_nvidia_put_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.breakout_nvidia_put_options_contract
                            )
                        elif condition == "sma":
                            self.sma_nvidia_put_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.sma_nvidia_put_options_contract
                            )
                elif symbol == constants.APPLE:
                    # the first options chain in list of 16
                    options_chain = next(c for c in self.apple_option_chains if
                                         c.exchange == constants.SMART and c.tradingClass == constants.APPLE)

                    # get all the call strikes and put strikes
                    call_strikes = [strike for strike in options_chain.strikes
                                    if strike > price]
                    put_strikes = [strike for strike in options_chain.strikes
                                   if strike < price]
                    expirations = sorted(exp for exp in options_chain.expirations)[:2]

                    correct_expiration = get_correct_options_expiration(expirations)

                    call_above_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['C']
                        for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]
                    call_below_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['C']
                        for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]
                    put_above_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['P']
                        for strike in call_strikes[:constants.NUMBER_OF_STRIKE_PRICES]]
                    put_below_entry_price = [
                        Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                        for right in ['P']
                        for strike in put_strikes[-constants.NUMBER_OF_STRIKE_PRICES:]]

                    call_contracts = numpy.concatenate((call_below_entry_price, call_above_entry_price))
                    put_contracts = numpy.concatenate((put_below_entry_price, put_above_entry_price))

                    if right == constants.CALL:
                        valid_contracts = self.ib.qualifyContracts(*call_contracts)

                        print("Number of valid contracts:", len(valid_contracts))
                        print(valid_contracts)

                        if condition == "breakout":
                            self.breakout_apple_call_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.breakout_apple_call_options_contract
                            )
                        elif condition == "sma":
                            self.sma_apple_call_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.sma_apple_call_options_contract
                            )
                    else:
                        valid_contracts = self.ib.qualifyContracts(*put_contracts)

                        print("Number of valid contracts:", len(valid_contracts))
                        print(valid_contracts)

                        if condition == "breakout":
                            self.breakout_apple_put_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.breakout_apple_put_options_contract
                            )
                        elif condition == "sma":
                            self.sma_apple_put_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            await self.place_options_order(
                                message_data,
                                action,
                                condition,
                                self.sma_apple_put_options_contract
                            )
            elif action == constants.SELL:
                print("Checking open orders and trades to see how it works! Selling.....")
                open_orders = self.ib.openOrders()
                open_trades = self.ib.openTrades()
                print("Check open order:", open_orders)
                print("Open trades:", open_trades)

                if symbol == constants.AMAZON:
                    if condition == "breakout":
                        if right == "CALL":
                            await self.sell_contract(action, condition, symbol,
                                                     self.breakout_amazon_call_options_contract, result)
                            self.breakout_amazon_call_options_contract = None
                        if right == "PUT":
                            await self.sell_contract(action, condition, symbol,
                                                     self.breakout_amazon_put_options_contract, result)
                            self.breakout_amazon_put_options_contract = None
                    if condition == "sma":
                        if right == "CALL":
                            await self.sell_contract(action, condition, symbol,
                                                     self.sma_amazon_call_options_contract, result)
                            self.sma_amazon_call_options_contract = None
                        if right == "PUT":
                            await self.sell_contract(action, condition, symbol,
                                                     self.sma_amazon_put_options_contract, result)
                            self.sma_amazon_put_options_contract = None
                elif symbol == constants.NVIDIA:
                    if condition == "breakout":
                        if right == "CALL":
                            await self.sell_contract(action, condition, symbol,
                                                     self.breakout_nvidia_call_options_contract, result)
                            self.breakout_nvidia_call_options_contract = None
                        if right == "PUT":
                            await self.sell_contract(action, condition, symbol,
                                                     self.breakout_nvidia_put_options_contract, result)
                            self.breakout_nvidia_put_options_contract = None
                    if condition == "sma":
                        if right == "CALL":
                            await self.sell_contract(action, condition, symbol,
                                                     self.sma_nvidia_call_options_contract, result)
                            self.sma_nvidia_call_options_contract = None
                        if right == "PUT":
                            await self.sell_contract(action, condition, symbol,
                                                     self.sma_nvidia_put_options_contract, result)
                            self.sma_nvidia_put_options_contract = None
                elif symbol == constants.APPLE:
                    if condition == "breakout":
                        if right == "CALL":
                            await self.sell_contract(action, condition, symbol,
                                                     self.breakout_apple_call_options_contract, result)
                            self.breakout_apple_call_options_contract = None
                        if right == "PUT":
                            await self.sell_contract(action, condition, symbol,
                                                     self.breakout_apple_put_options_contract, result)
                            self.breakout_apple_put_options_contract = None
                    if condition == "sma":
                        if right == "CALL":
                            await self.sell_contract(action, condition, symbol,
                                                     self.sma_apple_call_options_contract, result)
                            self.sma_apple_call_options_contract = None
                        if right == "PUT":
                            await self.sell_contract(action, condition, symbol,
                                                     self.sma_apple_put_options_contract, result)
                            self.sma_apple_put_options_contract = None
            else:
                print("Only action known is BUY and SELL, we don't do anything with this:", action)

    async def place_options_order(self, message_data, action, condition, contract):
        ticker_data = self.ib.reqTickers(contract)

        # all greeks, then get ask and delta
        ask_greeks = ticker_data[0].askGreeks
        ask = ticker_data[0].ask
        delta = ask_greeks.delta
        gamma = ask_greeks.gamma
        implied_volatility = ask_greeks.impliedVol

        # calculate number of contracts
        number_of_contracts = constants.NUMBER_OF_CONTRACTS

        # create limit order with the ask price
        limit_order = LimitOrder(action, number_of_contracts, ask)

        print("All ticker data:", ticker_data)
        print("Ask Price:", ask)
        print("Ask Greek delta:", delta)
        print("Ask Greek gamma:", gamma)
        print("Ask Greek implied vol.:", implied_volatility)
        print("Contract placed:", contract)
        print("Options LimitOrder to place:", limit_order)
        print("The selected strike:", contract.strike)

        # place order
        placed_order = self.ib.placeOrder(
            contract,
            limit_order
        )

        # insert the option for later use if needed in database
        self.insert_option_contract(
            condition,
            contract,
            number_of_contracts
        )

        # save the data for signals table
        self.save_data(message_data, number_of_contracts, contract.strike, ask, gamma, delta, implied_volatility)

        print("The final placed order for this trade:", placed_order)

        return placed_order

    async def sell_contract(self, action, condition, symbol, contract, result):
        found_in_database = False
        contracts_from_buy_trade = 0

        if contract is None:
            print("Didn't have contract stored in session, checking database.")
            retrieved_contract, number_of_contracts = self.check_for_options_contract(symbol, condition)

            if retrieved_contract is not None:
                found_in_database = True
                contracts_from_buy_trade = number_of_contracts
                contract = retrieved_contract

        if contract:
            ticker_data = self.ib.reqTickers(contract)
            ask_greeks = ticker_data[0].askGreeks
            ask = ticker_data[0].ask
            delta = ask_greeks.delta
            gamma = ask_greeks.gamma
            implied_vol = ask_greeks.impliedVol

            print("Contract to sell:", contract)
            print("Sell Ask Price:", ask)
            print("Sell Delta:", delta)
            print("Sell Gamma:", gamma)
            print("Sell Implied Vol.:", implied_vol)

            if not found_in_database:
                # get number of contracts if we didn't need to find the options contract in the database
                # since it already existed in the session
                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)

            sell_limit_order = LimitOrder(action, contracts_from_buy_trade, ticker_data[0].ask)
            sell_trade = self.ib.placeOrder(contract,
                                            sell_limit_order)
            print("Sold! Trade:", sell_trade)

            # TODO: combine into 1 transaction
            self.delete_options_contract(symbol, condition)
            self.update_data(result, condition, symbol, ask, delta, gamma, implied_vol)
        else:
            print("Couldn't find in database and didn't have in current session to sell.")

    async def ticker_info(self, contracts):
        is_put = False

        closest_delta = 0.0
        deltas = []
        invalid_range_deltas = []
        valid_range_deltas = []

        # make dictionary and get closest delta and choose contract with corresponding strike price
        # can get a list of all tickers for all contracts at once
        for i in range(len(contracts)):
            ticker_data = self.ib.reqTickers(contracts[i])
            delta = ticker_data[0].askGreeks.delta
            deltas.append(delta)

            if delta < 0:
                is_put = True

                if not constants.PUT_UPPER_DELTA_BOUNDARY <= delta <= constants.PUT_LOWER_DELTA_BOUNDARY:
                    print("Delta wasn't in range: -0.50 <= delta <= -0.30:", delta)
                    invalid_range_deltas.append(delta)
                else:
                    valid_range_deltas.append(delta)
            else:
                if not constants.CALL_UPPER_DELTA_BOUNDARY >= delta >= constants.CALL_LOWER_DELTA_BOUNDARY:
                    print("Delta wasn't in range: 0.50 >= delta >= 0.30:", delta)
                    invalid_range_deltas.append(delta)
                else:
                    valid_range_deltas.append(delta)

        if len(deltas) > 0:
            if not is_put:
                closest_delta = deltas[
                    min(range(len(deltas)), key=lambda i: abs(deltas[i] - constants.SET_DELTA_COMPARISON))]
            else:
                closest_delta = deltas[
                    min(range(len(deltas)), key=lambda i: abs(deltas[i] + constants.SET_DELTA_COMPARISON))]

            print("The closest delta found is", closest_delta, "from all deltas:", deltas)
            print("Total deltas to choose from:", deltas)
            print("All deltas in range:", valid_range_deltas)
            print("All deltas out of range:", invalid_range_deltas)
        else:
            print("No deltas were in range.")

        if len(deltas) > 0:
            for i in range(len(deltas)):
                if closest_delta == deltas[i]:
                    print("Choosing contract:", contracts[i])
                    return contracts[i]
        else:
            print("Couldn't find delta for contract so defaulting to contract closest to [In The Money]:", contracts[len(contracts) - 1])
            return contracts[len(contracts) - 1]

    async def get_correct_contract_with_delta(self, contracts):
        print("Calculating correct contract with delta closest to 0.45...")

        chosen_options_contract = await self.ticker_info(contracts)

        print("Chosen options contract with the closet delta to 0.45:", chosen_options_contract)

        return chosen_options_contract

    def delete_options_contract(self, symbol, condition):
        print("Deleting Option Contract from database since we sold!")

        sql_query = constants.DELETE_OPTION
        sql_input = (symbol, condition)

        try:
            cursor = self.cnx.cursor()
            cursor.execute(sql_query, sql_input)
            self.cnx.commit()
        except mysql.connector.Error as err:
            print("Failed deleting option from table: {}".format(err))

        print("Successfully deleted from database!")

    def save_data(self, message_data, number_of_contracts, strike_price, ask, gamma, delta, implied_vol):
        print("Saving to database...")

        sql_query = constants.INSERT_DATA
        sql_input = (
            message_data['symbol'],
            message_data['order']['condition'],
            message_data['order']['action'],
            message_data['order']['right'],
            number_of_contracts,
            message_data['order']['price'],
            strike_price,
            message_data['order']['stoploss'],
            message_data['order']['takeProfit'],
            delta,
            gamma,
            ask,
            implied_vol,
            message_data['order']['result']
        )

        try:
            cursor = self.cnx.cursor()
            cursor.execute(sql_query, sql_input)
            self.cnx.commit()
        except mysql.connector.Error as err:
            print("Failed saving data to signals table: {}".format(err))

        print("Saved to database!")

    def get_trade_contracts(self, symbol, condition):
        self.cnx.row_factory = lambda curs, row: row[0]
        cursor = self.cnx.cursor()

        sqlite_insert_with_param = constants.GET_MATCHING_TRADE
        sqlite_data = (
            symbol,
            condition
        )

        cursor.execute(sqlite_insert_with_param, sqlite_data)
        number_of_contracts = cursor.fetchone()

        print(number_of_contracts[0])

        print("Number of contracts returned from database for", symbol, "and condition", condition, "is",
              number_of_contracts[0])

        return number_of_contracts[0]

    def update_data(self, result, condition, symbol, sell_ask, sell_delta, sell_gamma, sell_implied_vol):
        print("Updating database...")

        cursor = self.cnx.cursor()
        sql_update_query = constants.UPDATE_DATA
        sql_input_data = (result, sell_delta, sell_gamma, sell_ask, sell_implied_vol, condition, symbol)
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

        row = cursor.fetchone()

        # found in database
        if row:
            print(row)
            fsymbol = row[0]
            fexpiration = row[1]
            fstrike = row[2]
            fright = row[3]
            number_of_contracts = row[4]

            found_contract = create_options_contract(fsymbol, fexpiration, fstrike, fright)
            self.ib.qualifyContracts(found_contract)

            print(found_contract)
        else:
            print("No contract found in database.")
            return None, None

        return found_contract, number_of_contracts

    def end_of_day_results(self):
        print("Retrieving end of day results...")

        cursor = self.cnx.cursor()
        cursor.execute(constants.END_OF_DAY_RESULTS)

        rows = cursor.fetchall()

        df = pd.DataFrame.from_records(rows, columns=[rows[0] for rows in cursor.description])
        print(df)

    async def check_connection(self):
        """
        Check IB Connection
        """
        if not self.ib.isConnected() or not self.ib.client.isConnected():
            print("Attempting Reconnection to Interactive Brokers...")
            self.ib.disconnect()
            self.ib = IB()
            self.ib.connect('127.0.0.1', 7497, clientId=1)
            print("Reconnected! @", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))

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

            print("Updated Amazon Chain: ", self.amazon_option_chains)
            print("Updated Nvidia Chain: ", self.nvidia_option_chains)
            print("Updated Apple Chain: ", self.apple_option_chains)
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

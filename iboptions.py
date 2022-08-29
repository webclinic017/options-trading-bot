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
from ib_insync import IB, Stock, Option, LimitOrder, Ticker, OptionComputation
from apscheduler.schedulers.asyncio import AsyncIOScheduler


def get_correct_options_expiration(expirations):
    today_date = datetime.date.today().strftime("%Y%m%d")

    if expirations[0] == today_date:
        print("This is a zero day expiration date, so use the next expiration date.")
        expiration = expirations[1]
    else:
        expiration = expirations[0]

    print("The correct expiration chosen from list {} based on today's date: {} is {}."
          .format(expirations, today_date, expiration))

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


def set_pandas_configuration():
    pd.options.display.width = None
    pd.options.display.max_columns = None
    pd.set_option('display.max_rows', 3000)
    pd.set_option('display.max_columns', 3000)


class OptionsBot:
    def __init__(self):
        current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
        print("************************************")
        print("*       Starting Trading Bot       *")
        print("*      ", current_time, "       *")
        print("************************************")

        self.set_initial_options_contracts_to_none()
        set_pandas_configuration()

        nest_asyncio.apply()

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
            await self.check_database_connection()

            message_data = json.loads(message['data'])

            symbol = message_data['symbol']
            condition = message_data['order']['condition']
            price = message_data['order']['price']
            right = message_data['order']['right']
            action = message_data['order']['action']
            result = message_data['order']['result']

            await self.display_trade_information(action, condition, price, result, right, symbol)

            if action == constants.BUY:
                if symbol == constants.AMAZON:
                    if right == constants.CALL:
                        # the first options chain in list of 16
                        options_chain = self.get_correct_options_chain(symbol)

                        # get all the call strikes and put strikes
                        strikes_after_entry_price_call = [strike for strike in options_chain.strikes
                                                          if strike > price]
                        strikes_before_entry_price_call = [strike for strike in options_chain.strikes
                                                           if strike < price]
                        expirations = sorted(exp for exp in options_chain.expirations)[:2]

                        correct_expiration = get_correct_options_expiration(expirations)

                        call_above_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['C']
                            for strike in strikes_after_entry_price_call[:constants.NUMBER_OF_STRIKE_PRICES]]
                        call_below_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['C']
                            for strike in strikes_before_entry_price_call[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        call_contracts = numpy.concatenate((call_below_entry_price, call_above_entry_price))

                        valid_contracts = self.ib.qualifyContracts(*call_contracts)

                        if condition == "breakout":
                            self.breakout_amazon_call_options_contract = await self.get_correct_contract_with_delta(
                                valid_contracts)

                            # TODO: do this not None check for all
                            if self.breakout_amazon_call_options_contract is not None:
                                await self.place_options_order(
                                    message_data,
                                    action,
                                    condition,
                                    self.breakout_amazon_call_options_contract
                                )
                            else:
                                print("There were no valid contracts to choose from, not buying anything.")
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
                        # the first options chain in list of 16
                        options_chain = self.get_correct_options_chain(symbol)

                        # get all the call strikes and put strikes
                        strikes_after_entry_price_call = [strike for strike in options_chain.strikes
                                                          if strike > price]
                        strikes_before_entry_price_call = [strike for strike in options_chain.strikes
                                                           if strike < price]
                        expirations = sorted(exp for exp in options_chain.expirations)[:2]

                        correct_expiration = get_correct_options_expiration(expirations)

                        put_above_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['P']
                            for strike in strikes_after_entry_price_call[:constants.NUMBER_OF_STRIKE_PRICES]]
                        put_below_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['P']
                            for strike in strikes_before_entry_price_call[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        put_contracts = numpy.concatenate((put_below_entry_price, put_above_entry_price))

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
                    if right == constants.CALL:
                        # the first options chain in list of 16
                        options_chain = self.get_correct_options_chain(symbol)

                        # get all the call strikes and put strikes
                        strikes_after_entry_price_call = [strike for strike in options_chain.strikes
                                                          if strike > price]
                        strikes_before_entry_price_call = [strike for strike in options_chain.strikes
                                                           if strike < price]
                        expirations = sorted(exp for exp in options_chain.expirations)[:2]

                        correct_expiration = get_correct_options_expiration(expirations)

                        call_above_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['C']
                            for strike in strikes_after_entry_price_call[:constants.NUMBER_OF_STRIKE_PRICES]]
                        call_below_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['C']
                            for strike in strikes_before_entry_price_call[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        call_contracts = numpy.concatenate((call_below_entry_price, call_above_entry_price))

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
                        # the first options chain in list of 16
                        options_chain = self.get_correct_options_chain(symbol)

                        # get all the call strikes and put strikes
                        strikes_after_entry_price_call = [strike for strike in options_chain.strikes
                                                          if strike > price]
                        strikes_before_entry_price_call = [strike for strike in options_chain.strikes
                                                           if strike < price]
                        expirations = sorted(exp for exp in options_chain.expirations)[:2]

                        correct_expiration = get_correct_options_expiration(expirations)

                        put_above_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['P']
                            for strike in strikes_after_entry_price_call[:constants.NUMBER_OF_STRIKE_PRICES]]
                        put_below_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['P']
                            for strike in strikes_before_entry_price_call[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        put_contracts = numpy.concatenate((put_below_entry_price, put_above_entry_price))

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
                    if right == constants.CALL:
                        # the first options chain in list of 16
                        options_chain = self.get_correct_options_chain(symbol)

                        # get all the call strikes and put strikes
                        strikes_after_entry_price_call = [strike for strike in options_chain.strikes
                                                          if strike > price]
                        strikes_before_entry_price_call = [strike for strike in options_chain.strikes
                                                           if strike < price]
                        expirations = sorted(exp for exp in options_chain.expirations)[:2]

                        correct_expiration = get_correct_options_expiration(expirations)

                        call_above_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['C']
                            for strike in strikes_after_entry_price_call[:constants.NUMBER_OF_STRIKE_PRICES]]
                        call_below_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['C']
                            for strike in strikes_before_entry_price_call[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        call_contracts = numpy.concatenate((call_below_entry_price, call_above_entry_price))

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
                        # the first options chain in list of 16
                        options_chain = self.get_correct_options_chain(symbol)

                        # get all the call strikes and put strikes
                        strikes_after_entry_price_call = [strike for strike in options_chain.strikes
                                                          if strike > price]
                        strikes_before_entry_price_call = [strike for strike in options_chain.strikes
                                                           if strike < price]
                        expirations = sorted(exp for exp in options_chain.expirations)[:2]

                        correct_expiration = get_correct_options_expiration(expirations)

                        put_above_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['P']
                            for strike in strikes_after_entry_price_call[:constants.NUMBER_OF_STRIKE_PRICES]]
                        put_below_entry_price = [
                            Option(symbol, correct_expiration, strike, right, constants.SMART, tradingClass=symbol)
                            for right in ['P']
                            for strike in strikes_before_entry_price_call[-constants.NUMBER_OF_STRIKE_PRICES:]]

                        put_contracts = numpy.concatenate((put_below_entry_price, put_above_entry_price))

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

    def set_initial_options_contracts_to_none(self):
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

    def get_correct_options_chain(self, symbol):
        options_chain = None

        if symbol == constants.AMAZON:
            options_chain = next(c for c in self.amazon_option_chains if
                                 c.exchange == constants.SMART and
                                 c.tradingClass == constants.AMAZON)
        elif symbol == constants.NVIDIA:
            options_chain = next(c for c in self.nvidia_option_chains if
                                 c.exchange == constants.SMART and
                                 c.tradingClass == constants.NVIDIA)
        elif symbol == constants.APPLE:
            options_chain = next(c for c in self.apple_option_chains if
                                 c.exchange == constants.SMART and
                                 c.tradingClass == constants.APPLE)

        return options_chain

    async def display_trade_information(self, action, condition, price, result, right, symbol):
        print("\n*********** Trade Information ***********\n")
        print("Company:      {}".format(symbol))
        print("Condition:    {}".format(condition))
        print("Entry Price:  {}".format(price))
        print("Action:       {}".format(action))
        print("Right:        {}".format(right))
        print("Result W/L/P: {}\n".format(result))

    async def check_database_connection(self):
        """ Connect to MySQL database """
        if not self.cnx.is_connected() or not self.ib.client.isConnected():
            try:
                print("Attempting Reconnection to MySQL Database...")
                self.cnx.disconnect()
                self.cnx = mysql.connector.connect(**constants.config)
                print("Reconnected to MySQL Database @", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
            except mysql.connector.Error as err:
                print(err)
        else:
            print("Still connected to MySQL Database!")

    async def place_options_order(self, message_data, action, condition, contract):
        ticker_data = self.ib.reqTickers(contract)

        # all greeks, then get ask and delta
        ask_greeks = ticker_data[0].askGreeks
        bid = ticker_data[0].bid
        ask = ticker_data[0].ask
        theta = ask_greeks.theta
        delta = ask_greeks.delta
        gamma = ask_greeks.gamma
        implied_volatility = ask_greeks.impliedVol

        # calculate number of contracts
        number_of_contracts = constants.NUMBER_OF_CONTRACTS

        if abs(delta) < 0.35:
            number_of_contracts = number_of_contracts + 1

        # create limit order with the ask price
        limit_order = LimitOrder(action, number_of_contracts, bid)

        print("Ask Price:", ask)
        print("Bid Price:", bid)
        print("Ask Greek delta:", delta)
        print("Ask Greek gamma:", gamma)
        print("Ask Greek theta:", theta)
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
        self.save_data(message_data, number_of_contracts, contract.strike, ask, gamma, delta, theta, implied_volatility)

        print("The final placed order for this trade:", placed_order)

        return placed_order

    async def sell_contract(self, action, condition, symbol, contract, result):
        found_in_database = False
        contracts_from_buy_trade = 0

        if contract is None:
            print("Attempt 1: Didn't have contract stored in session to SELL.")
            retrieved_contract, number_of_contracts = self.check_for_options_contract(symbol, condition)

            if retrieved_contract is not None:
                print("Attempt 2: Found in database!")
                found_in_database = True
                contracts_from_buy_trade = number_of_contracts
                contract = retrieved_contract

        if contract:
            ticker_data = self.ib.reqTickers(contract)
            ask_greeks = ticker_data[0].askGreeks
            ask = ticker_data[0].ask
            bid = ticker_data[0].bid
            delta = ask_greeks.delta
            gamma = ask_greeks.gamma
            theta = ask_greeks.theta
            implied_vol = ask_greeks.impliedVol

            print("Contract to sell:", contract)
            print("Sell Ask Price:", ask)
            print("Sell Delta:", delta)
            print("Sell Gamma:", gamma)
            print("Sell Theta:", theta)
            print("Sell Implied Vol.:\n", implied_vol)

            if not found_in_database:
                contracts_from_buy_trade = self.get_trade_contracts(symbol, condition)

            sell_limit_order = LimitOrder(action, contracts_from_buy_trade, bid)
            sell_trade = self.ib.placeOrder(contract, sell_limit_order)
            print("Sold! Trade:", sell_trade)

            # TODO: combine into 1 transaction
            self.delete_options_contract(symbol, condition)
            self.update_data(result, condition, symbol, ask, delta, gamma, theta, implied_vol)
        else:
            print("Attempt 2: Couldn't find in database.")

    async def ticker_info(self, contracts):
        ticker_full_data = self.ib.reqTickers(*contracts)
        print(ticker_full_data)
        list(ticker_full_data)

        valid_deltas = []
        invalid_deltas = []
        all_deltas = [ticker.askGreeks.delta for ticker in ticker_full_data]

        print("All Deltas from ticker data:", all_deltas)

        if ticker_full_data[0].askGreeks.delta > 0:
            for i in range(len(all_deltas)):
                if all_deltas[i] is not None:
                    if constants.CALL_UPPER_DELTA_BOUNDARY > all_deltas[i] > constants.CALL_LOWER_DELTA_BOUNDARY:
                        print("Delta is in range of {} to {}: {}".format(
                            constants.CALL_LOWER_DELTA_BOUNDARY, constants.CALL_UPPER_DELTA_BOUNDARY, all_deltas[i]))
                        valid_deltas.append(all_deltas[i])
                    else:
                        print("Delta not in range of {} to {}: {}".format(
                            constants.CALL_LOWER_DELTA_BOUNDARY, constants.CALL_UPPER_DELTA_BOUNDARY, all_deltas[i]))
                        invalid_deltas.append(all_deltas[i])

            closest_ticker_index = max(range(len(ticker_full_data)),
                                       key=lambda i: ticker_full_data[
                                                         i].askGreeks.delta < constants.CALL_UPPER_DELTA_BOUNDARY)
        else:
            for i in range(len(all_deltas)):
                if all_deltas[i] is not None:
                    if constants.PUT_UPPER_DELTA_BOUNDARY < all_deltas[i] < constants.PUT_LOWER_DELTA_BOUNDARY:
                        print("Delta is in range of {} to {}: {}".format(
                            constants.PUT_UPPER_DELTA_BOUNDARY, constants.PUT_LOWER_DELTA_BOUNDARY, all_deltas[i]))
                        valid_deltas.append(all_deltas[i])
                    else:
                        print("Delta not in range of {} to {}: {}".format(
                            constants.PUT_UPPER_DELTA_BOUNDARY, constants.PUT_LOWER_DELTA_BOUNDARY, all_deltas[i]))
                        invalid_deltas.append(all_deltas[i])

            closest_ticker_index = min(range(len(ticker_full_data)),
                                       key=lambda i: ticker_full_data[
                                                         i].askGreeks.delta > constants.PUT_UPPER_DELTA_BOUNDARY)

            if closest_ticker_index > 0:
                closest_ticker_index = closest_ticker_index - 1

        print("All valid deltas     =", valid_deltas)
        print("All invalid deltas   =", invalid_deltas)
        print("\nContract Index      =", closest_ticker_index)
        print("Closest Delta        =", ticker_full_data[closest_ticker_index].askGreeks.delta)
        print("Closest Strike Price =", ticker_full_data[closest_ticker_index].contract.strike)
        print("Contract chosen      =", ticker_full_data[closest_ticker_index].contract)

        return ticker_full_data[closest_ticker_index].contract

    async def get_correct_contract_with_delta(self, contracts):
        print("\n*********** START Delta Calculation ***********\n")
        print("Calculating correct contract with delta closest to {}".format(constants.SET_DELTA_COMPARISON))

        valid_contracts_to_list = contracts

        print("All VALID contracts\n")
        df = pd.DataFrame(list(valid_contracts_to_list),
                          columns=['conId', 'symbol', 'lastTradeDateOrContractMonth', 'strike', 'right',
                                   'multiplier', 'exchange', 'currency', 'localSymbol', 'tradingClass'])
        print(df, "\n")

        if len(contracts) == 0:
            print("No valid contracts to get the correct delta.")
            print("*********** END Delta Calculation ***********\n")
            return None
        else:
            chosen_options_contract = await self.ticker_info(contracts)
            print("\n*********** END Delta Calculation ***********\n")
            return chosen_options_contract

    def delete_options_contract(self, symbol, condition):
        print("*********** Deleting Options from Database ***********\n")
        print("\nDeleting Option Contract from database since we sold!")

        sql_query = constants.DELETE_OPTION
        sql_input = (symbol, condition)

        try:
            cursor = self.cnx.cursor(buffered=True)
            cursor.execute(sql_query, sql_input)
            self.cnx.commit()
            cursor.close()
            print("Successfully deleted Option from table!")
            print("*********** Finished Deleting From Database ***********\n")
        except mysql.connector.Error as err:
            print("Failed deleting option from table: {}".format(err))
            print("*********** Error Deleting From Database ***********\n")

    def save_data(self, message_data, number_of_contracts, strike_price, ask, gamma, delta, theta, implied_vol):
        print("\n*********** Inserting Data in Database ***********\n")

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
            theta,
            ask,
            implied_vol,
            message_data['order']['result']
        )

        print("Data to be inserted in Database:", sql_input)

        try:
            cursor = self.cnx.cursor()
            cursor.execute(sql_query, sql_input)
            self.cnx.commit()
            cursor.close()
            print("\n*********** Successfully Inserted Data in Database ***********\n")
        except mysql.connector.Error as err:
            print("Failed saving data to signals table: {}".format(err))
            print("\n*********** Failed Updating Data in Database ***********\n")

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
        cursor.close()

        print(number_of_contracts[0])

        print("Number of contracts returned from database for", symbol, "and condition", condition, "is",
              number_of_contracts[0])

        return number_of_contracts[0]

    def update_data(self, result, condition, symbol, sell_ask, sell_delta, sell_gamma, sell_theta, sell_implied_vol):
        print("Updating database...")

        cursor = self.cnx.cursor(buffered=True)
        sql_update_query = constants.UPDATE_DATA
        sql_input_data = (result, sell_delta, sell_gamma, sell_theta, sell_ask, sell_implied_vol, condition, symbol)
        cursor.execute(sql_update_query, sql_input_data)
        self.cnx.commit()

        rows_affected = cursor.rowcount

        cursor.close()

        print("Updated", rows_affected, "rows in the database Successfully!")

    def insert_option_contract(self, condition, contract, number_of_contracts):
        # have a static db connection and then get cursor from that
        cursor = self.cnx.cursor(buffered=True)
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
        cursor.close()

        print("Inserted into Database:", sqlite_data)

    def check_for_options_contract(self, symbol, condition):
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
        else:
            print("Still connected to Interactive Brokers!")

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

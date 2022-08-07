"""
    All the strings and queries that won't change will be here
    to reference them easier and create fewer lines of code in other
    files.  Can add any other static variables here.
"""

BALANCE = 1000
RISK = .01

BUY = "BUY"
SELL = "SELL"
CALL = "CALL"
PUT = "PUT"
SMART = "SMART"
USD = "USD"
EXCHANGE = "NASDAQOM"

NETFLIX = "NFLX"
FORD = "F"
APPLE = "AAPL"
NVIDIA = "NVDA"
AMAZON = "AMZN"

NUMBER_OF_STRIKE_PRICES = 2

CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY,
        symbol,
        condition,
        action, 
        right,
        contracts,
        entryprice,
        strikeprice,
        stoploss,
        takeProfit,
        result,
        afterhours,
        timestamp
    )
"""

CREATE_OPTIONS_TABLE = """
    CREATE TABLE IF NOT EXISTS options (
        condition,
        symbol,
        lastTradeDateOrContractMonth,
        strike,
        right,
        exchange,
        tradingClass,
        timestamp
    )
"""

SELECT_OPTION = """SELECT * FROM options WHERE condition = ? AND symbol = ?"""
DELETE_OPTION = """DELETE FROM options WHERE condition = ? AND symbol = ?"""
INSERT_OPTION = """
    INSERT INTO options(condition, symbol, lastTradeDateOrContractMonth, strike, right, exchange, tradingClass, timestamp)
    VALUES(?, ?, ?, ?, ?, ?, ?, ?);
"""

END_OF_DAY_RESULTS = """SELECT result, count(*) FROM signals where timestamp > date('now', '0 days') GROUP BY result"""
DELETE_ALL = """DELETE FROM signals"""
SELECT_ALL = """SELECT * FROM signals"""
INSERT_DATA = """
    INSERT INTO signals(symbol, condition, action, right, contracts, entryprice, strikeprice, stoploss, takeProfit, result, afterhours, timestamp) 
    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
UPDATE_DATA = """UPDATE signals SET result = ? WHERE condition = ? AND action = 'BUY' AND result = 'P' AND symbol = ?"""

MATCHING_TRADE_STOPLOSS = """select strikeprice from signals where stoploss = ? and condition = ? and right = ?"""
MATCHING_TRADE_PROFIT = """select strikeprice from signals where takeprofit = ? and condition = ? and right = ?"""
GET_MATCHING_TRADE = """select contracts from signals where symbol = ? and condition = ? and result = 'P'"""

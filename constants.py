"""
    All the strings and queries that won't change will be here
    to reference them easier and create fewer lines of code in other
    files.  Can add any other static variables here.
"""

config = {
    'user': 'root',
    'password': 'adminpassword',
    'host': '127.0.0.1',
    'database': 'trade'
}

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
    CREATE TABLE  IF NOT EXISTS signals (
        id              INT(11) NOT NULL AUTO_INCREMENT,
        symbol          VARCHAR(10) NOT NULL,
        trade_condition VARCHAR(20) NOT NULL,
        trade_action    VARCHAR(4) NOT NULL, 
        trade_right     VARCHAR(4) NOT NULL,
        contracts       INT NOT NULL,
        entryprice      DECIMAL(10, 3),
        strikeprice     DECIMAL(10, 3) NOT NULL,
        stoploss        DECIMAL(10, 3),
        takeProfit      DECIMAL(10, 3),
        result          CHAR(1) NOT NULL,
        timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id)
    )
"""

CREATE_OPTIONS_TABLE = """
    CREATE TABLE IF NOT EXISTS options (
        trade_condition,
        symbol,
        lastTradeDateOrContractMonth,
        strike,
        trade_right,
        exchange,
        tradingClass,
        timestamp
    )
"""

SELECT_OPTION = """SELECT * FROM options WHERE condition = ? AND symbol = ?"""
DELETE_OPTION = """DELETE FROM options WHERE condition = ? AND symbol = ?"""
INSERT_OPTION = """
    INSERT INTO options
        (
            condition, 
            symbol, 
            lastTradeDateOrContractMonth, 
            strike, 
            right, 
            exchange, 
            tradingClass, 
            timestamp
        )
    VALUES(?, ?, ?, ?, ?, ?, ?, ?);
"""

END_OF_DAY_RESULTS = """SELECT result, count(*) FROM signals where timestamp > date('now', '0 days') GROUP BY result"""
DELETE_ALL = """DELETE FROM signals"""
SELECT_ALL = """SELECT * FROM signals order by id desc"""
INSERT_DATA = """
    INSERT INTO signals
        (
            symbol, 
            trade_condition, 
            trade_action, 
            trade_right, 
            contracts, 
            entryprice, 
            strikeprice, 
            stoploss, 
            takeProfit, 
            result
        ) 
    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
"""

TEST_INSERT = """
    INSERT INTO signals 
        (
            symbol, 
            trade_condition, 
            trade_action, 
            trade_right, 
            contracts, 
            entryprice, 
            strikeprice, 
            stoploss, 
            takeProfit, 
            result) 
    VALUES (%s, %s, 'buy', %s, 1, 100.0, 101.0, 102.0, 101.0, 'P')
"""

UPDATE_DATA = """
    UPDATE signals 
    SET result = %s 
    WHERE 
        trade_condition = %s AND 
        trade_action = 'BUY' AND 
        result = 'P' AND 
        symbol = %s
"""

MATCHING_TRADE_STOPLOSS = """select strikeprice from signals where stoploss = ? and trade_condition = ? and right = ?"""
MATCHING_TRADE_PROFIT = """select strikeprice from signals where takeprofit = ? and trade_condition = ? and right = ?"""
GET_MATCHING_TRADE = """select contracts from signals where symbol = ? and trade_condition = ? and result = 'P'"""

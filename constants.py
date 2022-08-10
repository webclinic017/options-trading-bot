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
        strikeprice     VARCHAR(10) NOT NULL,
        stoploss        DECIMAL(10, 3),
        takeProfit      DECIMAL(10, 3),
        result          CHAR(1) NOT NULL,
        timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id)
    )
"""

CREATE_OPTIONS_TABLE = """
    CREATE TABLE IF NOT EXISTS options (
        option_id                     INT(11) NOT NULL AUTO_INCREMENT,
        trade_condition               VARCHAR(20) NOT NULL,
        symbol                        VARCHAR(10) NOT NULL,
        lastTradeDateOrContractMonth  VARCHAR(20) NOT NULL, 
        strike                        VARCHAR(10) NOT NULL,
        trade_right                   VARCHAR(4) NOT NULL,
        exchange                      VARCHAR(20) NOT NULL,
        tradingClass                  VARCHAR(20) NOT NULL,
        contracts                     INT NOT NULL,
        timestamp                     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (option_id)
    )
"""

GET_OPTION_CONTRACT = """
    SELECT symbol, lastTradeDateOrContractMonth, strike, trade_right, contracts 
        FROM options 
        WHERE 
            symbol = %s AND 
            trade_condition = %s
"""
DELETE_OPTION = """DELETE FROM options WHERE symbol = %s AND trade_condition = %s"""
INSERT_OPTION = """
    INSERT INTO options
        (
            trade_condition, 
            symbol, 
            lastTradeDateOrContractMonth, 
            strike, 
            trade_right, 
            exchange, 
            tradingClass,
            contracts
        )
    VALUES(%s, %s, %s, %s, %s, %s, %s, %s);
"""

END_OF_DAY_RESULTS = """
    SELECT result, count(*) 
        FROM signals 
        WHERE timestamp > DATE(NOW()) - INTERVAL 1 DAY GROUP BY result
"""
DELETE_ALL = """DELETE FROM signals"""
SELECT_ALL = """SELECT * FROM signals"""
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

MATCHING_TRADE_STOPLOSS = """select strikeprice from signals where stoploss = %s and trade_condition = %s and right = %s"""
MATCHING_TRADE_PROFIT = """select strikeprice from signals where takeprofit = %s and trade_condition = %s and right = %s"""
GET_MATCHING_TRADE = """select contracts from signals where symbol = %s and trade_condition = %s and result = 'P'"""

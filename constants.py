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

TWILIO_ACCOUNT_SID = 'AC2981f034e5344f4f3a2bab5708568aad'
TWILIO_AUTH_TOKEN = '850cf9aa10130bcda8c902be9165bca1'

BALANCE = 2500
RISK = .02

BUY = "BUY"
SELL = "SELL"
CALL = "CALL"
PUT = "PUT"
SMART = "SMART"
USD = "USD"

NETFLIX = "NFLX"
FORD = "F"
APPLE = "AAPL"
NVIDIA = "NVDA"
AMAZON = "AMZN"

PUT_UPPER_DELTA_BOUNDARY = -0.50
PUT_LOWER_DELTA_BOUNDARY = -0.30
CALL_UPPER_DELTA_BOUNDARY = 0.50
CALL_LOWER_DELTA_BOUNDARY = 0.30
SET_DELTA_COMPARISON = 0.45
NUMBER_OF_STRIKE_PRICES = 5
STRIKE_PRICE_CHECK_IN_THE_MONEY = 3

NUMBER_OF_CONTRACTS = 4
# luis - NUMBER_OF_CONTRACTS = 4
# tyler - NUMBER_OF_CONTRACTS = 1

CREATE_TABLE = """
    CREATE TABLE  IF NOT EXISTS signals (
        id                  INT(11) NOT NULL AUTO_INCREMENT,
        symbol              VARCHAR(10) NOT NULL,
        trade_condition     VARCHAR(20) NOT NULL,
        trade_action        VARCHAR(4) NOT NULL, 
        trade_right         VARCHAR(4) NOT NULL,
        contracts           INT NOT NULL,
        entryprice          DECIMAL(10, 3),
        strikeprice         VARCHAR(10) NOT NULL,
        stoploss            DECIMAL(10, 3),
        take_profit         DECIMAL(10, 3),
        buy_delta           DECIMAL(10, 3),
        buy_gamma           DECIMAL(10, 3),
        buy_ask             DECIMAL(10, 3),
        buy_implied_vol     DECIMAL(10, 3),
        sell_delta          DECIMAL(10, 3) DEFAULT 0.00,
        sell_gamma          DECIMAL(10, 3) DEFAULT 0.00,
        sell_ask            DECIMAL(10, 3) DEFAULT 0.00,
        sell_implied_vol    DECIMAL(10, 3) DEFAULT 0.00,    
        result              CHAR(1) NOT NULL,
        buy_timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sell_timestamp      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id)
    )
"""

EXPORT_ALL_TRADES_CSV = """
    SELECT 
        'id',
        'symbol',
        'trade_condition',
        'trade_action',
        'trade_right',
        'contracts',
        'entryprice',
        'strikeprice',
        'stoploss',
        'take_profit',
        'buy_delta',
        'buy_gamma',
        'buy_ask',
        'buy_implied_vol',
        'sell_delta',
        'sell_gamma',
        'sell_ask',
        'sell_implied_vol',
        'result',
        'buy_timestamp',
        'sell_timestamp'
    UNION ALL
    SELECT * FROM signals
"""

EXPORT_DAILY_CSV = """
    SELECT 
        'id',
        'symbol',
        'trade_condition',
        'trade_action',
        'trade_right',
        'contracts',
        'entryprice',
        'strikeprice',
        'stoploss',
        'take_profit',
        'buy_delta',
        'buy_gamma',
        'buy_ask',
        'buy_implied_vol',
        'sell_delta',
        'sell_gamma',
        'sell_ask',
        'sell_implied_vol',
        'result',
        'buy_timestamp',
        'sell_timestamp'
    UNION ALL
    SELECT * FROM signals WHERE buy_timestamp > DATE(NOW()) - INTERVAL 1 DAY
"""

END_OF_DAY_RESULTS = """
    SELECT result, count(*) 
        FROM signals 
        WHERE buy_timestamp > DATE(NOW()) - INTERVAL 1 DAY GROUP BY result
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
            take_profit,
            buy_delta,
            buy_gamma,
            buy_ask,
            buy_implied_vol,
            result
        ) 
    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
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
            take_profit,
            buy_delta,
            buy_gamma,
            buy_ask,
            buy_implied_vol,
            result
        ) 
    VALUES (%s, %s, 'buy', %s, 2, 100.0, 101.0, 99.0, 101.0, 1.111, 0.543, 1.25, 0.0542345345, 'P')
"""

UPDATE_DATA = """
    UPDATE signals 
    SET 
        result = %s, 
        sell_delta = %s, 
        sell_gamma = %s, 
        sell_ask = %s, 
        sell_implied_vol = %s, 
        sell_timestamp = CURRENT_TIMESTAMP
    WHERE 
        trade_condition = %s AND 
        trade_action = 'BUY' AND 
        result = 'P' AND 
        symbol = %s
"""

GET_MATCHING_TRADE = """select contracts from signals where symbol = %s and trade_condition = %s and result = 'P'"""

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

"""
    All the strings and queries that won't change will be here
    to reference them easier and create fewer lines of code in other
    files.  Can add any other static variables here.
"""

CREATE_TRADE_TABLE = """
    CREATE TABLE IF NOT EXISTS trade (
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
        buy_theta           DECIMAL(10, 3),
        buy_ask             DECIMAL(10, 3),
        buy_bid             DECIMAL(10, 3),
        buy_implied_vol     DECIMAL(10, 3),
        sell_delta          DECIMAL(10, 3) DEFAULT 0.00,
        sell_gamma          DECIMAL(10, 3) DEFAULT 0.00,
        sell_theta          DECIMAL(10, 3) DEFAULT 0.00,
        sell_ask            DECIMAL(10, 3) DEFAULT 0.00,
        sell_bid            DECIMAL(10, 3) DEFAULT 0.00,
        sell_implied_vol    DECIMAL(10, 3) DEFAULT 0.00,    
        result              CHAR(1) NOT NULL,
        buy_timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sell_timestamp      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

CREATE_ACCOUNT_SUMMARY_TABLE = """
    CREATE TABLE IF NOT EXISTS account_summary (
        id                  INT(11) NOT NULL AUTO_INCREMENT,
        net_liquidity       DECIMAL(10, 2),
        buy_timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id)
    )
"""

INSERT_TRADE_DATA = """
    INSERT INTO trade
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
            buy_theta,
            buy_ask,
            buy_bid,
            buy_implied_vol,
            result
        ) 
    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
"""

UPDATE_TRADE_DATA = """
    UPDATE trade 
    SET 
        result = %s, 
        sell_delta = %s, 
        sell_gamma = %s,
        sell_theta = %s, 
        sell_ask = %s,
        sell_bid = %s, 
        sell_implied_vol = %s, 
        sell_timestamp = CURRENT_TIMESTAMP
    WHERE 
        trade_condition = %s AND 
        trade_action = 'BUY' AND 
        result = 'P' AND 
        symbol = %s
"""

DELETE_ALL_TRADE_DATA = """DELETE FROM trade"""

RETRIEVE_TRADE_ASK_PRICE = """SELECT trade_right, buy_ask FROM trade WHERE symbol = %s and trade_condition = %s and result = 'P' LIMIT 1"""
RETRIEVE_TRADE_DATA_TODAY = """SELECT * FROM trade WHERE DATE(buy_timestamp) = CURDATE()"""
RETRIEVE_TRADE_DATA_YESTERDAY = """
    SELECT * FROM trade WHERE buy_timestamp > DATE_SUB(CURRENT_DATE, INTERVAL 1 DAY) and DATE(buy_timestamp) < CURDATE()
"""
RETRIEVE_TRADE_CURRENT_MONTH = """ SELECT * FROM trade WHERE MONTH(buy_timestamp)=MONTH(now())"""

GET_MATCHING_TRADE = """select contracts from trade where symbol = %s and trade_condition = %s and result = 'P' LIMIT 1"""

RETRIEVE_OPTION_ALL_REMAINING_CONTRACTS = """
    SELECT symbol, trade_condition, lastTradeDateOrContractMonth, strike, trade_right, contracts FROM options 
"""
RETRIEVE_OPTION_CONTRACT = """
    SELECT symbol, lastTradeDateOrContractMonth, strike, trade_right, contracts 
        FROM options 
        WHERE 
            symbol = %s AND 
            trade_condition = %s 
        LIMIT 1
"""
DELETE_OPTION_DATA = """DELETE FROM options WHERE symbol = %s AND trade_condition = %s"""
INSERT_OPTION_DATA = """
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

RETRIEVE_NET_LIQUIDITY = """
    SELECT * FROM account_summary
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
    SELECT * FROM trade
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
    SELECT * FROM trade WHERE buy_timestamp > DATE(NOW()) - INTERVAL 1 DAY
"""

END_OF_DAY_RESULTS = """
    SELECT result, count(*) 
        FROM trade 
        WHERE buy_timestamp > DATE(NOW()) - INTERVAL 1 DAY GROUP BY result
"""
"""
    All the strings and queries that won't change will be here
    to reference them easier and create less lines of code in other
    files.  Can add any other static variables here.
"""

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

STRIKE_PRICE_DIFFERENCE = 7

CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS signals (
        symbol,
        action, 
        right,
        contracts,
        entryprice,
        strikeprice,
        result,
        afterhours,
        timestamp DEFAULT (strftime('%m/%d/%Y %H:%M:%S', datetime('now')))
    )
"""
DELETE_ALL = """DELETE FROM signals"""
SELECT_ALL = """SELECT * FROM signals"""
INSERT_DATA = """
    INSERT INTO signals(symbol, action, right, contracts, entryprice, strikeprice, result, afterhours) 
    VALUES(?, ?, ?, ?, ?, ?, ?, ?);
"""

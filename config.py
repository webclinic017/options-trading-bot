"""
    This is the configuration for servers and variables that are unique to each bot.
"""

database_config = {
    'user': 'root',
    'password': 'adminpassword',
    'host': '127.0.0.1',
    'database': 'trade'
}

redis_port = 6379
localhost_port = 5002
interactive_brokers_port = 7497

BALANCE = 2500
RISK = .02
NUMBER_OF_CONTRACTS = 1
DELTA_CONSTANT_ADD_CONTRACT = 0.20
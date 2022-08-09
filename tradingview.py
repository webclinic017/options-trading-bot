import redis
import mysql.connector
from flask import Flask, request, json, render_template

import constants

app = Flask(__name__)

# Redis connection
r = redis.Redis(host='localhost', port=6379, db=0)


@app.route('/testinsert/condition/<condition>/symbol/<symbol>/right/<right>', methods=['GET'])
def testinsert(condition, symbol, right):
    try:
        cnx = mysql.connector.connect(**constants.config)
        cursor = cnx.cursor()
        cursor.execute(constants.TEST_INSERT, (condition, symbol, right))
        cnx.commit()
        cnx.close()
    except mysql.connector.Error as err:
        print("Failed inserting test data: {}".format(err))

    return "success"


@app.route('/', methods=['GET'])
def dashboard():
    signals = []

    try:
        cnx = mysql.connector.connect(**constants.config)
        cursor = cnx.cursor()
        cursor.execute(constants.SELECT_ALL)
        signals = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        print("Failed retrieving from database: {}".format(err))

    return render_template("dashboard.html", signals=signals)


@app.route('/tradingview', methods=['POST'])
def alert():
    """
        This route retrieves alerts from TradingView.

        Any alert is then published to redis server, which the message then
        gets picked up by broker.py to buy or sell to Interactive Brokers.

        We also store the trade into the database.  Will need to update the
        same row if we won or lost instead of inserting a new row.
    """
    data = request.data

    if data:
        tradeview_message = json.loads(request.data)
        r.publish('tradingview', data)

        symbol = tradeview_message['symbol']
        condition = tradeview_message['order']['condition']
        price = tradeview_message['order']['price']
        stoploss = tradeview_message['order']['stoploss']
        take_profit = tradeview_message['order']['takeProfit']
        right = tradeview_message['order']['right']
        action = tradeview_message['order']['action']
        result = tradeview_message['order']['result']

        print("This is a", right, "option to", action, "for", symbol, "@", price)
        print("Condition:", condition)
        print("Stoploss:", stoploss)
        print("Take Profit:", take_profit)
        print("Won/Loss/Pending?:", result)

        return data

    return "success"


if __name__ == "__main__":
    app.run(port=5002, debug=True)

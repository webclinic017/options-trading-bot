import redis
import mysql.connector
import constants
from flask import Flask, request, json, render_template

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

    total_trades = len(signals)
    list(signals)
    print(signals)

    average_call_delta = sum((i[10] for i in signals if i[4] == constants.CALL)) / len(signals)
    average_call_gamma = sum((i[11] for i in signals if i[4] == constants.CALL)) / len(signals)
    average_call_ask   = sum((i[12] for i in signals if i[4] == constants.CALL)) / len(signals)
    average_put_delta = sum((i[10] for i in signals if i[4] == constants.PUT)) / len(signals)
    average_put_gamma = sum((i[11] for i in signals if i[4] == constants.PUT)) / len(signals)
    average_put_ask   = sum((i[12] for i in signals if i[4] == constants.PUT)) / len(signals)

    return render_template(
        "dashboard.html",
        signals=signals,
        trades=total_trades,
        average_call_delta=average_call_delta,
        average_call_gamma=average_call_gamma,
        average_call_ask=average_call_ask,
        average_put_delta=average_put_delta,
        average_put_gamma=average_put_gamma,
        average_put_ask=average_put_ask
    )


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

import time
import redis
from flask import Flask, request, views, json, render_template

app = Flask(__name__)

# Redis connection
r = redis.Redis(host='localhost', port=6379, db=0)

@app.route('/', methods=['GET'])
def dashboard():
    return render_template("dashboard.html")

@app.route('/tradingview', methods=['POST'])
def alert():
    """
        This route retrieves alerts from TradingView.

        Any alert is then published to redis server, which the message then
        gets picked up by broker.py to buy or sell to Interactive Brokers.

        We also store the trade into the database.  Will need to update the
        same row if we won or lost instead of inserting a new row.
    """

    print("Testing trading view endpoint.")

    data = request.data

    if data:
        tradeview_message = json.loads(request.data)
        r.publish('tradingview', data)

        symbol = tradeview_message['symbol']
        price = tradeview_message['order']['price']
        # stoploss = tradeview_message['order']['stoploss']
        # take_profit = tradeview_message['order']['takeProfit']
        right = tradeview_message['order']['right']
        contracts = tradeview_message['order']['contracts']
        action = tradeview_message['order']['action']
        # result = tradeview_message['order']['result']
        # afterhours = tradeview_message['order']['afterhours']

        print("This is a", right, "option to", action, "for", symbol, "@", price, "and", contracts, "contracts")
        # print("Stoploss:", stoploss)
        # print("Take Profit:", take_profit)
        # print("Afterhours?:", afterhours)
        # print("Won/Loss/Pending?:", result)

        return data

    return "success"


if __name__ == "__main__":
    app.run(port=5002, debug=True)

import redis
import mysql.connector
import constants
import json
import csv
import io
from flask import Flask, request, json, render_template, make_response

app = Flask(__name__)

# Redis connection
r = redis.Redis(host='localhost', port=6379, db=0)


@app.route('/testinsert/condition/<condition>/symbol/<symbol>/right/<right>', methods=['GET'])
def testinsert(condition, symbol, right):
    try:
        cnx = mysql.connector.connect(**constants.config)
        cursor = cnx.cursor(buffered=True)
        cursor.execute(constants.TEST_INSERT, (symbol, condition, right))
        cnx.commit()
        cnx.close()
    except mysql.connector.Error as err:
        print("Failed inserting test data: {}".format(err))

    return "success"


@app.route('/', methods=['GET'])
def dashboard():
    signals_today = []
    signals_yesterday = []
    signals_current_month = []
    net_liquidity = []

    try:
        cnx = mysql.connector.connect(**constants.config)
        cursor = cnx.cursor(buffered=True)
        cursor.execute(constants.RETRIEVE_SIGNALS_DATA_TODAY)
        signals_today = cursor.fetchall()
        cursor.execute(constants.RETRIEVE_SIGNALS_DATA_YESTERDAY)
        signals_yesterday = cursor.fetchall()
        cursor.execute(constants.RETRIEVE_SIGNALS_CURRENT_MONTH)
        signals_current_month = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        print("Failed retrieving from database: {}".format(err))

    total_call_trades = sum((1 for i in signals_today if i[4] == constants.CALL))
    total_put_trades = sum((1 for i in signals_today if i[4] == constants.PUT))
    total_wins = sum((1 for i in signals_today if i[22] == 'W'))
    total_losses = sum((1 for i in signals_today if i[22] == 'L'))
    total_pending = sum((1 for i in signals_today if i[22] == 'P'))
    yesterday_total_wins = sum((1 for i in signals_yesterday if i[22] == 'W'))
    yesterday_total_losses = sum((1 for i in signals_yesterday if i[22] == 'L'))
    yesterday_total_pending = sum((1 for i in signals_yesterday if i[22] == 'P'))
    monthly_total_wins = sum((1 for i in signals_current_month if i[22] == 'W'))
    monthly_total_losses = sum((1 for i in signals_current_month if i[22] == 'L'))

    list(signals_today)
    list(signals_yesterday)
    list(signals_current_month)

    pie_chart_array = [total_wins, total_losses, total_pending]
    yesterday_pie_chart_array = [yesterday_total_wins, yesterday_total_losses, yesterday_total_pending]
    monthly_pie_chart_array = [monthly_total_wins, monthly_total_losses]

    return render_template(
        "dashboard.html",
        signals=signals_today,
        total_call_trades=total_call_trades,
        total_put_trades=total_put_trades,
        pie_chart_array=json.dumps(pie_chart_array),
        yesterday_pie_chart_array = json.dumps(yesterday_pie_chart_array),
        monthly_pie_chart_array = json.dumps(monthly_pie_chart_array),
        wins=total_wins,
        losses=total_losses,
        yesterday_wins=yesterday_total_wins,
        yesterday_losses=yesterday_total_losses,
        monthly_wins=monthly_total_wins,
        monthly_losses=monthly_total_losses
    )


@app.route('/generate')
def generate():
    signals = []

    try:
        cnx = mysql.connector.connect(**constants.config)
        cursor = cnx.cursor()
        cursor.execute(constants.EXPORT_DAILY_CSV)
        signals = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        print("Failed downloading CSV file: {}".format(err))

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerows(signals)
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=export.csv"
    output.headers["Content-type"] = "text/csv"

    return output


@app.route('/tradingview', methods=['POST'])
def alert():
    """
        This route retrieves alerts from TradingView.

        Any alert is then published to redis server, which the message then
        gets picked up by iboptions.py to buy or sell to Interactive Brokers.
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

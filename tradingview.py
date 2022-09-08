import redis
import mysql.connector

import config
import constants
import tables
import json
import csv
import io
from flask import Flask, request, json, render_template, make_response

app = Flask(__name__)

# Redis connection
r = redis.Redis(host='localhost', port=config.redis_port, db=0)


@app.route('/', methods=['GET'])
def dashboard():
    trades_today = []
    trades_yesterday = []
    trades_current_month = []

    try:
        cnx = mysql.connector.connect(**config.database_config)
        cursor = cnx.cursor(buffered=True)
        cursor.execute(tables.RETRIEVE_TRADE_DATA_TODAY)
        trades_today = cursor.fetchall()
        cursor.execute(tables.RETRIEVE_TRADE_DATA_YESTERDAY)
        trades_yesterday = cursor.fetchall()
        cursor.execute(tables.RETRIEVE_TRADE_CURRENT_MONTH)
        trades_current_month = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        print("Failed retrieving from database: {}".format(err))

    total_call_trades = sum((1 for i in trades_today if i[4] == constants.CALL))
    total_put_trades = sum((1 for i in trades_today if i[4] == constants.PUT))
    total_wins = sum((1 for i in trades_today if i[22] == 'W'))
    total_losses = sum((1 for i in trades_today if i[22] == 'L'))
    total_pending = sum((1 for i in trades_today if i[22] == 'P'))
    yesterday_total_wins = sum((1 for i in trades_yesterday if i[22] == 'W'))
    yesterday_total_losses = sum((1 for i in trades_yesterday if i[22] == 'L'))
    yesterday_total_pending = sum((1 for i in trades_yesterday if i[22] == 'P'))
    monthly_total_wins = sum((1 for i in trades_current_month if i[22] == 'W'))
    monthly_total_losses = sum((1 for i in trades_current_month if i[22] == 'L'))

    list(trades_today)
    list(trades_yesterday)
    list(trades_current_month)

    pie_chart_array = [total_wins, total_losses, total_pending]
    yesterday_pie_chart_array = [yesterday_total_wins, yesterday_total_losses, yesterday_total_pending]
    monthly_pie_chart_array = [monthly_total_wins, monthly_total_losses]

    return render_template(
        "dashboard.html",
        signals=trades_today,
        total_call_trades=total_call_trades,
        total_put_trades=total_put_trades,
        pie_chart_array=json.dumps(pie_chart_array),
        yesterday_pie_chart_array=json.dumps(yesterday_pie_chart_array),
        monthly_pie_chart_array=json.dumps(monthly_pie_chart_array),
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
        cnx = mysql.connector.connect(**config.database_config)
        cursor = cnx.cursor()
        cursor.execute(tables.EXPORT_DAILY_CSV)
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
        trade_message = json.loads(request.data)
        r.publish('tradingview', data)

        symbol = trade_message['symbol']
        condition = trade_message['order']['condition']
        price = trade_message['order']['price']
        stoploss = trade_message['order']['stoploss']
        take_profit = trade_message['order']['takeProfit']
        right = trade_message['order']['right']
        action = trade_message['order']['action']
        result = trade_message['order']['result']

        print("This is a", right, "option to", action, "for", symbol, "@", price)
        print("Condition:", condition)
        print("Stoploss:", stoploss)
        print("Take Profit:", take_profit)
        print("Won/Loss/Pending?:", result)

        return data

    return "success"


if __name__ == "__main__":
    app.run(port=config.localhost_port, debug=True)

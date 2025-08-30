from flask import Flask, render_template, jsonify
import subprocess
import threading

app = Flask(__name__)

bot_process = None  # store subprocess handle


def run_bot():
    global bot_process
    bot_process = subprocess.Popen(["python", "bot.py"])


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start-bot", methods=["POST"])
def start_bot():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return jsonify({"status": "already running"})
    
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/stop-bot", methods=["POST"])
def stop_bot():
    global bot_process
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        bot_process = None
        return jsonify({"status": "stopped"})
    return jsonify({"status": "not running"})


if __name__ == "__main__":
    app.run(debug=True)

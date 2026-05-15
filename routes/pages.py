from flask import Blueprint, current_app, render_template, send_from_directory

from lib.strategies import experimental_strategies, maintained_strategies

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return render_template(
        "index.html",
        maintained_strategies=maintained_strategies(),
        experimental_strategies=experimental_strategies(),
    )


@bp.route("/backtest")
def backtest_report():
    return render_template(
        "backtest.html",
        maintained_strategies=maintained_strategies(),
        experimental_strategies=experimental_strategies(),
    )


@bp.route("/portfolio")
def portfolio():
    return render_template("portfolio.html")


@bp.route("/favicon.ico")
def favicon():
    return send_from_directory(
        current_app.static_folder,
        "favicon.svg",
        mimetype="image/svg+xml",
    )

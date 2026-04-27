from flask import Flask

try:
    from flask_compress import Compress
except ImportError:  # Optional dependency; run without gzip if missing.
    Compress = None

from lib.paths import get_resource_path
from routes import ALL_BLUEPRINTS


def create_app() -> Flask:
    flask_app = Flask(
        __name__,
        template_folder=get_resource_path("templates"),
        static_folder=get_resource_path("static"),
    )

    if Compress is not None:
        flask_app.config.setdefault("COMPRESS_MIMETYPES", [
            "application/json",
            "text/html",
            "text/css",
            "text/javascript",
            "application/javascript",
        ])
        flask_app.config.setdefault("COMPRESS_MIN_SIZE", 500)
        Compress(flask_app)

    for bp in ALL_BLUEPRINTS:
        flask_app.register_blueprint(bp)

    return flask_app


app = create_app()


if __name__ == "__main__":
    import argparse
    import os
    from routes.watchlist import schedule_daily_watchlist_prefetch

    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=5050)
    parser.add_argument(
        "--build-chart-cache",
        action="store_true",
        help="Build watchlist chart artifacts before starting the server.",
    )
    parser.add_argument(
        "--build-chart-cache-only",
        action="store_true",
        help="Build watchlist chart artifacts and exit without starting the server.",
    )
    args = parser.parse_args()
    if args.build_chart_cache or args.build_chart_cache_only:
        from lib.chart_prewarmer import build_watchlist_chart_artifacts

        with app.app_context():
            summary = build_watchlist_chart_artifacts(app)
        print(
            "Chart cache build complete: "
            f"{summary['ok']}/{summary['requests']} requests ok "
            f"for {summary['tickers']} tickers"
            + (
                f" across {summary['strategies']} strategies"
                if summary.get("strategies")
                else ""
            )
            + (" (aborted after repeated failures)" if summary.get("aborted") else "")
        )
        if args.build_chart_cache_only:
            raise SystemExit(0)
    debug = True
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        with app.app_context():
            schedule_daily_watchlist_prefetch()
        # Start the chart payload prewarmer in the same reloader-guarded
        # block so Werkzeug's auto-restart doesn't spawn two of them.
        from lib.chart_prewarmer import ChartPrewarmer
        ChartPrewarmer(app).start()
    # threaded=True lets the background chart prewarmer (see lib/chart_prewarmer.py)
    # run concurrently with user requests instead of queuing behind them.
    app.run(debug=debug, port=args.port, threaded=True)

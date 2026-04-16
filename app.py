from flask import Flask

from lib.paths import get_resource_path
from routes import ALL_BLUEPRINTS


def create_app() -> Flask:
    flask_app = Flask(
        __name__,
        template_folder=get_resource_path("templates"),
        static_folder=get_resource_path("static"),
    )

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
    args = parser.parse_args()
    debug = True
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        with app.app_context():
            schedule_daily_watchlist_prefetch()
    app.run(debug=debug, port=args.port)

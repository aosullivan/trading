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
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=5050)
    args = parser.parse_args()
    app.run(debug=True, port=args.port)

from flask import Flask

from routes import ALL_BLUEPRINTS

app = Flask(__name__)

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", type=int, default=5050)
    args = parser.parse_args()
    app.run(debug=True, port=args.port)

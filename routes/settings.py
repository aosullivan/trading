from flask import Blueprint, jsonify, request

from lib.user_settings import load_settings, save_settings

bp = Blueprint("settings", __name__)


@bp.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@bp.route("/api/settings", methods=["PUT"])
def put_settings():
    data = request.get_json(force=True) or {}
    updated = save_settings(data)
    return jsonify(updated)

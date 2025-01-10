from flask import Blueprint, jsonify

bp = Blueprint('routes', __name__)

@bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

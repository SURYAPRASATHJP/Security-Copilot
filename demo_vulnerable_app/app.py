import os

import requests
from cryptography.hazmat.primitives import hashes
from flask import Flask, jsonify, request
from jinja2 import Template

app = Flask(__name__)

DEFAULT_TIMEOUT_SECONDS = 10
GREETING = Template("Hello {{ name }}, this service is running.")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/greet")
def greet():
    return GREETING.render(name=request.args.get("name", "stranger"))


@app.post("/fingerprint")
def fingerprint():
    """Return a SHA-256 digest of the request body so callers can compare uploads."""
    digest = hashes.Hash(hashes.SHA256())
    digest.update(request.get_data())
    return jsonify({"sha256": digest.finalize().hex()})


@app.get("/upstream")
def upstream():
    url = request.args.get("url", "https://example.com")
    response = requests.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
    return jsonify({"status_code": response.status_code, "length": len(response.content)})


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5000)))

import requests


def fetch(url):
    return requests.get(url, timeout=5).status_code

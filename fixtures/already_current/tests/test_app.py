from app import fetch


def test_fetch_is_callable():
    assert callable(fetch)

import requests


def user_agent():
    # This attribute was removed after 2.27, so the upgrade breaks the test below.
    return requests.utils.default_user_agent()

from app import user_agent


def test_user_agent_mentions_the_old_version():
    assert "2.27" in user_agent()

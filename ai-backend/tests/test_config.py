

def test_server_keep_alive_outlasts_the_tv_client_pool():
    from utubot.config import ServerConfig

    assert ServerConfig().keep_alive_s > 30

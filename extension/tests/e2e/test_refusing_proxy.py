import http.client

from refusing_proxy import RefusingProxy


def test_a_request_to_a_non_loopback_name_is_recorded_and_refused():
    proxy = RefusingProxy().start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
        connection.request("GET", "http://refused.example.invalid/x", headers={"Host": "refused.example.invalid"})
        assert connection.getresponse().status == 502
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=5)
        connection.request("GET", "/__log")
        answer = connection.getresponse().read()
        connection.close()
        assert {"method": "GET", "host": "refused.example.invalid"} in __import__("json").loads(answer)["requests"]
    finally:
        proxy.stop()

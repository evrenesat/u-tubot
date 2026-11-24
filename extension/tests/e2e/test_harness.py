import time

from selenium.webdriver.support.ui import WebDriverWait


def wait_answer(driver, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        answer = driver.execute_script("return window.__utubotAnswer ?? null")
        if answer is not None:
            return answer
        time.sleep(0.05)
    raise AssertionError("the extension page did not answer")


def grant(driver, origin):
    button = driver.execute_script(
        """
        window.__utubotAnswer = null;
        const button = document.createElement("button");
        button.textContent = "grant";
        button.addEventListener("click", () => {
          const api = globalThis.browser ?? globalThis.chrome;
          api.permissions.request({origins: [arguments[0]]}).then(
            (granted) => { window.__utubotAnswer = {granted}; },
            (error) => { window.__utubotAnswer = {error: String(error)}; },
          );
        });
        document.body.append(button);
        return button;
        """,
        origin,
    )
    button.click()
    return wait_answer(driver)


def test_the_test_variant_marks_the_fixture_and_answers_health(suite):
    suite.driver.get(suite.fixture("www/watch.html"))
    WebDriverWait(suite.driver, 5).until(
        lambda driver: driver.execute_script("return document.documentElement.dataset.utubot") == "1"
    )

    suite.driver.get(suite.page("pages/options.html"))
    assert grant(suite.driver, "http://127.0.0.2/*") == {"granted": True}
    suite.driver.execute_script(
        """
        window.__utubotAnswer = null;
        (async () => {
          try {
            const api = globalThis.browser ?? globalThis.chrome;
            await api.storage.local.set({
              "utubot.backend": arguments[0],
              "utubot.token": "utb_emulator",
              "utubot.user": "emu"
            });
            window.__utubotAnswer = {answer: await api.runtime.sendMessage({ type: "health", payload: {} })};
          } catch (error) {
            window.__utubotAnswer = {error: String(error)};
          }
        })();
        """,
        suite.backend_base,
    )
    assert wait_answer(suite.driver) == {"answer": {"ok": True}}


def test_zz_the_refusing_proxy_recorded_nothing(suite):
    requests = suite.proxy_log()
    assert requests == [], f"the e2e runs contacted: {sorted({entry['host'] for entry in requests})}"

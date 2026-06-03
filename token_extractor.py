"""
token_extractor.py — SSO Token Extraction via Selenium WebDriver.

Launches a browser (Edge or Chrome) with anti-detection options, navigates to
the Racpad environment URL, and waits for the user to complete SSO login.
After login, extracts tokens from browser localStorage/sessionStorage.

NOTE: verify=False is used for internal/test environments only.
      Set verify=True in production with valid certificates.
"""

import json
import base64
import time
import threading
import os

# ── Environment URLs ──────────────────────────────────────────────────────────

ENV_URLS = {
    "dev": "https://dev-menu-racpad.rentacenter.com/menu/",
    "qa": "https://qa-menu-racpad.rentacenter.com/menu/",
    "prod": "https://menu-racpad.rentacenter.com/menu/",
}

# ── CDP JS Interceptor (survives SSO redirects) ──────────────────────────────

INTERCEPTOR_JS = """
(function () {
    if (window.__authCaptureInstalled) return;
    window.__authCaptureInstalled = true;
    window._authCapture = window._authCapture || [];
    var origOpen = XMLHttpRequest.prototype.open;
    var origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url) {
        this._xUrl = url; this._xHeaders = {};
        return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        if (this._xHeaders) this._xHeaders[name.toLowerCase()] = value;
        return origSetHeader.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        if (this._xHeaders && this._xHeaders['authorization'])
            window._authCapture.push({ url: this._xUrl, auth: this._xHeaders['authorization'] });
        return origSend.apply(this, arguments);
    };
    var origFetch = window.fetch;
    window.fetch = function(resource, init) {
        try {
            var auth = null;
            if (init && init.headers) {
                auth = typeof init.headers.get === 'function'
                    ? (init.headers.get('Authorization') || init.headers.get('authorization'))
                    : (init.headers['Authorization'] || init.headers['authorization']);
            }
            if (auth)
                window._authCapture.push({ url: typeof resource === 'string' ? resource : resource.url, auth: auth });
        } catch(e) {}
        return origFetch.apply(this, arguments);
    };
})();
"""

# ── Token extraction config ───────────────────────────────────────────────────

ID_TOKEN_SUFFIX = ".idToken"
ACCESS_TOKEN_SUFFIX = ".accessToken"
STORE_NUMBER_KEY = "storeNumber"


# ── Session state (thread-safe) ───────────────────────────────────────────────

class _TokenSession:
    """Holds the state of a single token-extraction session."""

    def __init__(self):
        self.lock = threading.RLock()  # Reentrant � same thread can re-acquire while holding it
        self.status = "idle"  # idle | browser_open | extracting | done | error
        self.tokens = None
        self.error = None
        self.driver = None

    def reset(self):
        with self.lock:
            self.status = "idle"
            self.tokens = None
            self.error = None
            self.driver = None


_session = _TokenSession()


def get_status():
    """Return current session status and tokens if done."""
    with _session.lock:
        return {
            "status": _session.status,
            "tokens": _session.tokens,
            "error": _session.error,
        }


def _is_browser_alive():
    try:
        if _session.driver is None:
            return False
        _ = _session.driver.window_handles
        return True
    except Exception:
        return False


def start_extraction(env="dev", browser="edge"):
    """Launch browser in a background thread and begin token extraction flow.

    Returns immediately. Poll get_status() for results.
    """
    with _session.lock:
        if _session.status == "browser_open":
            if not _is_browser_alive():
                _session.reset()  # browser closed by user, silently reclaim
            else:
                return {"error": "Browser session already in progress. Complete or cancel it first."}
        _session.reset()
        _session.status = "browser_open"

    thread = threading.Thread(target=_extraction_worker, args=(env, browser), daemon=True)
    thread.start()
    return {"status": "browser_open", "message": f"Browser launched for {env.upper()}. Complete SSO login."}


def extract_now():
    """Attempt to extract tokens from the currently open browser session."""
    with _session.lock:
        if _session.status != "browser_open" or _session.driver is None:
            return {"error": "No active browser session."}
        driver = _session.driver
        _session.status = "extracting"

    try:
        tokens = _extract_tokens_from_driver(driver)
        if not tokens.get("accessToken") and not tokens.get("idToken"):
            with _session.lock:
                _session.status = "browser_open"
            return {"error": "No tokens found yet. Make sure you have completed SSO login and the app has loaded."}

        # Success — close browser
        try:
            driver.quit()
        except Exception:
            pass

        with _session.lock:
            _session.tokens = tokens
            _session.status = "done"
            _session.driver = None

        return {"status": "done", "tokens": tokens}

    except Exception as e:
        with _session.lock:
            _session.status = "browser_open"
        return {"error": f"Token extraction failed: {e}"}


def cancel_session():
    """Close the browser and cancel the current session."""
    with _session.lock:
        driver = _session.driver
        _session.reset()

    if driver:
        try:
            driver.quit()
        except Exception:
            pass

    return {"status": "idle", "message": "Session cancelled."}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extraction_worker(env, browser):
    """Background thread: launches browser, injects interceptor, navigates."""
    try:
        driver = _launch_browser(browser)
        with _session.lock:
            _session.driver = driver

        # Inject CDP interceptor before navigation (survives redirects)
        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": INTERCEPTOR_JS})
        except Exception:
            pass  # Some driver versions may not support this; tokens from localStorage still work

        # Navigate to environment URL
        url = ENV_URLS.get(env, ENV_URLS["dev"])
        driver.get(url)

        # Hide webdriver flag
        driver.execute_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

    except Exception as e:
        with _session.lock:
            _session.status = "error"
            _session.error = str(e)
            _session.driver = None


def _launch_browser(browser="edge"):
    """Launch Edge or Chrome with anti-detection options."""
    if browser == "chrome":
        return _launch_chrome()
    return _launch_edge()


def _launch_edge():
    """Launch Microsoft Edge with webdriver-manager, fallback to local driver."""
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service
    from selenium import webdriver

    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Try webdriver-manager first, fallback to local executable
    try:
        from webdriver_manager.microsoft import EdgeChromiumDriverManager
        svc = Service(executable_path=EdgeChromiumDriverManager().install())
    except Exception:
        # Fallback: look for msedgedriver.exe in project root or PATH
        local_path = os.path.join(os.path.dirname(__file__), "msedgedriver.exe")
        if os.path.exists(local_path):
            svc = Service(executable_path=local_path)
        else:
            svc = Service()  # Let Selenium find it in PATH

    driver = webdriver.Edge(service=svc, options=opts)
    driver.execute_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return driver


def _launch_chrome():
    """Launch Chrome with webdriver-manager, fallback to local driver."""
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium import webdriver

    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        svc = Service(executable_path=ChromeDriverManager().install())
    except Exception:
        local_path = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
        if os.path.exists(local_path):
            svc = Service(executable_path=local_path)
        else:
            svc = Service()

    driver = webdriver.Chrome(service=svc, options=opts)
    driver.execute_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return driver


def _extract_tokens_from_driver(driver):
    """Read tokens from localStorage and sessionStorage."""
    tokens = {}

    # Read all localStorage
    ls = driver.execute_script("""
        var o={};
        for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);o[k]=localStorage.getItem(k);}
        return o;
    """) or {}

    for k, v in ls.items():
        if k.endswith(ACCESS_TOKEN_SUFFIX) and v:
            tokens["accessToken"] = v
        if k.endswith(ID_TOKEN_SUFFIX) and v:
            tokens["idToken"] = v

    # Read storeNumber from sessionStorage
    sn = driver.execute_script(f"return sessionStorage.getItem('{STORE_NUMBER_KEY}');")
    if sn:
        tokens["storeNumber"] = sn

    # Decode JWT to get expiration
    if tokens.get("accessToken"):
        try:
            payload = tokens["accessToken"].split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            if claims.get("exp"):
                tokens["expiresAt"] = claims["exp"]
        except Exception:
            pass

    return tokens

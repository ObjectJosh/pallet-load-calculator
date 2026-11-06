"""Minimal client for the onpallet.com web form, used only to collect reference data.

The calculator itself never contacts the site. Use this sparingly: it is a free public
service. Callers are expected to wait between requests (see collect.py, --delay).

Protocol (see docs/SPEC.md, section 5):
  1. GET  /           -> session cookie
  2. POST /index.php  -> HTML containing the result id ("pid")
  3. POST /pal.php    -> JSON layout for that pid
  4. POST /sel.php    -> results page with the summary table
"""
import html
import http.cookiejar
import json
import os
import re
import ssl
import urllib.parse
import urllib.request

BASE = "https://onpallet.com"
USER_AGENT = "pallet-load-calculator-validation"

PALLET_IDS = {"euro": "ps_pal1", "industrial": "ps_pal2", "us": "ps_pal3", "half": "ps_pal4",
              "australian": "ps_pal5"}

# Some Python builds on macOS ship without CA certificates; fall back to the system bundle.
_CA = next((c for c in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem")
            if os.path.exists(c)), None)
_SSL = ssl.create_default_context(cafile=_CA) if _CA else ssl.create_default_context()


class SiteError(RuntimeError):
    pass


class Session:
    """One calculation per session, so the result id always belongs to this session."""

    def __init__(self, timeout=30):
        self.timeout = timeout
        jar = http.cookiejar.CookieJar()
        self._op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),
                                               urllib.request.HTTPSHandler(context=_SSL))
        self._op.addheaders = [("User-Agent", USER_AGENT)]
        self._op.open(BASE + "/", timeout=timeout).read()
        self.pid = None

    def _post(self, path, data):
        body = urllib.parse.urlencode(data).encode()
        with self._op.open(BASE + path, body, timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")

    def submit(self, width, length, height, weight, pallet, load_height, unit="mm"):
        """Submit the form. Values are sent as given; round them like the browser first
        (palletcalc.half_up) if you want to reproduce what a person typing would get."""
        blank = "7.9" if unit == "in" else "200"  # the page always sends these; blanks break inch mode
        form = {"p_unit": unit, "p_width": width, "p_length": length, "p_height": height,
                "p_weight": weight, "p_loadheight": load_height, "ps_custW": blank,
                "ps_custL": blank, "calculate": "Calculate"}
        if str(pallet).startswith("custom:"):
            cw, cl = str(pallet).split(":", 1)[1].split("x")
            form.update(p_type="ps_palX", ps_custW=cw.strip(), ps_custL=cl.strip())
        else:
            form["p_type"] = PALLET_IDS[pallet]
        page = self._post("/index.php", {k: str(v) for k, v in form.items()})
        m = re.search(r'\\?"pid\\?"\s*:\s*\\?"([a-f0-9]+)', page)
        if not m:
            raise SiteError("no result id in response (input rejected)")
        self.pid = m.group(1)
        return self.pid

    def layout(self):
        """Layer layout as returned by /pal.php (status 0) or raise SiteError(status)."""
        data = json.loads(self._post("/pal.php", {"pal": json.dumps({"pid": self.pid, "num": 0})}))
        if data.get("status") != 0:
            raise SiteError(f"pal.php status {data.get('status')}")
        return data["pal"]

    def summary(self):
        """The 'Detail results' table of the results page, as {label: text}."""
        page = self._post("/sel.php", {"pid": self.pid, "palnum": "0", "palchange": ""})
        m = re.search(r"Detail results(.*?)</table>", page, re.S)
        if not m:
            raise SiteError("results table not found")
        cells = [html.unescape(re.sub(r"<[^>]*>", "", c)).strip()
                 for c in re.findall(r"<td>(.*?)</td>", m.group(1), re.S)]
        return dict(zip(cells[0::2], cells[1::2]))

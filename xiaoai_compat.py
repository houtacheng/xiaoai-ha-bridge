"""Experimental clock plumbing. No model-to-MiNA-hardware assumption is made."""
import json
import logging
import re
from urllib.parse import quote
from miservice import MiAccount as _MiAccount

CLOCK_MODEL = "zimi.clock.myk01"
_secrets = set()


class MiAccount(_MiAccount):
    """2.9.3's login helper disables TLS verification; keep it enabled here."""
    async def _serviceLogin(self, uri, data=None):
        self.now_ua = self.ua.random
        cookies = {"sdkVersion": "3.9", "deviceId": self.token["deviceId"],
                   "passToken": self.token.get("passToken", "")}
        if "passToken" in self.token:
            cookies["userId"] = self.token["userId"]
        async with self.session.request(
            "GET" if data is None else "POST",
            "https://account.xiaomi.com/pass/" + uri, data=data, cookies=cookies,
            headers={"User-Agent": self.now_ua}, ssl=True,
        ) as response:
            raw = await response.read()
        return json.loads(raw[11:])


def remember_secrets(value, sensitive=False):
    if isinstance(value, dict):
        for key, item in value.items():
            remember_secrets(item, sensitive or str(key).lower() in {
                "password", "token", "api_key", "cookie_text", "passtoken",
                "servicetoken", "ssecurity", "micoapi", "xiaomiio", "authorization",
            })
    elif isinstance(value, (list, tuple)):
        for item in value:
            remember_secrets(item, sensitive)
    elif sensitive and value:
        _secrets.add(str(value))


def redact(text):
    text = str(text)
    for secret in sorted(_secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]").replace(quote(secret, safe=""), "[REDACTED]")
    text = re.sub(r"(?i)(Bearer|Basic)\s+[^\s,;]+", r"\1 [REDACTED]", text)
    return re.sub(
        r'''(?ix)((?:["']?)(?:serviceToken|passToken|ssecurity|access_token|api_key|password|token|cookie|authorization)(?:["']?)\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s;,}]+)''',
        r"\1[REDACTED]", text,
    )


class SafeLogFilter(logging.Filter):
    def filter(self, record):
        # Dependency messages can contain entire authentication responses.
        if record.name == "miservice" or record.name.startswith("miservice."):
            return False
        if isinstance(record.args, tuple):
            record.args = tuple(type(a).__name__ if isinstance(a, BaseException) else a for a in record.args)
        record.msg = redact(record.getMessage())
        record.args = ()
        # Tracebacks from HTTP libraries may include response bodies / cookies.
        record.exc_info = None
        record.exc_text = None
        return True


async def discover_devices(na, cfg):
    """Keep MiNA deviceID separate from Mi Home did. master=1 is opt-in."""
    devices = await na.device_list() or []
    if not isinstance(devices, list):
        raise ValueError("unexpected_mina_device_list")
    if cfg.get("discovery_all"):
        extra = await na.device_list(master=1) or []
        if not isinstance(extra, list):
            raise ValueError("unexpected_mina_device_list")
        devices = devices + extra
    unique = {}
    for device in devices:
        if isinstance(device, dict) and device.get("deviceID"):
            unique[str(device["deviceID"])] = device
    return list(unique.values())


def select_target(devices, cfg):
    selected = str(cfg.get("device_id") or cfg.get("device_did") or "")
    if selected:
        # A Mi Home did may resolve a listed entry, but never becomes a MiNA ID.
        matches = [d for d in devices if selected in
                   (str(d.get("deviceID", "")), str(d.get("did", "")))]
        if len(matches) == 1:
            return matches[0]
        if not matches and cfg.get("allow_unlisted_device") and cfg.get("device_id"):
            if cfg.get("conversation_api", "auto") == "auto":
                raise ValueError("unlisted_device_requires_explicit_conversation_api")
            if cfg["conversation_api"] == "http" and not cfg.get("hardware"):
                raise ValueError("http_requires_observed_hardware")
            return {"deviceID": selected, "hardware": cfg.get("hardware", "")}
        raise ValueError("configured_device_not_uniquely_found")
    if len(devices) == 1:
        return devices[0]
    raise ValueError("select_one_mina_device_explicitly")


def conversation_api(cfg, hardware):
    mode = cfg.get("conversation_api", "auto")
    if mode not in {"auto", "mina", "http"}:
        raise ValueError("invalid_conversation_api")
    return ("mina" if hardware == "M01" else "http") if mode == "auto" else mode


def parse_http_records(payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid_conversation_response")
    if payload.get("code", 0) not in (0, "0"):
        raise ValueError("conversation_api_rejected")
    data = payload.get("data")
    if not data:
        return []
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict) or not isinstance(data.get("records", []), list):
        raise ValueError("invalid_conversation_records")
    return [r for r in data.get("records", []) if isinstance(r, dict)]


def normalize_mina_messages(messages):
    if not isinstance(messages, list):
        raise ValueError("invalid_mina_messages")
    records = []
    for msg in messages:
        answers = msg.get("response", {}).get("answer", [])
        if answers:
            records.append({"time": msg.get("timestamp_ms", 0),
                            "query": answers[0].get("question", ""), "answers": answers})
    return records


def parse_mina_result(payload):
    """Check both gateway and ubus status, unlike the dependency's empty fallback."""
    if not isinstance(payload, dict) or payload.get("code", 0) not in (0, "0"):
        raise ValueError("mina_gateway_rejected")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("code") not in (0, "0"):
        raise ValueError("mina_ubus_rejected")
    info = data.get("info")
    if isinstance(info, str):
        info = json.loads(info)
    if not isinstance(info, dict) or not isinstance(info.get("result"), list):
        raise ValueError("invalid_mina_result")
    records = []
    for item in info["result"]:
        nlp = item.get("nlp")
        if not nlp:
            continue
        if isinstance(nlp, str):
            nlp = json.loads(nlp)
        answers = nlp.get("response", {}).get("answer", [])
        if not isinstance(answers, list):
            raise ValueError("invalid_mina_answers")
        query = next((a.get("intention", {}).get("query", "") for a in answers
                      if isinstance(a, dict) and a.get("intention", {}).get("query")), "")
        records.append({"time": int(nlp.get("meta", {}).get("timestamp", 0)),
                        "query": query, "answers": answers})
    return records


async def fetch_mina_records(na, device_id):
    return parse_mina_result(await na.ubus_request(device_id, "nlp_result_get", "mibrain", {}))


def require_ubus_success(payload):
    if (not isinstance(payload, dict) or payload.get("code", 0) not in (0, "0")
            or not isinstance(payload.get("data"), dict)
            or payload["data"].get("code") not in (0, "0")):
        raise ValueError("ubus_request_not_accepted")


def public_devices(devices):
    """Only fields needed by the local selector; never expose device tokens."""
    return [{k: d[k] for k in ("deviceID", "did", "hardware", "model", "name") if k in d}
            for d in devices]

"""AI01ZM / zimi.clock.myk01 legacy miIO READ-ONLY status profile.

RPC names are documented by python-miio's zimi/clock/alarmclock driver.
No MiNA identifier mapping, speech RPC or alarm modification is inferred.
"""
import asyncio
import json
import time

from xiaoai_compat import CLOCK_MODEL

AIVS_PATH = "/v2/api/aivs"
# Public application identifier observed in Xiaomi's AI01ZM plugin v107.
AIVS_CLIENT_ID = "257885859209021440"


def select_clock(devices, clock_did=""):
    clocks = [d for d in devices if isinstance(d, dict) and d.get("model") == CLOCK_MODEL]
    if clock_did:
        clocks = [d for d in clocks if str(d.get("did", "")) == str(clock_did)]
    else:
        clocks = [d for d in clocks if d.get("isOnline") is True]
    if len(clocks) != 1 or not clocks[0].get("did"):
        raise ValueError("clock_target_not_unique")
    if clocks[0].get("isOnline") is False:
        raise ValueError("selected_clock_offline")
    return clocks[0]


def parse_clock_history(result):
    if isinstance(result, str):
        result = json.loads(result)
    if not isinstance(result, dict):
        raise ValueError("invalid_aivs_result")
    if result.get("code", 0) not in (0, "0"):
        raise ValueError("aivs_rejected")
    ret = result.get("ret")
    if isinstance(ret, str):
        ret = json.loads(ret)
    if not isinstance(ret, dict) or not isinstance(ret.get("records"), list):
        raise ValueError("invalid_aivs_records")
    records = []
    for record in ret["records"]:
        # The plugin uses case-sensitive User; every other role is a reply/UI item.
        if not isinstance(record, dict) or record.get("speaker") != "User":
            continue
        query, stamp = record.get("content"), record.get("time")
        if not isinstance(query, str) or not query.strip() or type(stamp) is not int or stamp <= 0:
            continue
        records.append({"time": stamp, "query": query.strip(), "answers": [], "source": "mijia_aivs"})
    return sorted(records, key=lambda r: r["time"])


async def fetch_clock_history(io, clock_did, start_ms=None):
    if not clock_did:
        raise ValueError("clock_did_required")
    request = {
        "path": "/api/aivs/device-events",
        "params": {"client_id": AIVS_CLIENT_ID, "did": str(clock_did)},
        "header": {"name": "DialogRecord.FetchByTime"},
        "payload": {"start": int(time.time() * 1000) if start_ms is None else int(start_ms), "pagesize": 10},
        "req_header": {"Content-Type": ["application/json"]},
    }
    return parse_clock_history(await io.miio_request(AIVS_PATH, request))


def _status_value(value, allowed):
    if isinstance(value, dict):
        value = value.get("result")
    if not isinstance(value, list) or len(value) != 1 or type(value[0]) is not int:
        return None
    return value[0] if allowed(value[0]) else None


async def read_clock_status(io):
    devices = await io.device_list(name="full")
    if not isinstance(devices, list):
        raise ValueError("invalid_mi_home_inventory")
    clocks = []
    for device in devices:
        if not isinstance(device, dict) or device.get("model") != CLOCK_MODEL:
            continue
        # Deliberate allowlist: never return did, IP, MAC, token or raw metadata.
        online = device.get("isOnline") if type(device.get("isOnline")) is bool else None
        clock = {"name": str(device.get("name") or "小愛智能鬧鐘"), "model": CLOCK_MODEL,
                 "online": online, "read_only": True, "voice_control_verified": False,
                 "checks": {}}
        clocks.append(clock)
        if online is False:
            clock["status"] = "offline"
            continue
        if not device.get("did"):
            clock["status"] = "missing_cloud_route"
            continue
        for field, method, allowed in (
            ("volume", "get_volume", lambda n: 0 <= n <= 100),
            ("hourly_system", "get_hourly_system", lambda n: n in (12, 24)),
        ):
            try:
                result = await asyncio.wait_for(io.home_request(device["did"], method, []), timeout=15)
                value = _status_value(result, allowed)
                clock["checks"][field] = {"status": "ok", "value": value} if value is not None else {"status": "unexpected_shape"}
            except Exception as e:
                clock["checks"][field] = {"status": "error", "error_type": type(e).__name__}
        clock["status"] = "read_only_verified" if all(c["status"] == "ok" for c in clock["checks"].values()) else "read_only_incomplete"
    return {"ok": True, "model": CLOCK_MODEL, "clock_count": len(clocks),
            "clocks": clocks, "voice_control_verified": False,
            "msg": "僅讀取鬧鐘狀態；語音控制 HA 與 TTS 尚未驗證"}

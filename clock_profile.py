"""AI01ZM / zimi.clock.myk01 legacy miIO READ-ONLY status profile.

RPC names are documented by python-miio's zimi/clock/alarmclock driver.
No MiNA identifier mapping, speech RPC or alarm modification is inferred.
"""
import asyncio

from xiaoai_compat import CLOCK_MODEL


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

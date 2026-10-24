#!/usr/bin/env python3
"""Read-only cloud probes. No HA actions, TTS, raw payloads or transcripts."""
import argparse
import asyncio
import hashlib
import json
import logging
import secrets
import time
from pathlib import Path

import aiohttp
import yaml
from miservice import MiNAService, MiIOService
from xiaoai_compat import (CLOCK_MODEL, select_target,
                           fetch_mina_records, parse_http_records, MiAccount)

HTTP_URL = "https://userprofile.mina.mi.com/device_profile/v2/conversation"


async def diagnose(args):
    # Disable dependency logs before any authentication operation.
    logging.disable(logging.CRITICAL)
    config = yaml.safe_load(Path(args.config).read_text()) or {}
    cfg = config.get("xiaomi", {})
    token_file = Path(args.config).parent / ".mi.token"
    if not token_file.exists():
        return {"status": "login_required", "hardware_verified": False}
    token = json.loads(token_file.read_text())
    salt = secrets.token_bytes(16)

    def fingerprint(value):
        return hashlib.sha256(salt + str(value).encode()).hexdigest()[:12]

    def safe_label(value):
        import re
        value = str(value or "")
        return value if re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", value) else "unknown"

    def inventory(devices):
        rows = []
        for d in devices:
            row = {"ref": fingerprint(d.get("deviceID") or d.get("did")),
                   "hardware": safe_label(d.get("hardware")),
                   "model": safe_label(d.get("model")),
                   "clock_model_match": d.get("model") == CLOCK_MODEL}
            if args.local_ids:
                row["deviceID_local_only"] = d.get("deviceID")
                row["did_local_only"] = d.get("did")
            rows.append(row)
        return rows

    report = {"status": "experimental_unverified", "hardware_verified": False,
              "contains_local_ids": args.local_ids, "probes": {}}

    async def probe(name, action):
        try:
            result = await asyncio.wait_for(action(), timeout=25)
            report["probes"][name] = {"status": "ok"}
            return result
        except Exception as e:
            report["probes"][name] = {"status": "error", "error_type": type(e).__name__}
            # Only locally defined enums may cross the diagnostic boundary.
            reason = str(e)
            if reason in {"mina_gateway_rejected", "mina_ubus_rejected", "invalid_mina_result",
                          "invalid_mina_answers", "conversation_api_rejected",
                          "invalid_conversation_response", "invalid_conversation_records",
                          "hardware_required", "login_failed"}:
                report["probes"][name]["reason"] = reason
            if isinstance(e, aiohttp.ClientResponseError):
                report["probes"][name]["http_status"] = e.status
            return None

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        account = MiAccount(session, cfg.get("username", ""), cfg.get("password", ""), None)
        account.token = token
        na = MiNAService(account)
        # Always compare the two views independently; one failure must not hide the other.
        lists = []
        for master in (0, 1):
            devices = await probe(f"mina_master_{master}", lambda m=master: na.device_list(master=m))
            if devices is not None:
                if not isinstance(devices, list):
                    report["probes"][f"mina_master_{master}"] = {"status": "invalid_shape"}
                    continue
                devices = [d for d in devices if isinstance(d, dict)]
                report["probes"][f"mina_master_{master}"]["devices"] = inventory(devices)
                lists.extend(d for d in devices if d.get("deviceID"))
        unique = {str(d["deviceID"]): d for d in lists}
        try:
            target = select_target(list(unique.values()), cfg)
            report["selected_ref"] = fingerprint(target["deviceID"])
        except ValueError:
            target = None
            report["selection"] = "explicit_mina_device_required"

        if args.probe_conversation and target:
            did = str(target["deviceID"])
            now = int(time.time() * 1000)

            async def mina():
                return await fetch_mina_records(na, did)

            async def http():
                hardware = target.get("hardware") or cfg.get("hardware")
                if not hardware:
                    raise ValueError("hardware_required")
                # micoapi token belongs to this service; never substitute xiaomiio tokens.
                if not account.token or "micoapi" not in account.token:
                    if not await account.login("micoapi"):
                        raise RuntimeError("login_failed")
                cookies = {"deviceId": did, "userId": str(account.token["userId"]),
                           "serviceToken": account.token["micoapi"][1]}
                async with session.get(HTTP_URL, params={"source": "dialogu", "hardware": hardware,
                                       "timestamp": now, "limit": 2}, cookies=cookies) as response:
                    response.raise_for_status()
                    return parse_http_records(await response.json())

            for name, action in (("conversation_mina", mina), ("conversation_http", http)):
                records = await probe(name, action)
                if records is not None:
                    stamps = []
                    for record in records:
                        try:
                            stamps.append(int(record.get("time", record.get("timestamp_ms", 0))))
                        except (TypeError, ValueError):
                            pass
                    report["probes"][name].update(
                        record_count=len(records),
                        recent_record_count=sum(now - 120000 <= t <= now + 10000 for t in stamps),
                    )

        if args.miio:
            # Separate SID, optional because it can require another login / region.
            io = MiIOService(account, region=args.region)
            devices = await probe("mi_home", io.device_list)
            if isinstance(devices, list):
                report["probes"]["mi_home"]["devices"] = inventory(
                    [d for d in devices if isinstance(d, dict) and d.get("model") == CLOCK_MODEL])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--miio", action="store_true", help="Also query Mi Home (xiaomiio SID)")
    parser.add_argument("--region", choices=["cn", "de", "i2", "ru", "sg", "us"], default="cn")
    parser.add_argument("--probe-conversation", action="store_true")
    parser.add_argument("--local-ids", action="store_true", help="LOCAL ONLY: expose IDs for configuration")
    args = parser.parse_args()
    try:
        report = asyncio.run(diagnose(args))
    except Exception as e:
        report = {"status": "error", "error_type": type(e).__name__, "hardware_verified": False}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "experimental_unverified" else 2


if __name__ == "__main__":
    raise SystemExit(main())

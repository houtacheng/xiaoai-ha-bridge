import asyncio
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xiaoai_compat import (discover_devices, select_target, conversation_api,
                           parse_http_records, normalize_mina_messages,
                           SafeLogFilter, remember_secrets, public_devices)
from xiaoai_compat import parse_mina_result, fetch_mina_records
from xiaoai_compat import MiAccount, require_ubus_success


class ClockTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_merges_without_converting_mi_home_did(self):
        na = AsyncMock()
        na.device_list.side_effect = [[{"deviceID": "speaker"}],
                                     [{"deviceID": "clock", "did": "123"}, {"deviceID": "speaker"}]]
        devices = await discover_devices(na, {"discovery_all": True})
        self.assertEqual(len(devices), 2)
        self.assertEqual(select_target(devices, {"device_did": "123"})["deviceID"], "clock")
        self.assertEqual(na.device_list.call_args.kwargs, {"master": 1})

    async def test_expanded_discovery_opt_in(self):
        na = AsyncMock()
        na.device_list.return_value = []
        self.assertEqual(await discover_devices(na, {}), [])
        na.device_list.assert_awaited_once_with()

    def test_missing_target_never_falls_back(self):
        for cfg in ({"device_did": "missing"}, {"device_id": "mi-home-id"}, {}):
            devices = [{"deviceID": "speaker"}, {"deviceID": "other"}]
            with self.assertRaises(ValueError):
                select_target(devices, cfg)

    def test_manual_target_requires_explicit_opt_in_and_api(self):
        cfg = {"device_id": "known-mina-id", "allow_unlisted_device": True}
        with self.assertRaises(ValueError):
            select_target([], cfg)
        cfg["conversation_api"] = "mina"
        self.assertEqual(select_target([], cfg)["deviceID"], "known-mina-id")
        cfg["conversation_api"] = "http"
        with self.assertRaises(ValueError):
            select_target([], cfg)

    def test_clock_is_not_assigned_fabricated_hardware(self):
        self.assertEqual(conversation_api({"conversation_api": "mina"}, "AI01ZM"), "mina")
        self.assertEqual(conversation_api({}, "M01"), "mina")
        self.assertEqual(conversation_api({}, "L06A"), "http")
        with self.assertRaises(ValueError):
            conversation_api({"conversation_api": "guess"}, "")

    def test_http_response_formats_and_rejection(self):
        expected = [{"time": 123, "query": "test"}]
        for data in ({"records": expected}, json.dumps({"records": expected})):
            self.assertEqual(parse_http_records({"code": 0, "data": data}), expected)
        self.assertEqual(parse_http_records({"data": None}), [])
        for data in ({"code": 401}, {"data": {"records": {}}}, []):
            with self.assertRaises(ValueError):
                parse_http_records(data)

    def test_mina_normalization(self):
        msg = {"timestamp_ms": 123, "response": {"answer": [{"question": "test"}]}}
        records = normalize_mina_messages([msg])
        self.assertEqual(records[0]["query"], "test")
        self.assertEqual(records[0]["time"], 123)

    async def test_raw_mina_multiple_answers_and_rejections(self):
        nlp = {"meta": {"timestamp": "123"}, "response": {"answer": [
            {"intention": {"query": "test"}}, {"content": {"to_speak": "test"}}]}}
        payload = {"code": 0, "data": {"code": 0, "info": json.dumps({"result": [{"nlp": json.dumps(nlp)}]})}}
        na = AsyncMock()
        na.ubus_request.return_value = payload
        self.assertEqual((await fetch_mina_records(na, "clock"))[0]["query"], "test")
        na.ubus_request.assert_awaited_once_with("clock", "nlp_result_get", "mibrain", {})
        for bad in ({"code": 401}, {"data": {"code": -1}}, {"data": {"code": 0, "info": {}}}):
            with self.assertRaises(ValueError):
                parse_mina_result(bad)
        self.assertEqual(parse_mina_result({"data": {"code": 0, "info": {"result": []}}}), [])

    def test_device_payload_allowlist(self):
        self.assertEqual(public_devices([{"deviceID": "x", "token": "secret", "other": {"passToken": "secret"}}]), [{"deviceID": "x"}])

    def test_logs_strip_known_secrets_dependency_payloads_and_tracebacks(self):
        remember_secrets({"api_key": "synthetic-api-secret", "micoapi": ["synthetic-security", "synthetic-service"]})
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(SafeLogFilter())
        logger = logging.getLogger("clock-test")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        logger.error("key=%s token=%s password='unknown-secret'", "synthetic-api-secret", "synthetic-service")
        logger.error("failed: %s", RuntimeError("raw-response-secret"), exc_info=(RuntimeError, RuntimeError("trace-secret"), None))
        dep_record = logging.LogRecord("miservice.miaccount", logging.ERROR, "", 1, "raw-login-secret", (), None)
        handler.handle(dep_record)
        output = stream.getvalue()
        for secret in ("synthetic-api-secret", "synthetic-service", "unknown-secret", "raw-response-secret", "trace-secret", "raw-login-secret"):
            self.assertNotIn(secret, output)
        self.assertIn("RuntimeError", output)

    async def test_bridge_http_401_and_dict_payload(self):
        import bridge
        session = AsyncMock()
        response = AsyncMock()
        response.status = 401
        session.get.return_value = response
        self.assertEqual(await bridge._get_latest_ask_from_xiaoai(session, "clock", "observed", 123), ([], 123, True))
        response.status = 200
        response.json.return_value = {"data": {"records": [{"time": 123, "query": "test"}]}}
        records, _, expired = await bridge._get_latest_ask_from_xiaoai(session, "clock", "observed", 123)
        self.assertEqual(len(records), 1)
        self.assertFalse(expired)

    async def test_cookie_mask_round_trip(self):
        import bridge
        with patch.object(bridge, "load_config", return_value={"xiaomi": {"cookie_text": "serviceToken=synthetic"}}):
            masked = await bridge.get_config()
        self.assertEqual(masked["xiaomi"]["cookie_text"], "••••••••")
        with patch.object(bridge, "load_config", return_value={"xiaomi": {"cookie_text": "serviceToken=synthetic"}}), patch.object(bridge, "save_config") as save:
            await bridge.post_config(bridge.SaveConfigRequest(config=masked))
            self.assertEqual(save.call_args.args[0]["xiaomi"]["cookie_text"], "serviceToken=synthetic")

    async def test_login_keeps_tls_verification_enabled(self):
        account = object.__new__(MiAccount)
        account.ua = MagicMock(random="test-agent")
        account.token = {"deviceId": "test-device"}
        account.session = MagicMock()
        response = AsyncMock()
        response.read.return_value = b'&&&START&&&{"code":0}'
        account.session.request.return_value.__aenter__.return_value = response
        self.assertEqual(await account._serviceLogin("serviceLogin?sid=micoapi"), {"code": 0})
        self.assertIs(account.session.request.call_args.kwargs["ssl"], True)

    def test_tts_acceptance_requires_success_codes(self):
        require_ubus_success({"code": 0, "data": {"code": 0}})
        for payload in (None, {"code": 0}, {"data": {"code": -1}}, {"code": 401}):
            with self.assertRaises(ValueError):
                require_ubus_success(payload)

    async def test_tts_endpoint_obeys_selected_clock_and_rejects_missing_target(self):
        import bridge
        from fastapi import HTTPException
        cfg = {"xiaomi": {"device_did": "clock"}}
        na = AsyncMock()
        na.device_list.return_value = [{"deviceID": "speaker"}, {"deviceID": "clock"}]
        na.text_to_speech.return_value = {"code": 0, "data": {"code": 0}}
        with patch.object(bridge, "load_config", return_value=cfg), patch.object(bridge, "_has_xiaomi_credentials", return_value=True), patch.object(bridge, "MiAccount"), patch("miservice.MiNAService", return_value=na):
            result = await bridge.tts_speak(bridge.TTSRequest(text="test"))
            self.assertTrue(result["ok"])
            na.text_to_speech.assert_awaited_once_with("clock", "test")
            cfg["xiaomi"]["device_did"] = "missing"
            with self.assertRaises(HTTPException):
                await bridge.tts_speak(bridge.TTSRequest(text="test"))
            self.assertEqual(na.text_to_speech.await_count, 1)

    async def test_diagnostic_report_contains_no_credentials_ids_or_transcripts(self):
        import diagnose_clock
        from argparse import Namespace
        import time
        now = int(time.time() * 1000)
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.yaml"
            config.write_text('xiaomi: {device_did: private-mina-id, conversation_api: mina}')
            (Path(folder) / ".mi.token").write_text(json.dumps({"userId": "private-user", "micoapi": ["private-security", "private-token"]}))
            na = AsyncMock()
            na.device_list.return_value = [{"deviceID": "private-mina-id", "hardware": "observed", "name": "private-name"}]
            na.ubus_request.return_value = {"data": {"code": 0, "info": {"result": [{"nlp": {
                "meta": {"timestamp": now}, "response": {"answer": [{"intention": {"query": "private-transcript"}}]}}}]}}}
            session = MagicMock()
            response = AsyncMock()
            response.raise_for_status = MagicMock()
            response.json.return_value = {"data": {"records": [{"time": now, "query": "private-transcript"}]}}
            session.get.return_value.__aenter__.return_value = response
            context = MagicMock()
            context.__aenter__.return_value = session
            with patch.object(diagnose_clock.aiohttp, "ClientSession", return_value=context), patch.object(diagnose_clock, "MiNAService", return_value=na), patch.object(diagnose_clock, "MiAccount", return_value=MagicMock()):
                report = await diagnose_clock.diagnose(Namespace(config=str(config), local_ids=False, miio=False, probe_conversation=True))
            logging.disable(logging.NOTSET)
            encoded = json.dumps(report)
            for value in ("private-mina-id", "private-name", "private-user", "private-token", "private-security", "private-transcript"):
                self.assertNotIn(value, encoded)
            self.assertEqual(report["probes"]["conversation_mina"]["recent_record_count"], 1)
            self.assertEqual(report["probes"]["conversation_http"]["record_count"], 1)
            self.assertFalse(report["hardware_verified"])


if __name__ == "__main__":
    unittest.main()

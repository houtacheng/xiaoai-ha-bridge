import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xiaoai_compat import classify_qr_poll, parse_xiaomi_json
import xiaoai_compat


class QRTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import bridge
        self.bridge = bridge
        bridge._qr_state.clear()
        bridge._qr_flow_lock = asyncio.Lock()

    async def asyncTearDown(self):
        await self.bridge._clear_qr_state()

    def test_json_prefix_whitespace_bom_and_invalid_types(self):
        for value in (b' {"code":0}', b'\xef\xbb\xbf \n&&&START&&& {"code":0}', ' \n&&&START&&&{"code":0}'):
            self.assertEqual(parse_xiaomi_json(value), {"code": 0})
        for value in (b'[]', b'<html>private</html>', b''):
            with self.assertRaises(ValueError):
                parse_xiaomi_json(value)

    def test_waiting_responses_are_not_parse_errors(self):
        for status, body in ((204, b''), (408, b'timeout'), (504, b'<html>timeout</html>'), (200, b' \n')):
            state, credentials = classify_qr_poll(status, body)
            self.assertTrue(state['ok'])
            self.assertFalse(state['done'])
            self.assertIsNone(credentials)

    def test_expired_rate_limit_and_non_json_expose_no_payload(self):
        for status in (401, 403, 404, 410):
            state, _ = classify_qr_poll(status, b'private-session')
            self.assertTrue(state['terminal'])
            self.assertNotIn('private-session', json.dumps(state))
        for status, body in ((200, b'<html>serviceToken=private-secret</html>'), (429, b'private-secret'), (502, b'private-secret')):
            state, credentials = classify_qr_poll(status, body)
            self.assertFalse(state['terminal'])
            self.assertIsNone(credentials)
            self.assertNotIn('private-secret', json.dumps(state))

    def test_success_payload_is_separate_from_public_state(self):
        private = {'psecurity': 'private-security', 'userId': 'private-user', 'passToken': 'private-pass'}
        state, credentials = classify_qr_poll(200, json.dumps(private).encode())
        self.assertEqual(credentials, private)
        self.assertNotIn('private-', json.dumps(state))
        state, credentials = classify_qr_poll(200, b'{"userId":"private-user"}')
        self.assertTrue(state['terminal'])
        self.assertIsNone(credentials)

    def session(self, response):
        session = MagicMock()
        session.closed = False
        session.close = AsyncMock()
        session.get.return_value.__aenter__.return_value = response
        return session

    async def test_poll_timeout_retains_session_and_credentials(self):
        b = self.bridge
        session = self.session(AsyncMock())
        session.get.return_value.__aenter__.side_effect = asyncio.TimeoutError()
        b._qr_state.update(ready=True, session=session, lp_url='https://example.invalid/private', deadline=time.monotonic()+180)
        with patch.object(b, '_finish_qr_login') as finish:
            result = await b.qr_login_poll()
            self.assertTrue(result['ok'])
            finish.assert_not_called()
            session.close.assert_not_awaited()

    async def test_poll_single_flight(self):
        b = self.bridge
        await b._qr_flow_lock.acquire()
        try:
            result = await b.qr_login_poll()
            self.assertTrue(result['ok'])
            self.assertFalse(result['done'])
        finally:
            b._qr_flow_lock.release()

    async def test_status_identifies_received_scan_without_disclosing_it(self):
        b = self.bridge
        b._qr_state.update(ready=True, stage='exchanging_micoapi', pending_scan={'passToken':'private-pass'}, lp_url='private-url', deadline=time.monotonic()+100)
        state = await b.qr_login_status()
        self.assertTrue(state['scan_received'])
        self.assertEqual(state['stage'], 'exchanging_micoapi')
        self.assertNotIn('private-', json.dumps(state))
        await b._qr_flow_lock.acquire()
        try:
            waiting = await b.qr_login_poll()
            self.assertIn('已收到扫码', waiting['msg'])
        finally:
            b._qr_flow_lock.release()

    async def test_passport_exchange_uses_clean_cookie_jar_and_retains_other_sids(self):
        parent = xiaoai_compat.MiAccount(MagicMock(), '', '', None)
        original = {'userId':'test-user', 'passToken':'test-pass', 'deviceId':'test-device', 'xiaomiio':['io-security','io-token']}
        parent.token = original.copy()
        isolated_session = MagicMock()
        context = MagicMock()
        context.__aenter__.return_value = isolated_session
        async def login(account, sid):
            self.assertIs(account.session, isolated_session)
            self.assertNotIn('xiaomiio', account.token)
            account.token[sid] = ['mina-security','mina-token']
            return True
        with patch.object(xiaoai_compat.aiohttp, 'ClientSession', return_value=context), patch.object(xiaoai_compat._MiAccount, 'login', new=AsyncMock(side_effect=login)):
            self.assertTrue(await parent.login('micoapi'))
        self.assertEqual(parent.token['xiaomiio'], original['xiaomiio'])
        self.assertEqual(parent.token['micoapi'], ['mina-security','mina-token'])

    async def test_passport_exchange_failure_preserves_existing_credentials(self):
        parent = xiaoai_compat.MiAccount(MagicMock(), '', '', None)
        parent.token = {'userId':'test-user','passToken':'test-pass','deviceId':'test-device','micoapi':['old-security','old-token']}
        original = parent.token.copy()
        parent.token_store = MagicMock()
        context = MagicMock()
        with patch.object(xiaoai_compat.aiohttp, 'ClientSession', return_value=context), patch.object(xiaoai_compat._MiAccount, 'login', new=AsyncMock(return_value=False)):
            self.assertFalse(await parent.login('micoapi'))
        self.assertEqual(parent.token, original)
        parent.token_store.save_token.assert_not_called()

    async def test_new_qr_preserves_cookie_session_and_closes_previous(self):
        b = self.bridge
        previous = self.session(AsyncMock())
        b._qr_state['session'] = previous
        entry = AsyncMock()
        entry.raise_for_status = MagicMock()
        entry.read.return_value = b' \n&&&START&&&{"code":70016,"location":"https://account.xiaomi.com/pass/auth?sid=mijia"}'
        qr = AsyncMock()
        qr.raise_for_status = MagicMock()
        qr.read.return_value = b'{"qr":"https://account.xiaomi.com/qr/private","lp":"https://account.xiaomi.com/lp/private","timeout":120}'
        session = self.session(entry)
        contexts = [MagicMock(), MagicMock()]
        contexts[0].__aenter__.return_value = entry
        contexts[1].__aenter__.return_value = qr
        session.get.side_effect = contexts
        with patch.object(b.aiohttp, 'ClientSession', return_value=session):
            result = await b.qr_login_start()
            self.assertTrue(result['ok'])
            self.assertIs(b._qr_state['session'], session)
            session.close.assert_not_awaited()
            previous.close.assert_awaited_once()
            self.assertNotIn('lp_url', result)
            self.assertNotIn('device_id', result)

    async def test_expired_session_is_closed(self):
        b = self.bridge
        session = self.session(AsyncMock())
        b._qr_state.update(ready=True, session=session, deadline=0)
        result = await b.qr_login_poll()
        self.assertTrue(result['terminal'])
        session.close.assert_awaited_once()
        self.assertFalse(b._qr_state)

    async def test_failed_micoapi_exchange_does_not_touch_files(self):
        b = self.bridge
        scan = {'userId': 'new-user', 'passToken': 'new-pass'}
        b._qr_state['device_id'] = 'new-device'
        account = MagicMock()
        account.login = AsyncMock(return_value=False)
        with patch.object(b, 'MiAccount', return_value=account), patch.object(b, 'load_config') as load, patch.object(b, 'save_config') as save:
            with self.assertRaises(ValueError):
                await b._finish_qr_login(self.session(AsyncMock()), scan)
            load.assert_not_called()
            save.assert_not_called()

    async def test_success_uses_micoapi_pair_and_keeps_existing_rules(self):
        b = self.bridge
        with tempfile.TemporaryDirectory() as folder:
            paths = {name: Path(folder)/filename for name, filename in [('AUTH_PATH','auth.json'),('TOKEN_PATH','.mi.token'),('CONFIG_PATH','config.yaml')]}
            for path in paths.values():
                path.write_bytes(b'original')
            account = MagicMock()
            async def login(sid):
                self.assertEqual(sid, 'micoapi')
                account.token.update(micoapi=['correct-security','correct-mina-token'])
                return True
            account.login = AsyncMock(side_effect=login)
            b._qr_state['device_id'] = 'new-device'
            saved = []
            with patch.multiple(b, **paths), patch.object(b, 'MiAccount', return_value=account), patch.object(b, 'load_config', return_value={'intent_rules':[{'test':'retained'}]}), patch.object(b, 'save_config', side_effect=lambda cfg:saved.append(cfg)):
                await b._finish_qr_login(self.session(AsyncMock()), {'userId':'new-user','passToken':'new-pass','serviceToken':'wrong-mijia-token'})
                token = json.loads(paths['TOKEN_PATH'].read_text())
                self.assertEqual(token['micoapi'], ['correct-security','correct-mina-token'])
                self.assertNotIn('wrong-mijia-token', paths['TOKEN_PATH'].read_text())
                self.assertEqual(saved[0]['intent_rules'], [{'test':'retained'}])

    async def test_persistence_failure_restores_all_original_files(self):
        b = self.bridge
        with tempfile.TemporaryDirectory() as folder:
            paths = {name: Path(folder)/filename for name, filename in [('AUTH_PATH','auth.json'),('TOKEN_PATH','.mi.token'),('CONFIG_PATH','config.yaml')]}
            for path in paths.values():
                path.write_bytes(b'original')
            account = MagicMock()
            async def login(sid):
                account.token['micoapi'] = ['security','token']
                return True
            account.login = AsyncMock(side_effect=login)
            b._qr_state['device_id'] = 'new-device'
            with patch.multiple(b, **paths), patch.object(b, 'MiAccount', return_value=account), patch.object(b, 'load_config', return_value={}), patch.object(b, 'save_config', side_effect=OSError('private-response')):
                with self.assertRaises(OSError):
                    await b._finish_qr_login(self.session(AsyncMock()), {'userId':'new-user','passToken':'new-pass'})
                self.assertTrue(all(p.read_bytes()==b'original' for p in paths.values()))
                self.assertFalse(list(Path(folder).glob('*.qr-pending')))

    async def test_success_closes_session_and_never_returns_scan_secrets(self):
        b = self.bridge
        scan = {'userId':'private-user','passToken':'private-pass','psecurity':'private-security'}
        response = AsyncMock()
        response.status = 200
        response.read.return_value = json.dumps(scan).encode()
        session = self.session(response)
        b._qr_state.update(ready=True,session=session,lp_url='https://example.invalid',device_id='private-device',deadline=time.monotonic()+180)
        with patch.object(b, '_finish_qr_login', new=AsyncMock()) as finish:
            result = await b.qr_login_poll()
            self.assertTrue(result['done'])
            finish.assert_awaited_once()
            session.close.assert_awaited_once()
            self.assertNotIn('private-', json.dumps(result))

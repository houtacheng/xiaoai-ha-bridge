import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clock_profile import read_clock_status


class ClockProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_model_and_only_documented_reads_no_identifiers(self):
        io = AsyncMock()
        io.device_list.return_value = [
            {'model':'zimi.clock.myk01','did':'private-clock','isOnline':True,'name':'Clock','token':'private-token','localip':'private-ip'},
            {'model':'zimi.clock.myk01','did':'private-offline','isOnline':False},
            {'model':'other.speaker','did':'private-other','isOnline':True},
        ]
        io.home_request.side_effect = [[5], {'result':[12]}]
        report = await read_clock_status(io)
        self.assertEqual(report['clock_count'], 2)
        self.assertEqual(report['clocks'][0]['status'], 'read_only_verified')
        self.assertEqual(report['clocks'][1]['status'], 'offline')
        self.assertFalse(report['voice_control_verified'])
        io.home_request.assert_has_awaits([call('private-clock','get_volume',[]),call('private-clock','get_hourly_system',[])])
        self.assertEqual(io.home_request.await_count, 2)
        encoded = json.dumps(report)
        for private in ('private-clock','private-token','private-ip','private-offline','private-other'):
            self.assertNotIn(private, encoded)

    async def test_invalid_values_and_exception_bodies_are_not_exposed(self):
        io = AsyncMock()
        io.device_list.return_value = [{'model':'zimi.clock.myk01','did':'private-id','isOnline':True}]
        io.home_request.side_effect = [[{'token':'private-body'}], RuntimeError('private-error-body')]
        report = await read_clock_status(io)
        self.assertEqual(report['clocks'][0]['status'], 'read_only_incomplete')
        self.assertEqual(report['clocks'][0]['checks']['volume']['status'], 'unexpected_shape')
        self.assertNotIn('private-', json.dumps(report))

    async def test_missing_cloud_route_never_sends_rpc(self):
        io = AsyncMock()
        io.device_list.return_value = [{'model':'zimi.clock.myk01','isOnline':True}]
        report = await read_clock_status(io)
        self.assertEqual(report['clocks'][0]['status'], 'missing_cloud_route')
        io.home_request.assert_not_awaited()

    async def test_endpoint_uses_no_token_store_and_returns_read_only_profile(self):
        import bridge
        io = AsyncMock()
        io.device_list.return_value = []
        with patch.object(bridge,'load_config',return_value={'xiaomi':{}}), patch.object(bridge,'_has_xiaomi_credentials',return_value=True), patch.object(bridge,'_set_token'), patch.object(bridge,'MiAccount',return_value=MagicMock()) as account, patch('miservice.MiIOService',return_value=io):
            result = await bridge.clock_diagnostics()
        self.assertTrue(result['ok'])
        self.assertEqual(result['clock_count'], 0)
        self.assertIsNone(account.call_args.args[-1])
        io.device_list.assert_awaited_once_with(name='full')

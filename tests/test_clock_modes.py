import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge


class ClockModeTests(unittest.IsolatedAsyncioTestCase):
    def config(self):
        return {'xiaomi':{'conversation_api':'mijia_aivs','clock_did':'private-clock',
                         'clock_bridge_dry_run':True,'clock_bridge_test_only':True,
                         'clock_test_entity':'input_boolean.xiaoai_ai01zm_bridge_test_20261024'},
                'homeassistant':{'url':'http://test.invalid','token':'private-token'},
                'intent_rules':[{'pattern':'retained-rule'}]}

    async def test_actual_helper_read_strips_attributes_and_credentials(self):
        cfg=self.config();response=AsyncMock();response.status=200
        response.json.return_value={'entity_id':cfg['xiaomi']['clock_test_entity'],'state':'on','attributes':{'token':'private-extra'}}
        session=MagicMock();session.get.return_value.__aenter__.return_value=response
        context=MagicMock();context.__aenter__.return_value=session
        with patch.object(bridge.aiohttp,'ClientSession',return_value=context):
            state=await bridge._clock_helper_state(cfg)
        self.assertEqual(state,'on')
        self.assertNotIn('private-',state)

    async def test_helper_scope_is_checked_before_any_network_call(self):
        cfg=self.config();cfg['xiaomi']['clock_test_entity']='light.real_device'
        with patch.object(bridge.aiohttp,'ClientSession') as session:
            self.assertIsNone(await bridge._clock_helper_state(cfg))
        session.assert_not_called()

    async def test_report_shows_active_receive_only_mode_and_real_state(self):
        cfg=self.config()
        with patch.object(bridge,'load_config',return_value=cfg), patch.object(bridge,'_clock_helper_state',new=AsyncMock(return_value='off')), patch.dict(bridge.bridge_state,{'running':True,'clock_profile':{'dry_run':True,'test_only':True,'new_voice_count':3,'ha_test_count':0}},clear=True):
            result=await bridge.clock_test_state()
        self.assertEqual(result['mode'],'receive_only')
        self.assertEqual(result['helper_state'],'off')
        self.assertEqual(result['new_voice_count'],3)
        self.assertNotIn('private-',json.dumps(result))

    async def test_enabling_helper_mode_keeps_rules_and_never_enables_physical_scope(self):
        cfg=self.config();original=copy.deepcopy(cfg['intent_rules'])
        with patch.object(bridge,'load_config',return_value=cfg), patch.object(bridge,'_clock_helper_state',new=AsyncMock(return_value='off')), patch.object(bridge,'_restart_clock_configuration',new=AsyncMock()) as restart, patch.object(bridge,'_wait_clock_test_ready',new=AsyncMock(return_value=True)):
            result=await bridge.start_clock_helper_test()
        self.assertTrue(result['ok'])
        saved=restart.call_args.args[0]
        self.assertFalse(saved['xiaomi']['clock_bridge_dry_run'])
        self.assertTrue(saved['xiaomi']['clock_bridge_test_only'])
        self.assertEqual(saved['intent_rules'],original)
        self.assertEqual(saved['xiaomi']['clock_did'],'private-clock')

    async def test_unavailable_helper_does_not_change_mode(self):
        cfg=self.config()
        with patch.object(bridge,'load_config',return_value=cfg), patch.object(bridge,'_clock_helper_state',new=AsyncMock(return_value=None)), patch.object(bridge,'_restart_clock_configuration',new=AsyncMock()) as restart:
            result=await bridge.start_clock_helper_test()
        self.assertFalse(result['ok'])
        self.assertTrue(cfg['xiaomi']['clock_bridge_dry_run'])
        restart.assert_not_awaited()

    async def test_wait_does_not_report_ready_while_dry_run_is_active(self):
        with patch.dict(bridge.bridge_state,{'running':True,'connected':True,'clock_profile':{'dry_run':True,'test_only':True}},clear=True), patch.object(bridge.asyncio,'sleep',new=AsyncMock()):
            self.assertFalse(await bridge._wait_clock_test_ready())

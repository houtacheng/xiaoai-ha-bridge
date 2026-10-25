import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clock_profile import select_clock, parse_clock_history, fetch_clock_history


class ClockHistoryTests(unittest.IsolatedAsyncioTestCase):
    def test_target_pinned_exact_model_and_never_fallback(self):
        devices=[{'model':'zimi.clock.myk01','did':'clock','isOnline':True},
                 {'model':'zimi.clock.myk01','did':'offline','isOnline':False},
                 {'model':'other.speaker','did':'speaker','isOnline':True}]
        self.assertEqual(select_clock(devices)['did'],'clock')
        for selected in ('missing','offline','speaker'):
            with self.assertRaises(ValueError):select_clock(devices,selected)
        devices.append({'model':'zimi.clock.myk01','did':'second','isOnline':True})
        with self.assertRaises(ValueError):select_clock(devices)

    def test_only_user_text_with_millisecond_timestamps_is_executable(self):
        raw={'ret':{'records':[
            {'speaker':'User','content':' test two ','time':2000},
            {'speaker':'Assistant','content':'do not execute','time':3000},
            {'speaker':'user','content':'wrong role','time':4000},
            {'speaker':'User','widget':'private','content':'','time':5000},
            {'speaker':'User','content':'wrong time','time':True},
            {'speaker':'User','content':'test one','time':1000}]}}
        records=parse_clock_history(json.dumps(raw))
        self.assertEqual([r['query'] for r in records],['test one','test two'])
        self.assertTrue(all(r['source']=='mijia_aivs' for r in records))

    def test_rejection_and_invalid_payloads_never_embed_bodies(self):
        for raw in ({'code':401,'message':'private-secret'}, {'ret':{'records':{}}}, [], {'ret':None}):
            with self.assertRaises(ValueError) as error:parse_clock_history(raw)
            self.assertNotIn('private-secret',str(error.exception))

    async def test_request_is_the_plugin_read_operation_with_explicit_mi_home_route(self):
        io=AsyncMock()
        io.miio_request.return_value={'ret':{'records':[]}}
        self.assertEqual(await fetch_clock_history(io,'clock-did',1234567890000),[])
        endpoint,request=io.miio_request.call_args.args
        self.assertEqual(endpoint,'/v2/api/aivs')
        self.assertEqual(request['header'],{'name':'DialogRecord.FetchByTime'})
        self.assertEqual(request['path'],'/api/aivs/device-events')
        self.assertEqual(request['params']['did'],'clock-did')
        self.assertEqual(request['payload'],{'start':1234567890000,'pagesize':10})

    async def test_bridge_dry_run_skips_history_replies_future_and_duplicate_records(self):
        import bridge
        import clock_profile
        now=1700000000000
        cfg={'xiaomi':{'conversation_api':'mijia_aivs','clock_bridge_dry_run':True},
             'homeassistant':{},'intent_rules':[],'poll_interval_seconds':2}
        io=AsyncMock()
        io.device_list.return_value=[{'model':'zimi.clock.myk01','did':'clock','isOnline':True}]
        calls=0
        async def fetch(endpoint,request):
            nonlocal calls
            calls+=1
            if calls>=3:bridge.bridge_state['running']=False
            return {'ret':{'records':[
                {'speaker':'User','content':'old control','time':now-10},
                {'speaker':'User','content':'new test','time':now+1},
                {'speaker':'Assistant','content':'reply is not input','time':now+2},
                {'speaker':'User','content':'future control','time':now+60000}]}}
        io.miio_request.side_effect=fetch
        ha=MagicMock()
        ha.test_connection=AsyncMock()
        ha.call_service=AsyncMock()
        account=MagicMock()
        account.login=AsyncMock(return_value=True)
        with tempfile.TemporaryDirectory() as folder:
            paths={name:Path(folder)/file for name,file in [('CONFIG_PATH','config.yaml'),('TOKEN_PATH','.mi.token'),('AUTH_PATH','auth.json')]}
            with patch.multiple(bridge,**paths), patch.object(bridge,'load_config',return_value=cfg), patch.object(bridge,'_has_xiaomi_credentials',return_value=True), patch.object(bridge,'_set_token'), patch.object(bridge,'MiAccount',return_value=account), patch.object(bridge,'HAClient',return_value=ha), patch('miservice.MiIOService',return_value=io), patch.object(bridge.time,'time',return_value=now/1000), patch.object(bridge.asyncio,'sleep',new=AsyncMock()):
                bridge.bridge_state['running']=True
                await bridge.bridge_loop()
            self.assertEqual(bridge.bridge_state['clock_profile']['new_voice_count'],1)
            self.assertEqual(json.loads((Path(folder)/'last_timestamp.json').read_text()),{'aivs:clock':now+1})
        ha.test_connection.assert_not_awaited()
        ha.call_service.assert_not_awaited()

    async def test_no_speaker_rpc_for_clock_without_verified_tts(self):
        import bridge
        self.assertFalse(await bridge._speak(None,'aivs:clock','test',interrupt=True))

    async def test_test_mode_only_operates_its_virtual_helper(self):
        import bridge
        now=1700000000000
        entity='input_boolean.xiaoai_ai01zm_bridge_test_20261024'
        cfg={'xiaomi':{'conversation_api':'mijia_aivs','clock_bridge_dry_run':False,'clock_bridge_test_only':True,'clock_test_entity':entity},
             'homeassistant':{'url':'http://test.invalid','token':'synthetic-ha'},'intent_rules':[], 'poll_interval_seconds':2}
        io=AsyncMock()
        io.device_list.return_value=[{'model':'zimi.clock.myk01','did':'clock','isOnline':True}]
        calls=0
        async def fetch(*args):
            nonlocal calls
            calls+=1
            if calls>=2:bridge.bridge_state['running']=False
            return {'ret':{'records':[
                {'speaker':'User','content':'打开桥接测试','time':now-1},
                {'speaker':'User','content':'打开测试开关','time':now+1},
                {'speaker':'User','content':'打开实际设备','time':now+2},
                {'speaker':'User','content':'关闭测试开关','time':now+3},
                {'speaker':'Assistant','content':'打开测试开关','time':now+4}]}}
        io.miio_request.side_effect=fetch
        account=MagicMock();account.login=AsyncMock(return_value=True)
        ha=MagicMock();ha.test_connection=AsyncMock(return_value=True);ha.call_service=AsyncMock(return_value=True)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(bridge,'CONFIG_PATH',Path(folder)/'config.yaml'), patch.object(bridge,'load_config',return_value=cfg), patch.object(bridge,'_has_xiaomi_credentials',return_value=True), patch.object(bridge,'_set_token'), patch.object(bridge,'MiAccount',return_value=account), patch.object(bridge,'HAClient',return_value=ha), patch('miservice.MiIOService',return_value=io), patch.object(bridge.time,'time',return_value=now/1000), patch.object(bridge.asyncio,'sleep',new=AsyncMock()):
                bridge.bridge_state['running']=True
                await bridge.bridge_loop()
        self.assertEqual(ha.call_service.await_count,2)
        self.assertEqual([c.args[:3] for c in ha.call_service.call_args_list],[('input_boolean','turn_on',{'entity_id':entity}),('input_boolean','turn_off',{'entity_id':entity})])
        self.assertEqual(bridge.bridge_state['clock_profile']['ha_test_count'],2)

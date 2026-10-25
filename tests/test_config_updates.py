import copy
import unittest
from config_updates import config_revision, merge_update

class ConfigUpdateTests(unittest.TestCase):
    def setUp(self):
        self.cfg={'intent_rules':[{'pattern':'开风扇','action':{'entity_id':'switch.fan'}}],
                  'device_aliases':{'switch.fan':'風扇'},'homeassistant':{'token':'private'},
                  'xiaomi':{'clock_bridge_dry_run':False,'clock_bridge_test_only':False,'clock_did':'private','tts_reply':False}}

    def test_old_browser_without_revision_cannot_overwrite(self):
        with self.assertRaisesRegex(ValueError,'stale_config'):
            merge_update(self.cfg,{'intent_rules':[]},'rules','')

    def test_stale_rules_editor_cannot_remove_new_rules(self):
        revision=config_revision(self.cfg);new=copy.deepcopy(self.cfg)
        new['intent_rules'].append({'pattern':'关风扇','action':{}})
        with self.assertRaisesRegex(ValueError,'stale_config'):
            merge_update(new,self.cfg,'rules',revision)

    def test_rule_save_preserves_aliases_secrets_and_clock_mode(self):
        submitted={'intent_rules':[{'pattern':'关闭暖气','action':{}}],
                   'device_aliases':{},'xiaomi':{'clock_bridge_dry_run':True},'homeassistant':{}}
        updated=merge_update(self.cfg,submitted,'rules',config_revision(self.cfg))
        self.assertEqual(updated['device_aliases'],self.cfg['device_aliases'])
        self.assertEqual(updated['xiaomi'],self.cfg['xiaomi'])
        self.assertEqual(updated['homeassistant'],self.cfg['homeassistant'])

    def test_xiaomi_save_preserves_hidden_mode_and_target(self):
        updated=merge_update(self.cfg,{'xiaomi':{'tts_reply':False,'clock_bridge_dry_run':True,'clock_bridge_test_only':True,'clock_did':'wrong'}},'xiaomi',config_revision(self.cfg))
        self.assertEqual(updated,self.cfg)

    def test_blank_invalid_and_empty_matching_rules_rejected(self):
        for pattern in ['', '   ', '(', '.*', '^$']:
            with self.subTest(pattern=pattern),self.assertRaises(ValueError):
                merge_update(self.cfg,{'intent_rules':[{'pattern':pattern}]},'rules',config_revision(self.cfg))

    def test_parser_cannot_execute_legacy_blank_or_invalid_rules(self):
        import bridge
        parser=bridge.IntentParser([{'pattern':p,'action':{'entity_id':'switch.heater'}} for p in ['', ' ', '(', '.*']])
        self.assertIsNone(parser.parse('问天气'))

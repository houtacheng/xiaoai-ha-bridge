"""Reject stale browser saves and limit changes to the page being saved."""
import copy
import hashlib
import json
import re

SECTION_KEYS = {
    'xiaomi': ('xiaomi',), 'ha': ('homeassistant',), 'rules': ('intent_rules',),
    'adv': ('poll_interval_seconds', 'ai_mode', 'openai', 'ai_context_enabled',
            'ai_context_turns', 'ai_clarify_enabled', 'ai_clarify_ttl',
            'ai_device_filter', 'ai_fallback', 'ai_fallback_text',
            'interrupt_native_reply', 'update_repo', 'update_proxy', 'notify', 'web_auth'),
}
XIAOMI_EDITABLE = ('conversation_api', 'discovery_all', 'hardware', 'device_did', 'tts_reply')


def config_revision(cfg):
    data = {k: v for k, v in cfg.items() if not k.startswith('_config_')}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def merge_update(existing, incoming, section, revision):
    if not revision or revision != config_revision(existing):
        raise ValueError('stale_config')
    if section not in SECTION_KEYS:
        raise ValueError('invalid_section')
    merged = copy.deepcopy(existing)
    if section == 'xiaomi':
        mi = merged.setdefault('xiaomi', {})
        submitted = incoming.get('xiaomi') or {}
        for key in XIAOMI_EDITABLE:
            if key in submitted:
                mi[key] = submitted[key]
    else:
        for key in SECTION_KEYS[section]:
            if key in incoming:
                merged[key] = copy.deepcopy(incoming[key])
    if section == 'rules':
        for rule in merged.get('intent_rules') or []:
            pattern = rule.get('pattern', '')
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError('empty_rule')
            try:
                compiled = re.compile(pattern.replace('{num}', r'(\d+)'))
            except re.error:
                raise ValueError('invalid_regex') from None
            if compiled.search(''):
                raise ValueError('empty_matching_rule')
    return merged

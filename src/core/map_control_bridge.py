# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any


def _build_direct_control_call(method_name: str) -> str:
    return f"""
    (function() {{
        const control = window.__WuwaMapControl;
        if (!control || typeof control.{method_name} !== 'function') {{
            return JSON.stringify({{ ok: false, reason: 'map_control_api_missing' }});
        }}
        return JSON.stringify({{ ok: true, data: control.{method_name}() }});
    }})();
    """


def build_map_control_command(command: dict[str, Any]) -> str:
    command_json = json.dumps(command, ensure_ascii=False)
    return f"""
    (function() {{
        try {{
            const control = window.__WuwaMapControl;
            if (!control || typeof control.handleCommand !== 'function') {{
                return JSON.stringify({{ ok: false, reason: 'map_control_api_missing' }});
            }}
            return JSON.stringify(control.handleCommand({command_json}));
        }} catch (e) {{
            return JSON.stringify({{
                ok: false,
                reason: 'map_control_exception',
                name: e && e.name ? String(e.name) : '',
                message: e && e.message ? String(e.message) : String(e || ''),
                stack: e && e.stack ? String(e.stack) : ''
            }});
        }}
    }})();
    """


def build_map_context_query() -> str:
    return _build_direct_control_call("getMapContext")


def build_tile_metadata_snapshot_query() -> str:
    return _build_direct_control_call("getTileMetadataSnapshot")


def build_tile_metadata_update_listener() -> str:
    return """
    (function() {
        if (window.__wuwaTileMetadataBridgeInstalled) {
            return JSON.stringify({ ok: true, data: 'already_installed' });
        }
        window.__wuwaTileMetadataBridgeInstalled = true;
        window.addEventListener('wuwaTileMetadataChanged', function(event) {
            const updatedAt = event && event.detail ? String(event.detail.updatedAt || '') : '';
            if (window.backend && typeof window.backend.notifyTileMetadataChanged === 'function') {
                window.backend.notifyTileMetadataChanged(updatedAt);
            }
        });
        return JSON.stringify({ ok: true, data: 'installed' });
    })();
    """

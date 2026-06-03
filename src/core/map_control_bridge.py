# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any


def build_map_control_command(command: dict[str, Any]) -> str:
    command_json = json.dumps(command, ensure_ascii=False)
    return f"""
    (function() {{
        const control = window.__WuwaMapControl;
        if (!control || typeof control.handleCommand !== 'function') {{
            return JSON.stringify({{ ok: false, reason: 'map_control_api_missing' }});
        }}
        return JSON.stringify(control.handleCommand({command_json}));
    }})();
    """

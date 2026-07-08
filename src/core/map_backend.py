# -*- coding: utf-8 -*-
import json
import base64
from concurrent.futures import ThreadPoolExecutor
import requests

from PySide6.QtCore import QObject, Signal, Slot


class MapBackend(QObject):
    statusUpdated = Signal(float, float, int)
    localMapChangedSignal = Signal(str)
    proxyResponse = Signal(str, int, str, str)
    tileMetadataChangedSignal = Signal(str)
    
    _internalProxyResponse = Signal(str, int, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proxy_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="map-proxy")
        self._internalProxyResponse.connect(self._do_emit_proxy_response)

    def _do_emit_proxy_response(self, req_id, status_code, resp_data, resp_headers_str):
        try:
            print(f"[Proxy] Emitting proxyResponse for {req_id} with status {status_code}")
            self.proxyResponse.emit(req_id, status_code, resp_data, resp_headers_str)
        except Exception as e:
            print(f"[Proxy] Error emitting proxyResponse: {e}")

    @Slot(float, float, int)
    def updateStatus(self, lat, lng, zoom):
        self.statusUpdated.emit(lat, lng, zoom)

    @Slot(str)
    def localMapChanged(self, map_name):
        self.localMapChangedSignal.emit(map_name)

    @Slot(str)
    def notifyTileMetadataChanged(self, updated_at: str):
        self.tileMetadataChangedSignal.emit(str(updated_at or ""))

    @Slot(str, str, str, str, str, str)
    def proxyRequest(self, req_id, method, url, headers_json, body, response_type="text"):
        def run_req():
            try:
                print(f"[Proxy] {method} -> {url}")
                headers = json.loads(headers_json) if headers_json else {}

                if 'User-Agent' not in headers:
                    headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

                request_body = body
                if body and body.startswith('base64:'):
                    try:
                        base64_data = body[7:]
                        request_body = base64.b64decode(base64_data)
                        print(f"[Proxy] Decoded Base64 body, size: {len(request_body)} bytes")
                    except Exception as e:
                        print(f"[Proxy] Base64 decode error: {e}")
                        request_body = body

                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=request_body,
                    timeout=60
                )

                print(f"[Proxy] Response: {response.status_code} for {req_id}")

                header_lines = [f"{k}: {v}" for k, v in response.headers.items()]
                resp_headers_str = "\n".join(header_lines)

                if response_type == 'arraybuffer':
                    resp_data = base64.b64encode(response.content).decode('ascii')
                else:
                    resp_data = response.text

                self._internalProxyResponse.emit(req_id, response.status_code, resp_data, resp_headers_str)

            except Exception as e:
                print(f"[Proxy] Error: {e}")
                self._internalProxyResponse.emit(req_id, 0, str(e), "")

        self._proxy_executor.submit(run_req)

    def shutdown(self):
        self._proxy_executor.shutdown(wait=False, cancel_futures=True)

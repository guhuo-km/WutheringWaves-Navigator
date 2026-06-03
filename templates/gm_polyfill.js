// GM API Polyfill for QtWebEngine

window.unsafeWindow = window;

// 1. GM_addStyle
window.GM_addStyle = function(css) {
    const style = document.createElement('style');
    style.textContent = css;

    const target = document.head || document.documentElement;
    if (target) {
        target.appendChild(style);
    } else {
        const observer = new MutationObserver((mutations, obs) => {
            const t = document.head || document.documentElement;
            if (t) {
                t.appendChild(style);
                obs.disconnect();
            }
        });
        observer.observe(document, { childList: true, subtree: true });
    }
    return style;
};

// 2. GM_getValue / GM_setValue
window.GM_getValue = function(key, defaultValue) {
    const value = localStorage.getItem('GM_' + key);
    if (value === null) return defaultValue;
    try {
        const wrapper = JSON.parse(value);
        return wrapper.v;
    } catch (e) {
        return defaultValue;
    }
};

window.GM_setValue = function(key, value) {
    localStorage.setItem('GM_' + key, JSON.stringify({ v: value }));
};

window.GM_deleteValue = function(key) {
    localStorage.removeItem('GM_' + key);
};

// 2.5 Lightweight toast for download completion
(function initDownloadToast() {
    let activeToast = null;
    let activeTimer = null;

    function removeToast() {
        if (activeTimer) {
            clearTimeout(activeTimer);
            activeTimer = null;
        }
        if (activeToast && activeToast.parentNode) {
            activeToast.parentNode.removeChild(activeToast);
        }
        activeToast = null;
    }

    function showToast(message) {
        removeToast();

        const toast = document.createElement('div');
        toast.textContent = message || '✅ 下载完成';
        toast.style.cssText = [
            'position: fixed',
            'right: 16px',
            'bottom: 16px',
            'z-index: 2147483647',
            'max-width: 320px',
            'padding: 10px 14px',
            'border-radius: 10px',
            'background: rgba(28, 28, 32, 0.92)',
            'color: #ffffff',
            'font-size: 13px',
            'line-height: 1.4',
            'box-shadow: 0 6px 20px rgba(0, 0, 0, 0.28)',
            'backdrop-filter: blur(3px)',
            'cursor: default',
            'user-select: none'
        ].join(';');

        toast.addEventListener('mouseenter', removeToast);

        const target = document.body || document.documentElement;
        if (!target) return;
        target.appendChild(toast);

        activeToast = toast;
        activeTimer = setTimeout(removeToast, 2000);
    }

    window.__gm_show_download_toast = showToast;
})();

function __gm_is_download_like_response(details, responseText, responseHeaders) {
    try {
        const method = String((details && details.method) || 'GET').toUpperCase();
        if (method !== 'GET') return false;

        const url = String((details && details.url) || '');
        if (!url) return false;

        const headerStr = String(responseHeaders || '').toLowerCase();
        if (headerStr.includes('content-disposition:') && headerStr.includes('attachment')) {
            return true;
        }

        const contentTypeLine = headerStr.split('\n').find(line => line.startsWith('content-type:')) || '';
        const contentType = contentTypeLine.toLowerCase();
        const likelyBinaryType = (
            contentType.includes('application/octet-stream') ||
            contentType.includes('application/zip') ||
            contentType.includes('application/x-zip') ||
            contentType.includes('application/x-rar') ||
            contentType.includes('application/pdf') ||
            contentType.includes('application/vnd')
        );

        if (likelyBinaryType) {
            return true;
        }

        const extLike = /\.(zip|rar|7z|exe|msi|apk|pdf|json)(\?|$)/i.test(url);
        if (extLike && responseText && responseText.length > 0) {
            return true;
        }
    } catch (e) {
        return false;
    }
    return false;
}

// 3. GM_xmlhttpRequest (Bridge to Python)
window.GM_xmlhttpRequest = function(details) {
    const url = details.url;
    const isCrossDomain = (function(u) {
        try {
            const target = new URL(u, window.location.href);
            return target.origin !== window.location.origin;
        } catch(e) { return false; }
    })(url);

    // 需要通过Python代理的域名白名单（用于绕过CORS）
    const shouldProxy = (function(u) {
        if (!u) return false;
        const urlStr = String(u);
        // wuwuddt.com 主站、wuwuddt.com API 和阿里云 OSS 都需要代理
        return urlStr.includes('wuwuddt.com') ||
               urlStr.includes('api.wuwuddt.com') ||
               urlStr.includes('127.0.0.1:58427') ||
               urlStr.includes('localhost:58427') ||
               urlStr.includes('cdn.jsdelivr.net') ||
               urlStr.includes('.oss-cn-') ||           // 阿里云 OSS 所有区域
               urlStr.includes('.aliyuncs.com');        // 阿里云通用域名
    })(url);

    if (!shouldProxy && isCrossDomain) {
        console.warn("[Polyfill] GM_xmlhttpRequest for non-whitelisted domain, using standard XHR:", url);
        // Fallback to standard XHR (will likely fail CORS but won't hang the app)
        const xhr = new XMLHttpRequest();
        xhr.open(details.method || 'GET', url);
        if (details.headers) {
            for (const h in details.headers) xhr.setRequestHeader(h, details.headers[h]);
        }
        xhr.onload = () => {
            if (details.onload) details.onload({
                status: xhr.status,
                responseText: xhr.responseText,
                response: xhr.response,
                readyState: 4
            });
        };
        xhr.onerror = () => { if (details.onerror) details.onerror(); };
        xhr.send(details.data);
        return { abort: () => xhr.abort() };
    }

    // 检查 backend 和 proxyResponse 是否都可用
    if (!window.backend || !window.backend.proxyRequest) {
        console.warn("[Polyfill] GM_xmlhttpRequest: Backend not ready, queuing:", url);
        if (!window._gm_request_queue) window._gm_request_queue = [];
        window._gm_request_queue.push(details);
        return { abort: () => {} };
    }

    // 检查 proxyResponse 信号是否已连接
    if (!window._gm_signal_connected) {
        console.warn("[Polyfill] GM_xmlhttpRequest: proxyResponse signal not connected yet, queuing:", url);
        if (!window._gm_request_queue) window._gm_request_queue = [];
        window._gm_request_queue.push(details);
        return { abort: () => {} };
    }

    const reqId = 'req_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    if (!window._gm_callbacks) window._gm_callbacks = new Map();
    window._gm_callbacks.set(reqId, details);

    const method = details.method || 'GET';
    const responseType = details.responseType || 'text';

    // Handle body types - FormData needs special async handling
    let body = details.data || '';
    let headersObj = details.headers || {};

    if (body instanceof FormData) {
        // FormData needs to be converted to multipart format asynchronously
        (async function() {
            try {
                // Use Response to serialize FormData correctly
                const response = new Response(body);
                const contentType = response.headers.get('content-type');
                const arrayBuffer = await response.arrayBuffer();

                // Convert to Base64
                const uint8Array = new Uint8Array(arrayBuffer);
                let binary = '';
                for (let i = 0; i < uint8Array.length; i++) {
                    binary += String.fromCharCode(uint8Array[i]);
                }
                const base64Body = btoa(binary);

                // Set headers with correct content-type (includes boundary)
                headersObj['Content-Type'] = contentType;
                const headersJson = JSON.stringify(headersObj);

                console.log(`[Polyfill] Bridging FormData request ${reqId} to Python: ${method} ${url}`);

                // Call with special marker for base64 body
                window.backend.proxyRequest(reqId, method, url, headersJson, 'base64:' + base64Body, responseType);
            } catch (e) {
                console.error('[Polyfill] Error processing FormData:', e);
                if (details.onerror) details.onerror({ status: 0, statusText: 'FormData processing error' });
            }
        })();
        return { abort: () => {} };
    }

    if (typeof body === 'object' && body !== null) {
        body = JSON.stringify(body);
    }

    const headersJson = JSON.stringify(headersObj);

    console.log(`[Polyfill] Bridging request ${reqId} to Python: ${method} ${url}`);

    // 调用 Python 方法（不需要回调，响应通过信号返回）
    window.backend.proxyRequest(reqId, method, url, headersJson, body, responseType);

    return { abort: () => {} };
};

window._handleProxyResponse = function(reqId, status, responseText, headers) {
    console.log(`[Polyfill] Received proxy response for ${reqId}, status: ${status}`);
    const details = window._gm_callbacks ? window._gm_callbacks.get(reqId) : null;
    if (!details) {
        console.warn(`[Polyfill] No callback found for request ${reqId}`);
        return;
    }

    window._gm_callbacks.delete(reqId);

    let responseData = responseText;
    if (details.responseType === 'arraybuffer') {
        try {
            const binaryString = atob(responseText);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            responseData = bytes.buffer;
        } catch (e) {
            console.error("GM Polyfill: Base64 decode failed", e);
        }
    }

    const response = {
        readyState: 4,
        status: status,
        statusText: status >= 200 && status < 300 ? "OK" : "Error",
        responseHeaders: headers || "",
        responseText: (details.responseType === 'arraybuffer') ? "" : responseText,
        response: responseData,
        finalUrl: details.url
    };

    if (status >= 200 && status < 300) {
        if (__gm_is_download_like_response(details, responseText, headers)) {
            if (typeof window.__gm_show_download_toast === 'function') {
                window.__gm_show_download_toast('✅ 下载完成');
            }
        }
        if (details.onload) details.onload(response);
    } else {
        if (details.onerror) details.onerror(response);
    }
};

// 4. Global Network Hooks (Selective Proxy for CORS)
(function hookGlobalNetwork() {
    const isCrossDomain = (url) => {
        try {
            const target = new URL(url, window.location.href);
            return target.origin !== window.location.origin;
        } catch(e) { return false; }
    };

    // 需要通过Python代理的域名白名单（用于绕过CORS）
    const shouldProxy = (url) => {
        if (!url) return false;
        const urlStr = String(url);
        // wuwuddt.com 主站、wuwuddt.com API 和阿里云 OSS 都需要代理
        return urlStr.includes('wuwuddt.com') ||
               urlStr.includes('api.wuwuddt.com') ||
               urlStr.includes('.oss-cn-') ||           // 阿里云 OSS 所有区域
               urlStr.includes('.aliyuncs.com');        // 阿里云通用域名
    };

    // Hook fetch
    const originalFetch = window.fetch;
    window.fetch = function(input, init) {
        let url;
        if (typeof input === 'string') url = input;
        else if (input instanceof URL) url = input.href;
        else if (input && input.url) url = input.url;
        else url = String(input);

        if (shouldProxy(url) && isCrossDomain(url)) {
            console.log("[Polyfill] Intercepting fetch (CORS Proxy):", url);
            return new Promise((resolve, reject) => {
                GM_xmlhttpRequest({
                    method: (init && init.method) || 'GET',
                    url: url,
                    headers: (init && init.headers) || {},
                    data: (init && init.body) || '',
                    onload: (res) => {
                        resolve({
                            ok: res.status >= 200 && res.status < 300,
                            status: res.status,
                            statusText: res.statusText,
                            text: () => Promise.resolve(res.responseText),
                            json: () => Promise.resolve(JSON.parse(res.responseText)),
                            arrayBuffer: () => Promise.resolve(res.response),
                            blob: () => Promise.resolve(new Blob([res.response])),
                            headers: {
                                get: (n) => {
                                    const regex = new RegExp('^' + n + ':\\s*(.*)$', 'mi');
                                    const match = res.responseHeaders.match(regex);
                                    return match ? match[1] : null;
                                }
                            }
                        });
                    },
                    onerror: (err) => reject(new Error("Network error via proxy"))
                });
            });
        }
        return originalFetch.apply(this, arguments);
    };

    // Hook XHR
    const originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {
        if (shouldProxy(url) && isCrossDomain(url)) {
            this._proxyUrl = url;
            this._proxyMethod = method;
            this._proxyHeaders = {};
            console.log("[Polyfill] Intercepting XHR (CORS Proxy):", url);

            const originalSetRequestHeader = this.setRequestHeader;
            this.setRequestHeader = function(name, value) {
                this._proxyHeaders[name] = value;
                // Still call original in case it's needed internally by the browser
                if (typeof originalSetRequestHeader === 'function') {
                    try { originalSetRequestHeader.apply(this, arguments); } catch(e) {}
                }
            };

            this.send = (data) => {
                GM_xmlhttpRequest({
                    method: this._proxyMethod,
                    url: this._proxyUrl,
                    headers: this._proxyHeaders,
                    data: data,
                    onload: (res) => {
                        Object.defineProperty(this, 'status', { value: res.status, writable: true, configurable: true });
                        Object.defineProperty(this, 'responseText', { value: res.responseText, writable: true, configurable: true });
                        Object.defineProperty(this, 'response', { value: res.response, writable: true, configurable: true });
                        Object.defineProperty(this, 'readyState', { value: 4, writable: true, configurable: true });
                        this.dispatchEvent(new Event('load'));
                        this.dispatchEvent(new Event('readystatechange'));
                    },
                    onerror: () => {
                        this.dispatchEvent(new Event('error'));
                    }
                });
            };
            return; // Skip original open
        }
        return originalOpen.apply(this, arguments);
    };
})();

// Auto-connect Signal
(function init() {
    let retryCount = 0;
    const maxRetries = 120; // 最多重试120次（60秒）

    function check() {
        if (window._gm_signal_connected) return; // 已连接则退出
        retryCount++;

        // 检查 backend 是否存在
        if (!window.backend) {
            if (retryCount % 20 === 0) {
                console.log(`[Polyfill] Waiting for backend bridge... (${retryCount})`);
            }
            setTimeout(check, 500);
            return;
        }

        // 检查 proxyResponse 信号是否存在
        if (!window.backend.proxyResponse) {
            if (retryCount % 20 === 0) {
                console.log(`[Polyfill] Backend found but proxyResponse signal not available yet... (${retryCount})`);
                // 输出 backend 对象的可用属性以便调试
                console.log("[Polyfill] Available backend properties:", Object.keys(window.backend));
            }
            if (retryCount < maxRetries) {
                setTimeout(check, 500);
            } else {
                console.error("[Polyfill] FATAL: Max retries reached. proxyResponse signal is NOT available on backend object.");
                console.error("[Polyfill] Backend object keys:", Object.keys(window.backend));
            }
            return;
        }

        // 尝试连接信号
        try {
            // 不需要连接 QWebChannel 信号，Python 端会直接通过 runJavaScript 调用
            // window.backend.proxyResponse.connect(window._handleProxyResponse);
            window._gm_signal_connected = true;
            console.log("[Polyfill] ✓ Backend connected (using runJavaScript bypass)");

            // 处理队列中的请求
            if (window._gm_request_queue && window._gm_request_queue.length > 0) {
                const q = window._gm_request_queue;
                window._gm_request_queue = [];
                console.log(`[Polyfill] Processing ${q.length} queued requests`);
                q.forEach(d => GM_xmlhttpRequest(d));
            }
        } catch(e) {
            console.error("[Polyfill] Failed to setup backend:", e);
            window._gm_signal_connected = false;
            if (retryCount < maxRetries) {
                setTimeout(check, 1000);
            }
        }
    }

    // 启动检查
    check();
})();

console.log("GM Polyfill + Network Hooks Ready");

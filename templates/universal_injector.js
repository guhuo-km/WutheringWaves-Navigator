(function() {
    // 防止重复注入
    if (window._universal_injector_loaded) {
        console.log("Universal Injector already loaded.");
        return;
    }
    window._universal_injector_loaded = true;
    console.log("Universal Injector: Starting initialization...");

    function probeCount(name) {
        try {
            if (localStorage.getItem('KMP_RESOURCE_PROBE') !== 'true') return;
            window.__kmpResourceProbe = window.__kmpResourceProbe || { counters: {}, last: Date.now() };
            const p = window.__kmpResourceProbe;
            p.counters[name] = (p.counters[name] || 0) + 1;
            const now = Date.now();
            if (now - p.last < 60000) return;
            const elapsed = Math.max(1, (now - p.last) / 1000);
            const parts = Object.keys(p.counters).sort().map(k => `${k}=${p.counters[k]} (${(p.counters[k] / elapsed).toFixed(2)}/s)`);
            console.log(`[RESOURCE_PROBE_JS] interval=${elapsed.toFixed(1)}s ${parts.join('; ')}`);
            p.counters = {};
            p.last = now;
        } catch (e) {}
    }

    // ==========================================
    // 1. 地图实例拦截逻辑 (Map Interception)
    // ==========================================

    function deployInterception() {
        // 如果已捕获，跳过
        if (window.discoveredMap && typeof window.discoveredMap.panTo === 'function') {
            return true;
        }

        if (typeof L === 'object' && L.Map && L.Map.prototype) {
            // --- A计划: 构造函数拦截 ---
            if (L.Map.prototype.initialize && !L.Map.prototype.initialize._isPatched) {
                console.log("部署A计划: 拦截构造函数...");
                const originalInitialize = L.Map.prototype.initialize;
                L.Map.prototype.initialize = function(...args) {
                    console.log("%cA计划命中！地图实例被捕获！", 'color: #00ff00; font-size: 14px; font-weight: bold;');
                    window.discoveredMap = this;
                    return originalInitialize.apply(this, args);
                };
                L.Map.prototype.initialize._isPatched = true;
            }

            // --- B计划: 交互函数拦截 ---
            let deployedB = false;
            const functionsToPatch = ['setView', 'panTo', 'flyTo', 'fitBounds', 'scrollWheelZoom', 'touchZoom'];
            for (const funcName of functionsToPatch) {
                if (L.Map.prototype[funcName] && !L.Map.prototype[funcName]._isPatchedB) {
                    if (!deployedB) console.log("部署B计划: 交互函数埋点...");
                    deployedB = true;

                    const originalFunction = L.Map.prototype[funcName];
                    L.Map.prototype[funcName] = function(...args) {
                        if (!window.discoveredMap) {
                             console.log(`%cB计划命中！通过 '${funcName}' 捕获地图！`, 'color: #FFA500; font-size: 14px; font-weight: bold;');
                             window.discoveredMap = this;
                        }
                        return originalFunction.apply(this, args);
                    };
                    L.Map.prototype[funcName]._isPatchedB = true;
                }
            }
            return true;
        }
        return false;
    }

    // 立即尝试一次
    deployInterception();

    // ==========================================
    // 2. 桥接与事件同步逻辑 (Bridge & Sync)
    // ==========================================

    let backend = null;
    let mapBound = false;
    let lastMapName = null;

    // 初始化 QWebChannel 连接
    function initBridge() {
        if (typeof QWebChannel === 'undefined') return;
        if (typeof qt === 'undefined' || !qt.webChannelTransport) return;
        if (backend) return; // 已连接

        new QWebChannel(qt.webChannelTransport, function(channel) {
            backend = channel.objects.backend;
            window.backend = backend; // 暴露给全局，方便调试
            console.log("Universal Injector: QWebChannel Connected");

            // Mark signal as connected for GM polyfill
            window._gm_signal_connected = true;

            // Flush any queued GM requests
            if (window._gm_request_queue && window._gm_request_queue.length > 0) {
                console.log("[Universal Injector] Flushing " + window._gm_request_queue.length + " queued GM requests");
                const queue = window._gm_request_queue.splice(0);
                queue.forEach(function(details) {
                    if (window.GM_xmlhttpRequest) {
                        window.GM_xmlhttpRequest(details);
                    }
                });
            }

            // 调试：输出 backend 对象的所有属性
            if (backend) {
                console.log("[Universal Injector] Backend object available. Properties:");
                for (let key in backend) {
                    console.log(`  - ${key}: ${typeof backend[key]}`);
                }
                // 特别检查 proxyResponse
                if (backend.proxyResponse) {
                    console.log("[Universal Injector] ✓ proxyResponse signal is available");
                } else {
                    console.warn("[Universal Injector] ✗ proxyResponse signal is NOT available!");
                }
            }

            checkAndBind();
        });
    }

    // 检查并绑定事件
    function checkAndBind() {
        if (!backend) return;

        // 尝试获取地图实例 (兼容 window.map 和 window.discoveredMap)
        let map = window.discoveredMap || window.map;

        if (map && !mapBound) {
            console.log("Universal Injector: Binding map events to Python backend");

            // 定义坐标同步函数
            const updateStatus = () => {
                try {
                    const center = map.getCenter();
                    const zoom = map.getZoom();
                    backend.updateStatus(center.lat, center.lng, zoom);
                } catch(e) { console.error("UpdateStatus Error:", e); }
            };

            // 移除旧监听器并添加新监听器
            map.off('moveend zoomend', updateStatus);
            map.on('moveend zoomend', updateStatus);

            // 立即发送一次状态
            updateStatus();

            mapBound = true;
        }

        // 检查 URL 变化 (用于检测地图切换)
        try {
            // 尝试从 URL 参数 'map' 获取当前地图名
            const params = new URLSearchParams(window.location.search);
            const currentMap = params.get('map');

            if (currentMap && currentMap !== lastMapName) {
                // 如果地图名发生变化
                lastMapName = currentMap;

                // 只有当提供了 localMapChanged 槽函数时才调用 (MapWindow 和 MainWindow 都应该提供)
                if (backend.localMapChanged) {
                    backend.localMapChanged(currentMap);
                    console.log("Universal Injector: Reported map change to " + currentMap);
                }
            }
        } catch(e) { console.error("URL Check Error:", e); }
    }

    // Define triggerCapture for recapture functionality
    window.triggerCapture = function() {
        if (window.discoveredMap && window.backend) {
            try {
                const center = window.discoveredMap.getCenter();
                const zoom = window.discoveredMap.getZoom();
                window.backend.updateStatus(center.lat, center.lng, zoom);
                console.log("triggerCapture: Status updated");
            } catch(e) {
                console.error("triggerCapture Error:", e);
            }
        } else {
            console.warn("triggerCapture: Map or backend not ready");
        }
    };

    // ==========================================
    // 3. 运行时监控 (Runtime Monitoring)
    // ==========================================

    // 劫持 History API 以监听 URL 变化 (SPA常用技巧)
    const wrapHistory = (type) => {
        const original = history[type];
        return function() {
            const result = original.apply(this, arguments);
            checkAndBind(); // URL 变了，检查一下
            return result;
        };
    };
    history.pushState = wrapHistory('pushState');
    history.replaceState = wrapHistory('replaceState');
    window.addEventListener('popstate', checkAndBind);

    // 定时轮询机制 (处理异步加载)
    setInterval(() => {
        probeCount('universal.tick');
        // 如果地图还没捕获，尝试部署拦截器
        deployInterception();

        // 如果 QWebChannel 还没连接，尝试连接
        if (!backend) initBridge();

        // 检查地图状态和事件绑定
        checkAndBind();
    }, 1000);


    // 立即启动
    initBridge();
})();

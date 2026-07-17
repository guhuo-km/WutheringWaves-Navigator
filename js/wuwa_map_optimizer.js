// ==UserScript==
// @name         呜呜地图优化
// @namespace    https://github.com/guhuo-km/
// @version      1.2.5
// @description  集成了 UI隐藏、标记优化、路径绘制(SVG/JSON)、社区标签与搜索系统。
// @author       guhuo-km
// @match        https://www.kurobbs.com/mc/map/*
// @match        https://www.kurobbs.com/mc/map/
// @resource     JSZIP https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js
// @connect      api.wuwuddt.com
// @connect      api.wuwuddt.guhuo.site
// @connect      wuwuddt-routes-gb869h.oss-cn-beijing.aliyuncs.com
// @connect      *.oss-cn-beijing.aliyuncs.com
// @connect      *.aliyuncs.com
// @connect      127.0.0.1
// @connect      localhost
// @connect      cdn.jsdelivr.net
// @grant        GM_xmlhttpRequest
// @grant        GM_getResourceText
// @grant        GM_addStyle
// @grant        unsafeWindow
// @run-at       document-start
// @license      MIT
// ==/UserScript==

(function() {
    'use strict';

    const globalScope = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
    // Leaflet instance (assigned once detected)
    let L;

    function resourceProbeCount(name) {
        try {
            if (localStorage.getItem('KMP_RESOURCE_PROBE') !== 'true') return;
            globalScope.__kmpResourceProbe = globalScope.__kmpResourceProbe || { counters: {}, last: Date.now() };
            const p = globalScope.__kmpResourceProbe;
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

    const getStore = (key, def) => {
        const val = localStorage.getItem(key);
        return val === null ? def : val === 'true';
    };

    const getRouteMarkerDisplayMode = () => {
        const value = localStorage.getItem('KMP_ROUTE_MARKER_DISPLAY_MODE');
        return ['none', 'highlight', 'focus'].includes(value) ? value : 'highlight';
    };

    const STATE = {
        mapInstance: null,
        mainLayerGroup: null,
        highlightLayer: null,
        routeMarkerHighlightLayer: null,
        smartMarkHistory: [],
        routeManager: {
            routes: [],
            selectedIds: new Set(),
            singleVisibleMode: false,
            activeRouteIndex: -1,
            markerDisplayMode: getRouteMarkerDisplayMode(),
            add: null,
            remove: null,
            toggleVisible: null,
            redraw: null,
            // 新增编辑相关方法
            createNewRoute: null,
            startEdit: null,
            cancelEdit: null,
            saveEdit: null,
            updateEditLayer: null
        },
        toggles: {
            cleanUI: {
                switchTools: getStore('SM_UI_SWITCH_TOOLS', false),
                sideMenu: getStore('SM_UI_SIDE_MENU', false),
                leftTop: getStore('SM_UI_LEFT_TOP', false),
                zoomControl: getStore('SM_UI_ZOOM_CONTROL', false),
                mobile: getStore('SM_UI_MOBILE', false),
                syncMarker: getStore('SM_UI_SYNC_MARKER', false)
            },
            markerOptimization: getStore('SM_MARKER_OPT', false),
            pauseTrackingWhenPopupOpen: getStore('SM_PAUSE_TRACKING_WHEN_POPUP_OPEN', true)
        },
        pointCache: new Map(),
        // id -> { id, x, y, level, name, type?, fp }  (x/y 为 position.json 的坐标数值，用于 Leaflet 线性变换)
        pointIdCache: new Map(),
        // fp -> Map(id -> typeId|null)  (用于“标签聚焦”把 fp 映射回实际标点控制器)
        fpIdIndex: new Map(),
        markerFocus: {
            active: false,
            owner: null,
            keepKeys: new Set(), // `${typeId}::${id}`
            restoreOpacity: new Map(), // key -> opacity number (restore on exit)
            _applyTimer: null,
            _restoreTimer: null,
            _pendingRestoreEntries: null,
            _mapStoreUnsub: null,
            _busy: false,
            _lastLog: ''
        },
        // 坐标变换参数（自动校准后持久化；为空则使用默认 CONFIG）
        coordTransform: null,
        _coordCalibTimer: null,
        _coordCalibDone: false,
        _coordCalibLastLog: '',
        _coordCalibReason: '',
        tileMetadata: {
            standardTiles: new Map(),
            layeredTiles: new Map(),
            gravityTiles: new Map(),
            tileBaseUrl: '',
            ossParams: '',
            tileWidth: 1024,
            currentAreaId: '',
            updatedAt: 0,
            changed: false,
            resourceObserverInstalled: false,
            notificationTimer: null
        },
        currentDetail: null,
        pageState: new Map(),
        observer: null,
        popupDomObserver: null,
        _popupObservedEl: null,
        _activePopupEl: null,
        _popupSyncScheduled: false,
        dragDropBound: false,
        routeUploadModalOpen: false,
        routeUploadTickets: new Map(), // sha256 -> { sha256, uploadId, ossUrl, ossFields, expireAt }
        _pageJsZipPromise: null,
        searchUI: {
            mode: 'tag', // 'tag' | 'route'
            tagFocusOnly: true, // 标签模式：屏蔽无关点并强制显示目标点
            tagSelection: { kind: '', key: '' }, // kind: 'tag' | 'fp' | ''
            _selectedFps: [], // Array<string>：当前选中的 fp 列表（用于聚焦恢复/重放）
            _hotTags: [], // Array<{text, score}>：热门标签（热度排序）
            _hotTagsAt: 0,
            _hotTagsPromise: null,
            _hotTagFpCache: new Map(), // tagText -> { fps:Array<string>, at:number }
            idle: { page: 1, pageSizeTags: 20, pageSizeSingles: 10 },
            _idleSeq: 0,
            route: {
                tab: 'square', // 'square' | 'fav' | 'mine'
                sort: 'downloads', // 'downloads' | 'favorites' | 'likes'
                page: 1,
                totalPages: 1
            }
        }
    };
    const SMART_MARK_HISTORY_LIMIT = 100;
    const SMART_MARK_TEXT = {
        unnamed: '未命名',
        noUndoTarget: '暂无可撤销的标记',
        noHistory: '没有历史记录',
        undoLabel: '撤销',
        undoing: '撤销中...',
        undone: '已撤销',
        undoFailed: '撤销失败',
        requestFailed: '请求失败'
    };

    const CONFIG = {
        route: {
            zMin: -100, zRange: 400,
            SCALE: 0.01204705882352941,
            OFFSET: 1024,
            defaultWeight: 4, defaultSize: 1.2, defaultGap: 150
        },
        canvas: { offsetY: 25 },
        api: { base: 'https://api.wuwuddt.com' }
    };

    const IMPORT_LIMITS = {
        zipMaxBytes: 10 * 1024 * 1024,
        unzipMatchedMaxBytes: 15 * 1024 * 1024,
        unzipMatchedMaxFiles: 40
    };
    const ROUTE_GRAPH_SCHEMA = 'wuwa-route-graph';
    const ROUTE_GRAPH_VERSION = 2;
    const GRAPH_BOX_SELECT_THRESHOLD_RATIO = 0.5;
    const KMP_ARROW_PANE_Z_INDEX = 650;
    const KMP_EDIT_LINE_PANE_Z_INDEX = 660;
    const KMP_EDIT_MARKER_PANE_Z_INDEX = 670;
    const KMP_EDIT_DECORATION_PANE_Z_INDEX = 680;
    const SPECIAL_MARKER_SHAPES = [
        'circle', 'square', 'rounded-square', 'diamond', 'triangle-up', 'triangle-down',
        'pentagon', 'hexagon', 'octagon', 'star', 'ellipse', 'capsule'
    ];
    const DEFAULT_SPECIAL_MARKER_STYLE = {
        shape: 'diamond',
        fill_color: '#E06474',
        number: {
            font_size: 24,
            color: '#FFFFFF',
            outline: { enabled: true, width: 2, color: '#111111' }
        }
    };
    const SPECIAL_MARKER_GROUP_TEXT = {
        toolbar: '设置分组',
        sidebarTitle: '特殊标记分组',
        createGroup: '新建分组',
        emptyGroups: '暂无分组',
        groupLabel: '分组',
        members: '成员',
        emptyMembers: '暂无成员',
        addNode: '添加节点',
        stopAdding: '停止添加',
        editStyle: '编辑样式',
        deleteGroup: '删除组',
        moveUp: '上移',
        moveDown: '下移',
        removeMember: '移除',
        styleSummary: '当前组样式',
        noSelection: '选择一个分组查看样式',
        createTitle: '新建特殊标记分组',
        editTitle: '编辑特殊标记样式',
        shape: '形状',
        fillColor: '填充颜色',
        numberColor: '数字颜色',
        numberSize: '数字字号',
        outlineEnabled: '启用数字描边',
        outlineWidth: '描边粗细',
        outlineColor: '描边颜色',
        preview: '预览',
        hue: '色相',
        hex: 'Hex',
        cancel: '取消',
        create: '创建',
        done: '完成',
        shapeLabels: {
            circle: '圆形', square: '正方形', 'rounded-square': '圆角正方形', diamond: '菱形',
            'triangle-up': '上三角', 'triangle-down': '下三角', pentagon: '五边形', hexagon: '六边形',
            octagon: '八边形', star: '五角星', ellipse: '椭圆', capsule: '胶囊形'
        }
    };
    const ROUTE_LIST_TEXT = {
        mergeSelected: '合并选中',
        mergedRoutePrefix: '合并路线',
        selectionTitle: '勾选用于批量操作'
    };

    const JSZIP_CDN = 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js';
    const JSZIP_LOCAL_URLS = [
        'http://127.0.0.1:58427/jszip.min.js',
        'http://localhost:58427/jszip.min.js'
    ];

    function setImportStatus(message, isError = false) {
        const el = document.getElementById('sm-import-status');
        if (!el) return;
        el.style.color = isError ? '#f44336' : '#aaa';
        el.innerText = message || '';
    }

    const DEBUG_IMPORT = false;
    function logImport(...args) {
        if (!DEBUG_IMPORT) return;
        try { console.info('[KMP Import]', ...args); } catch (e) {}
    }

    function getLoadedJSZip() {
        const z1 = globalScope && globalScope.JSZip;
        if (z1 && typeof z1.loadAsync === 'function') return z1;
        try {
            const z2 = (typeof JSZip !== 'undefined') ? JSZip : null;
            if (z2 && typeof z2.loadAsync === 'function') return z2;
        } catch (e) {}
        return null;
    }

    function evalAsUserscriptGlobal(code) {
        // 使用“间接 eval”在 userscript 作用域执行（不受页面 CSP 影响）
        (0, eval)(code);
    }

    function isEmbeddedLocalEnv() {
        return typeof window !== 'undefined' && (
            typeof qt !== 'undefined' ||
            typeof QWebChannel !== 'undefined' ||
            (window.backend && typeof window.backend.proxyRequest === 'function')
        );
    }

    function gmFetchText(url, timeoutMs) {
        return new Promise((resolve, reject) => {
            try {
                GM_xmlhttpRequest({
                    method: 'GET',
                    url: url,
                    responseType: 'text',
                    timeout: timeoutMs || 15000,
                    onload: (res) => {
                        const ok = res && res.status >= 200 && res.status < 300 && typeof res.responseText === 'string';
                        if (!ok) reject(new Error(`JSZip下载失败：HTTP ${res && res.status}`));
                        else resolve(res.responseText);
                    },
                    onerror: () => reject(new Error('JSZip下载失败')),
                    ontimeout: () => reject(new Error('JSZip下载超时'))
                });
            } catch (e) {
                reject(e);
            }
        });
    }

    async function ensurePageJSZip() {
        const page = getLoadedJSZip();
        if (page) return page;
        if (STATE._pageJsZipPromise) return await STATE._pageJsZipPromise;

        const loader = (async () => {
            // 方案A：内置客户端优先走本地 jszip.min.js，避免 CDN / @resource 偶发失败
            if (typeof GM_xmlhttpRequest === 'function' && isEmbeddedLocalEnv()) {
                let lastLocalError = null;
                for (const url of JSZIP_LOCAL_URLS) {
                    try {
                        const code = await gmFetchText(url, 3000);
                        if (code && typeof code === 'string' && code.length > 1000) {
                            evalAsUserscriptGlobal(code);
                            const z = getLoadedJSZip();
                            if (z) return z;
                        }
                    } catch (e) {
                        lastLocalError = e;
                        logImport('Local JSZip fetch failed', url, e);
                    }
                }
                if (lastLocalError) {
                    logImport('Local JSZip unavailable, falling back to userscript resource/CDN', lastLocalError);
                }
            }

            // 方案A：Tampermonkey 资源（安装/更新时下载，运行时不受站点 CSP 的外链 script 限制）
            if (typeof GM_getResourceText === 'function') {
                try {
                    const code = GM_getResourceText('JSZIP');
                    if (code && typeof code === 'string' && code.length > 1000) {
                        evalAsUserscriptGlobal(code);
                        const z = getLoadedJSZip();
                        if (z) return z;
                    }
                } catch (e) {}
            }

            // 方案B：GM_xmlhttpRequest 拉取并在 userscript 作用域执行（绕过页面 CSP）
            if (typeof GM_xmlhttpRequest === 'function') {
                const canUseLocal = isEmbeddedLocalEnv();
                const urls = [];
                if (canUseLocal) {
                    urls.push(...JSZIP_LOCAL_URLS);
                }
                urls.push(JSZIP_CDN);

                let lastError = null;
                for (const url of urls) {
                    try {
                        const timeoutMs = url.includes('localhost') || url.includes('127.0.0.1') ? 3000 : 15000;
                        const code = await gmFetchText(url, timeoutMs);
                        if (code && typeof code === 'string' && code.length > 1000) {
                            evalAsUserscriptGlobal(code);
                            const z = getLoadedJSZip();
                            if (z) return z;
                        }
                    } catch (e) {
                        lastError = e;
                        logImport('JSZip fetch failed', url, e);
                    }
                }
                if (lastError) {
                    logImport('JSZip GM download failed, falling back to <script> injection', lastError);
                }
            }

            // 方案C：旧版注入 <script>（可能被站点 CSP 拦截，保留作兜底）
            await new Promise((resolve, reject) => {
                try {
                    const doc = document;
                    const parent = doc.head || doc.documentElement;
                    if (!parent) {
                        reject(new Error('无法注入JSZip：document未就绪'));
                        return;
                    }

                    const existing = doc.querySelector(`script[data-kmp-jszip="1"]`);
                    if (existing) {
                        const t = setTimeout(() => reject(new Error('JSZip加载超时')), 10000);
                        existing.addEventListener('load', () => { clearTimeout(t); resolve(); }, { once: true });
                        existing.addEventListener('error', () => { clearTimeout(t); reject(new Error('JSZip脚本加载失败')); }, { once: true });
                        return;
                    }

                    const script = doc.createElement('script');
                    script.dataset.kmpJszip = '1';
                    script.src = JSZIP_CDN;
                    script.async = true;
                    const t = setTimeout(() => reject(new Error('JSZip加载超时')), 10000);
                    script.onload = () => { clearTimeout(t); resolve(); };
                    script.onerror = () => { clearTimeout(t); reject(new Error('JSZip脚本加载失败（可能被CSP拦截）')); };
                    parent.appendChild(script);
                } catch (e) {
                    reject(e);
                }
            });

            const z = getLoadedJSZip();
            if (z) return z;
            throw new Error('JSZip加载完成但未挂载到页面');
        })();

        STATE._pageJsZipPromise = loader.catch((err) => {
            STATE._pageJsZipPromise = null;
            throw err;
        });

        return await STATE._pageJsZipPromise;
    }

    const SETTINGS = {
        pathWeight: CONFIG.route.defaultWeight,
        arrowSize: CONFIG.route.defaultSize,
        arrowGap: CONFIG.route.defaultGap
    };

    // ==============================
    // 坐标变换参数（可持久化覆盖默认值）
    // ==============================
    const COORD_TRANSFORM_KEY = 'SM_COORD_TRANSFORM_V1';

    function getDefaultCoordTransform() {
        return {
            scaleX: CONFIG.route.SCALE,
            scaleY: CONFIG.route.SCALE,
            offsetX: CONFIG.route.OFFSET,
            offsetY: 0
        };
    }

    function loadCoordTransform() {
        try {
            const raw = localStorage.getItem(COORD_TRANSFORM_KEY);
            if (!raw) return null;
            const obj = JSON.parse(raw);
            if (!obj || typeof obj !== 'object') return null;
            const scaleX = Number(obj.scaleX);
            const scaleY = Number(obj.scaleY);
            const offsetX = Number(obj.offsetX);
            const offsetY = Number(obj.offsetY);
            if (![scaleX, scaleY, offsetX, offsetY].every(Number.isFinite)) return null;
            if (scaleX <= 0 || scaleY <= 0) return null;
            return { scaleX, scaleY, offsetX, offsetY };
        } catch (e) {
            return null;
        }
    }

    function persistCoordTransform(t, meta = {}) {
        if (!t) return;
        const scaleX = Number(t.scaleX);
        const scaleY = Number(t.scaleY);
        const offsetX = Number(t.offsetX);
        const offsetY = Number(t.offsetY);
        if (![scaleX, scaleY, offsetX, offsetY].every(Number.isFinite)) return;
        if (scaleX <= 0 || scaleY <= 0) return;
        STATE.coordTransform = { scaleX, scaleY, offsetX, offsetY };
        try {
            localStorage.setItem(COORD_TRANSFORM_KEY, JSON.stringify({
                scaleX, scaleY, offsetX, offsetY,
                updatedAt: Date.now(),
                meta
            }));
        } catch (e) {}
    }

    function getCoordTransform() {
        return STATE.coordTransform || getDefaultCoordTransform();
    }

    function getTileProjectionContext() {
        const tileSize = Number(STATE.tileMetadata.tileWidth || 1024);
        const map = STATE.mapInstance;
        const crs = map && map.options ? map.options.crs : null;
        const transformation = crs && crs.transformation ? crs.transformation : null;
        const scaleX = transformation && Number.isFinite(Number(transformation._a)) ? Number(transformation._a) : null;
        const scaleY = transformation && Number.isFinite(Number(transformation._c)) ? Number(transformation._c) : null;
        return {
            tileSize,
            crsScaleX: scaleX,
            crsScaleY: scaleY,
            mapUnitsPerTileX: scaleX && scaleX !== 0 ? tileSize / scaleX : null,
            mapUnitsPerTileY: scaleY && scaleY !== 0 ? tileSize / scaleY : null
        };
    }

    function getMapContext() {
        return {
            areaId: String(STATE.tileMetadata.currentAreaId || ''),
            coordTransform: STATE.coordTransform || getDefaultCoordTransform(),
            tileSize: 1024,
            tileProjection: getTileProjectionContext(),
            mapProvider: 'official_map'
        };
    }

    function getOssParamsFromUrl(url) {
        try {
            const parsed = new URL(String(url), window.location.href);
            return parsed.search ? parsed.search.slice(1) : '';
        } catch (e) {
            const raw = String(url || '');
            const idx = raw.indexOf('?');
            return idx >= 0 ? raw.slice(idx + 1) : '';
        }
    }

    function normalizeTileUrl(url) {
        try {
            const parsed = new URL(String(url), window.location.href);
            return {
                cleanUrl: `${parsed.origin}${parsed.pathname}`,
                fullUrl: parsed.href
            };
        } catch (e) {
            const raw = String(url || '');
            return {
                cleanUrl: raw.split('?')[0].split('#')[0],
                fullUrl: raw
            };
        }
    }

    function parseTileMetadataFromUrl(url) {
        const raw = String(url || '');
        if (!raw || !raw.includes('.png')) return null;

        const normalized = normalizeTileUrl(raw);
        const cleanUrl = normalized.cleanUrl;
        const common = {
            url: normalized.fullUrl,
            ossParams: getOssParamsFromUrl(raw),
            tileWidth: 1024
        };

        let match = cleanUrl.match(/^(.*)\/(\d+)\/\2_(-?\d+)_(-?\d+)\.png$/);
        if (match) {
            return Object.assign(common, {
                type: 'standard',
                tileBaseUrl: match[1],
                regionId: match[2],
                x: Number(match[3]),
                y: Number(match[4])
            });
        }

        match = cleanUrl.match(/^(.*)\/(\d+)\/(\d+)\/(-?\d+)\/(-?\d+)_(-?\d+)\.png$/);
        if (match) {
            return Object.assign(common, {
                type: 'layered',
                tileBaseUrl: match[1],
                regionId: match[2],
                layerId: match[3],
                zLevel: Number(match[4]),
                x: Number(match[5]),
                y: Number(match[6])
            });
        }

        match = cleanUrl.match(/^(.*)\/(\d+)\/(\d+)\/(-?\d+)_(-?\d+)_(-?\d+)\.png$/);
        if (match) {
            return Object.assign(common, {
                type: 'layered',
                tileBaseUrl: match[1],
                regionId: match[2],
                layerId: match[3],
                zLevel: Number(match[4]),
                x: Number(match[5]),
                y: Number(match[6])
            });
        }

        match = cleanUrl.match(/^(.*)\/(\d+)\/(\d+)\/(-?\d+)_(-?\d+)\.png$/);
        if (match) {
            return Object.assign(common, {
                type: 'gravity',
                tileBaseUrl: match[1],
                regionId: match[2],
                layerId: match[3],
                zLevel: 0,
                x: Number(match[4]),
                y: Number(match[5])
            });
        }

        return null;
    }

    function getTileMetadataStore(kind) {
        if (kind === 'standard') return STATE.tileMetadata.standardTiles;
        if (kind === 'layered') return STATE.tileMetadata.layeredTiles;
        if (kind === 'gravity') return STATE.tileMetadata.gravityTiles;
        return null;
    }

    function tileMetadataKey(tile) {
        return [
            tile.type,
            tile.regionId || '',
            tile.layerId || 'default',
            tile.zLevel === undefined || tile.zLevel === null ? 'base' : tile.zLevel,
            tile.x,
            tile.y
        ].join(':');
    }

    function notifyTileMetadataChanged(updatedAt) {
        try {
            globalScope.__WuwaTileMetadataUpdatedAt = updatedAt;
            globalScope.dispatchEvent(new CustomEvent('wuwaTileMetadataChanged', { detail: { updatedAt } }));
        } catch (e) {}
    }

    function scheduleTileMetadataChanged(updatedAt) {
        if (STATE.tileMetadata.notificationTimer) {
            clearTimeout(STATE.tileMetadata.notificationTimer);
        }
        STATE.tileMetadata.notificationTimer = setTimeout(() => {
            STATE.tileMetadata.notificationTimer = null;
            notifyTileMetadataChanged(updatedAt);
        }, 150);
    }

    function sameTileMetadata(previous, current) {
        if (!previous || !current) return false;
        return [
            'type', 'regionId', 'layerId', 'zLevel', 'x', 'y', 'url',
            'tileBaseUrl', 'ossParams', 'tileWidth',
            'leafletTileX', 'leafletTileY', 'leafletTileZ'
        ].every(field => previous[field] === current[field]);
    }

    function attachLeafletTileCoords(tile, coords) {
        if (!coords || typeof coords !== 'object') return tile;
        const leafletTileX = Number(coords.x);
        const leafletTileY = Number(coords.y);
        const leafletTileZ = Number(coords.z);
        if (Number.isFinite(leafletTileX)) tile.leafletTileX = leafletTileX;
        if (Number.isFinite(leafletTileY)) tile.leafletTileY = leafletTileY;
        if (Number.isFinite(leafletTileZ)) tile.leafletTileZ = leafletTileZ;
        return tile;
    }

    function observeTileMetadataUrl(url, coords = null) {
        const parsed = parseTileMetadataFromUrl(url);
        if (!parsed) return false;

        const store = getTileMetadataStore(parsed.type);
        if (!store) return false;

        const updatedAt = Date.now();
        const tile = attachLeafletTileCoords(Object.assign({}, parsed, { updatedAt }), coords);
        const key = tileMetadataKey(tile);
        const previous = store.get(key);
        if (previous && sameTileMetadata(previous, tile)) return true;
        store.set(key, tile);

        STATE.tileMetadata.currentAreaId = String(tile.regionId || STATE.tileMetadata.currentAreaId || '');
        STATE.tileMetadata.tileBaseUrl = tile.tileBaseUrl || STATE.tileMetadata.tileBaseUrl;
        STATE.tileMetadata.ossParams = tile.ossParams || STATE.tileMetadata.ossParams;
        STATE.tileMetadata.tileWidth = tile.tileWidth || 1024;
        STATE.tileMetadata.updatedAt = updatedAt;
        STATE.tileMetadata.changed = true;
        scheduleTileMetadataChanged(updatedAt);
        return true;
    }

    function getTileMetadataSnapshot() {
        const metadata = STATE.tileMetadata;
        return {
            mapContext: getMapContext(),
            standardTiles: Array.from(metadata.standardTiles.values()),
            layeredTiles: Array.from(metadata.layeredTiles.values()),
            gravityTiles: Array.from(metadata.gravityTiles.values()),
            tileBaseUrl: metadata.tileBaseUrl,
            ossParams: metadata.ossParams,
            tileWidth: metadata.tileWidth,
            tileProjection: getTileProjectionContext(),
            updatedAt: metadata.updatedAt,
            changed: metadata.changed
        };
    }

    function installTileMetadataResourceObserver() {
        if (STATE.tileMetadata.resourceObserverInstalled) return;
        STATE.tileMetadata.resourceObserverInstalled = true;

        try {
            if (window.performance && typeof window.performance.getEntriesByType === 'function') {
                for (const entry of window.performance.getEntriesByType('resource') || []) {
                    if (entry && entry.name) observeTileMetadataUrl(entry.name);
                }
            }
        } catch (e) {}

        try {
            if (typeof PerformanceObserver !== 'function') return;
            const observer = new PerformanceObserver((list) => {
                for (const entry of list.getEntries() || []) {
                    if (entry && entry.name) observeTileMetadataUrl(entry.name);
                }
            });
            observer.observe({ type: 'resource', buffered: true });
        } catch (e) {}
    }

    // 暴露到全局供 Python 端读取
    window.getCoordTransform = getCoordTransform;

    // 初始化读取（如有历史值则永久覆盖默认值）
    STATE.coordTransform = loadCoordTransform();
    if (STATE.coordTransform) {
        try {
            console.info('[KMP Calib] loaded', {
                scaleX: STATE.coordTransform.scaleX,
                scaleY: STATE.coordTransform.scaleY,
                offsetX: STATE.coordTransform.offsetX,
                offsetY: STATE.coordTransform.offsetY
            });
        } catch (e) {}
    }

    function scheduleAutoCalibrate(reason) {
        if (STATE._coordCalibDone) return;
        STATE._coordCalibReason = reason || STATE._coordCalibReason || '';
        if (STATE._coordCalibTimer) return;

        const startedAt = Date.now();
        const MAX_MS = 2 * 60 * 1000;
        const TICK_MS = 1500;

        STATE._coordCalibTimer = setInterval(() => {
            resourceProbeCount('coord_calib.tick');
            try {
                const done = tryAutoCalibrateCoordTransform(STATE._coordCalibReason);
                if (done) {
                    clearInterval(STATE._coordCalibTimer);
                    STATE._coordCalibTimer = null;
                    STATE._coordCalibDone = true;
                    return;
                }
                if (Date.now() - startedAt > MAX_MS) {
                    clearInterval(STATE._coordCalibTimer);
                    STATE._coordCalibTimer = null;
                }
            } catch (e) {}
        }, TICK_MS);
    }

    function tryAutoCalibrateCoordTransform(reason) {
        const map = STATE.mapInstance;
        if (!map) return false;
        if (!L) return false;
        if (!STATE.pointIdCache || STATE.pointIdCache.size < 3) return false;

        const store = getMapStore();
        const cache = store && store.markersCache;
        if (!(cache instanceof Map) || cache.size === 0) return false;

        const samples = [];
        const MAX_SAMPLES = 800;

        const readLatLng = (obj) => {
            try {
                if (obj && typeof obj.getLocation === 'function') return obj.getLocation();
                const m0 = obj && obj.markers && obj.markers[0];
                if (m0 && typeof m0.getLatLng === 'function') return m0.getLatLng();
                return obj && obj._latlng ? obj._latlng : (m0 && m0._latlng ? m0._latlng : null);
            } catch (e) {
                return null;
            }
        };

        let shouldStop = false;
        for (const [typeKey, layerMap] of cache.entries()) {
            if (shouldStop) break;
            if (!(layerMap instanceof Map)) continue;
            for (const [id, pointObj] of layerMap.entries()) {
                const idStr = String(id);
                const rec = STATE.pointIdCache.get(idStr);
                if (!rec) continue;
                if (rec.type && typeKey && String(rec.type) !== String(typeKey)) continue;
                const ll = readLatLng(pointObj);
                if (!ll || !Number.isFinite(ll.lat) || !Number.isFinite(ll.lng)) continue;
                const x = Number(rec.x);
                const y = Number(rec.y);
                if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
                samples.push({ id: idStr, x, y, lat: ll.lat, lng: ll.lng });
                if (samples.length >= MAX_SAMPLES) { shouldStop = true; break; }
            }
        }

        if (samples.length < 3) return false;

        const pickFarthest = (base, list, excludeId) => {
            let best = null;
            let bestD = -1;
            for (const s of list) {
                if (excludeId && s.id === excludeId) continue;
                const dx = s.x - base.x;
                const dy = s.y - base.y;
                const d = dx * dx + dy * dy;
                if (d > bestD) { bestD = d; best = s; }
            }
            return best;
        };

        const a0 = samples[0];
        const a1 = pickFarthest(a0, samples);
        if (!a1) return false;
        const a2 = pickFarthest(a1, samples);
        if (!a2) return false;
        const s1 = a1;
        const s2 = a2;

        const dx = s2.x - s1.x;
        const dy = s2.y - s1.y;
        if (Math.abs(dx) < 1e-9 || Math.abs(dy) < 1e-9) return false;

        const scaleX = (s2.lng - s1.lng) / dx;
        const offsetX = s1.lng - (scaleX * s1.x);
        const scaleY = -(s2.lat - s1.lat) / dy;
        const offsetY = s1.lat + (scaleY * s1.y); // lat = -y*scaleY + offsetY

        if (![scaleX, scaleY, offsetX, offsetY].every(Number.isFinite)) return false;
        if (scaleX <= 0 || scaleY <= 0) return false;

        const thresholdM = samples.length >= 10 ? 2 : 5;
        const errs = [];
        const MAX_CHECK = Math.min(20, samples.length);
        for (let i = 0, seen = 0; i < samples.length && seen < MAX_CHECK; i++) {
            const s = samples[i];
            if (s.id === s1.id || s.id === s2.id) continue;
            const predLng = (s.x * scaleX) + offsetX;
            const predLat = -(s.y * scaleY) + offsetY;
            if (!Number.isFinite(predLat) || !Number.isFinite(predLng)) continue;
            const d = map.distance([predLat, predLng], [s.lat, s.lng]);
            if (Number.isFinite(d)) errs.push(d);
            seen++;
        }
        if (!errs.length) return false;
        errs.sort((aa, bb) => aa - bb);
        const p95 = errs[Math.min(errs.length - 1, Math.floor(errs.length * 0.95))];
        if (!(p95 <= thresholdM)) return false;

        const cur = getCoordTransform();
        const eps = 1e-12;
        const same =
            Math.abs(cur.scaleX - scaleX) < eps &&
            Math.abs(cur.scaleY - scaleY) < eps &&
            Math.abs(cur.offsetX - offsetX) < eps &&
            Math.abs(cur.offsetY - offsetY) < eps;

        if (same) return true;

        persistCoordTransform({ scaleX, scaleY, offsetX, offsetY }, {
            reason: reason || '',
            sampleCount: samples.length,
            thresholdM,
            p95
        });

        const logKey = `updated:${scaleX}:${scaleY}:${offsetX}:${offsetY}:${thresholdM}:${p95}`;
        if (STATE._coordCalibLastLog !== logKey) {
            STATE._coordCalibLastLog = logKey;
            try {
                console.info('[KMP Calib] updated', {
                    scaleX, scaleY, offsetX, offsetY,
                    samples: samples.length,
                    thresholdM,
                    p95
                });
            } catch (e) {}
        }
        return true;
    }

    GM_addStyle(`
        :root {
            --sm-bg: rgba(20, 20, 20, 0.95);
            --sm-border: #444;
            --sm-gold: #dcb268;
            --sm-gold-dim: rgba(220, 178, 104, 0.2);
        }

        body.hide-zoom-control .mc-zoom-control, body.hide-zoom-control .leaflet-control-zoom, body.hide-zoom-control .leaflet-control-container .leaflet-top.leaflet-left .leaflet-control-zoom { display: none !important; visibility: hidden !important; pointer-events: none !important; opacity: 0 !important; }
        body.hide-left-top .left-top-btn-group, body.hide-left-top .left-top-btn, body.hide-left-top .btn-login, body.hide-left-top .batch-point-btn, body.hide-left-top .leaflet-top.leaflet-left > .leaflet-control:not(.leaflet-control-zoom) { display: none !important; }
        body.hide-side-menu .side-menu, body.hide-side-menu .side-menu-panel, body.hide-side-menu .toggle-btn, body.hide-side-menu .mc-gui-panel { display: none !important; width: 0 !important; }
        body.hide-mobile .location-selector, body.hide-mobile .m-right-top-btn-group, body.hide-mobile .mobile-btn-group, body.hide-mobile .mobile-bottom-group, body.hide-mobile .mobile-btn { display: none !important; }
        body.hide-clean-ui .leaflet-top, body.hide-clean-ui .leaflet-bottom { display: none !important; }
        body.hide-switch-tools .switch-tools-cells { display: none !important; }
        body.hide-sync-marker .leaflet-sync-pane .player-marker { display: none !important; visibility: hidden !important; pointer-events: none !important; opacity: 0 !important; }

        #sm-sidebar { position: fixed; top: 0; left: -320px; width: 320px; height: 100vh; background: var(--sm-bg); z-index: 99999; transition: left 0.3s; color: #eee; font-size: 13px; display: flex; flex-direction: column; }
        #sm-sidebar.active { left: 0; }

        #sm-toggle-btn {
            position: fixed;
            top: 20%;
            left: 0;
            width: clamp(20px, 1.5vw, 36px);
            height: clamp(30px, 2.5vw, 54px);
            font-size: clamp(8px, 1vw, 14px);
            background: var(--sm-bg);
            border: 1px solid var(--sm-gold);
            border-left: none;
            border-radius: 0 4px 4px 0;
            z-index: 99999;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--sm-gold);
            transition: left 0.3s cubic-bezier(0.4, 0, 0.2, 1), width 0.2s, height 0.2s;
            box-shadow: 2px 1px 4px rgba(0,0,0,0.3);
        }

        /* 使用通用兄弟选择器，避免在 sidebar 与 toggle 之间插入其它节点（如弹窗 overlay）时失效 */
        #sm-sidebar.active ~ #sm-toggle-btn { left: 320px; }
        #sm-toggle-btn:hover { background: #333; }
        #sm-toggle-btn:active { transform: scale(0.95); }
        .sm-header { padding: 15px; background: #2a2a2a; border-bottom: 1px solid var(--sm-border); font-weight: bold; color: var(--sm-gold); text-align: center; letter-spacing: 1px; font-size: 16px; }
        .sm-content { flex: 1; overflow-y: scroll; padding: 10px; scrollbar-gutter: stable; }

        /* Sidebar 滚动条：常驻 + 黑金配色 */
        #sm-sidebar { scrollbar-width: thin; scrollbar-color: rgba(220, 178, 104, 0.75) rgba(0, 0, 0, 0.65); }
        #sm-sidebar * { scrollbar-width: thin; scrollbar-color: rgba(220, 178, 104, 0.75) rgba(0, 0, 0, 0.65); }
        #sm-sidebar ::-webkit-scrollbar { width: 10px; height: 10px; }
        #sm-sidebar ::-webkit-scrollbar-track { background: rgba(0, 0, 0, 0.65); }
        #sm-sidebar ::-webkit-scrollbar-thumb {
            background: rgba(220, 178, 104, 0.55);
            border-radius: 999px;
            border: 2px solid rgba(0, 0, 0, 0.65);
        }
        #sm-sidebar ::-webkit-scrollbar-thumb:hover { background: rgba(220, 178, 104, 0.8); }
        .sm-section { margin-bottom: 20px; border-bottom: 1px dashed #333; padding-bottom: 10px; }
        .sm-section:last-child { border: none; }
        .sm-section-title { font-size: 12px; color: var(--sm-gold); margin-bottom: 8px; font-weight: bold; display: flex; align-items: center; gap: 5px; }
        .sm-section-title.sm-search-title { justify-content: space-between; gap: 10px; }

        .sm-seg {
            display: inline-flex;
            border: 1px solid #555;
            border-radius: 999px;
            overflow: hidden;
            background: rgba(255,255,255,0.06);
            flex: 0 0 auto;
        }
        .sm-seg-btn {
            appearance: none;
            border: none;
            background: transparent;
            color: #bbb;
            font-size: 11px;
            padding: 4px 10px;
            cursor: pointer;
            user-select: none;
        }
        .sm-seg-btn.active {
            background: var(--sm-gold-dim);
            color: var(--sm-gold);
        }
        .sm-seg-btn:hover { color: #fff; }

        .sm-tabs {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 6px;
            margin-top: 8px;
        }
        .sm-tab-btn {
            background: rgba(255,255,255,0.06);
            border: 1px solid #333;
            color: #bbb;
            border-radius: 6px;
            padding: 6px 0;
            font-size: 11px;
            cursor: pointer;
        }
        .sm-tab-btn.active {
            border-color: var(--sm-gold);
            color: var(--sm-gold);
            background: rgba(220, 178, 104, 0.12);
        }

        .sm-route-square-list {
            margin-top: 8px;
            border: 1px solid #333;
            border-radius: 6px;
            background: #181818;
            max-height: 220px;
            overflow-y: scroll;
            scrollbar-gutter: stable;
        }
        .sm-route-square-item {
            padding: 8px 8px;
            border-bottom: 1px solid #2a2a2a;
            cursor: pointer;
            display: grid;
            grid-template-columns: 1fr auto;
            grid-template-rows: auto auto;
            gap: 2px 8px;
        }
        .sm-route-square-item:last-child { border-bottom: none; }
        .sm-route-title { color: #eee; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .sm-route-sub { color: #777; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .sm-route-metrics {
            color: #999;
            font-size: 10px;
            text-align: right;
            white-space: nowrap;
            display: inline-flex;
            justify-content: flex-end;
            gap: 6px;
        }
        .sm-route-metric-btn {
            appearance: none;
            border: 1px solid transparent;
            background: transparent;
            color: inherit;
            font-size: 10px;
            padding: 1px 4px;
            border-radius: 999px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 2px;
            line-height: 1.2;
        }
        .sm-route-metric-btn:hover { border-color: #444; background: rgba(255,255,255,0.06); color: #ddd; }
        .sm-route-metric-btn.active { border-color: rgba(220, 178, 104, 0.6); background: rgba(220, 178, 104, 0.12); color: var(--sm-gold); }
        .sm-route-metric-btn.danger:hover { border-color: #722; background: rgba(90, 20, 20, 0.25); color: #ff6b6b; }
        .sm-route-metric-btn svg { width: 12px; height: 12px; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
        .sm-route-uploader-id { color: #666; font-size: 10px; text-align: right; white-space: nowrap; }

        .sm-route-footer {
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            gap: 8px;
            margin-top: 8px;
        }
        .sm-page-ctrl { display: inline-flex; align-items: center; gap: 6px; color: #888; font-size: 10px; }
        .sm-page-display {
            padding: 1px 6px;
            border-radius: 4px;
            border: 1px solid transparent;
            color: #ddd;
            cursor: pointer;
            user-select: none;
        }
        .sm-page-ctrl:hover .sm-page-display {
            border-color: #444;
            background: rgba(255,255,255,0.06);
        }
        .sm-page-btn {
            background: #222;
            border: 1px solid #444;
            color: #ccc;
            border-radius: 4px;
            padding: 1px 6px;
            cursor: pointer;
            font-size: 11px;
            line-height: 1.2;
        }
        .sm-page-btn:disabled { opacity: 0.4; cursor: default; }
        .sm-page-input {
            width: 44px;
            padding: 2px 6px;
            border-radius: 4px;
            border: 1px solid #333;
            background: #111;
            color: #ddd;
            font-size: 10px;
            outline: none;
        }
        .sm-sort-group { display: inline-flex; justify-content: flex-end; gap: 6px; }
        .sm-sort-btn {
            background: transparent;
            border: 1px solid #444;
            color: #999;
            border-radius: 999px;
            width: 28px;
            height: 22px;
            padding: 0;
            font-size: 10px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }
        .sm-sort-btn.active { border-color: var(--sm-gold); color: var(--sm-gold); background: rgba(220, 178, 104, 0.12); }
        .sm-sort-btn svg { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }

        .sm-modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.6);
            z-index: 100000;
            display: none;
            align-items: center;
            justify-content: center;
        }
        .sm-modal {
            width: min(520px, calc(100vw - 24px));
            background: rgba(20, 20, 20, 0.98);
            border: 1px solid #666;
            border-radius: 10px;
            box-shadow: 0 10px 24px rgba(0,0,0,0.7);
            color: #eee;
            padding: 14px;
        }
        .sm-modal-title { font-size: 14px; color: var(--sm-gold); font-weight: bold; margin-bottom: 10px; }
        .sm-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
        .sm-modal-btn {
            background: #222;
            border: 1px solid #555;
            color: #ddd;
            border-radius: 6px;
            padding: 6px 12px;
            cursor: pointer;
            font-size: 12px;
        }
        .sm-modal-btn.primary { border-color: var(--sm-gold); color: var(--sm-gold); background: rgba(220, 178, 104, 0.12); }
        .sm-upload-drop {
            width: 100%;
            padding: 12px;
            background: rgba(255,255,255,0.06);
            border: 1px dashed #555;
            border-radius: 8px;
            color: #bbb;
            cursor: pointer;
            text-align: center;
            user-select: none;
        }
        .sm-upload-drop.dragover {
            border-color: var(--sm-gold);
            background: rgba(220, 178, 104, 0.12);
            color: var(--sm-gold);
        }
        .sm-upload-filehint { margin-top: 6px; font-size: 10px; color: #777; }
        .sm-ctrl-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
        .sm-ctrl-label { color: #ccc; }
        .sm-clean-title { justify-content: space-between; gap: 8px; }
        .sm-dropdown-toggle {
            appearance: none;
            width: 18px;
            height: 18px;
            flex: 0 0 auto;
            border: 0;
            background: transparent;
            color: var(--sm-gold);
            cursor: pointer;
            line-height: 1;
            font-size: 12px;
            transform: rotate(0deg);
            transition: transform 0.18s ease, color 0.18s ease;
        }
        .sm-dropdown-toggle.is-open { transform: rotate(90deg); }
        .sm-dropdown-toggle:hover { color: #f0cf8b; }
        .sm-clean-master {
            display: grid;
            grid-template-columns: 18px 1fr auto;
            gap: 4px;
            align-items: center;
            padding: 2px 0 7px;
            border-bottom: 1px solid rgba(220, 178, 104, 0.22);
            margin-bottom: 6px;
            cursor: pointer;
        }
        .sm-clean-master .sm-ctrl-label { color: var(--sm-gold); font-weight: bold; }
        .sm-clean-master .sm-switch { cursor: default; }
        .sm-dropdown-body {
            border-left: 1px solid rgba(220, 178, 104, 0.18);
            margin-left: 4px;
            padding-left: 10px;
            max-height: 150px;
            opacity: 1;
            overflow: hidden;
            transition: max-height 0.2s ease, opacity 0.16s ease, margin-top 0.2s ease;
        }
        .sm-dropdown-body.is-collapsed { max-height: 0; opacity: 0; margin-top: -2px; pointer-events: none; }
        .sm-switch { position: relative; display: inline-block; width: 34px; height: 18px; }
        .sm-switch input { opacity: 0; width: 0; height: 0; }
        .sm-slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #555; transition: .4s; border-radius: 18px; }
        .sm-slider:before { position: absolute; content: ""; height: 14px; width: 14px; left: 2px; bottom: 2px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .sm-slider { background-color: var(--sm-gold); }
        input:checked + .sm-slider:before { transform: translateX(16px); }
        input[type=range] { width: 100%; height: 4px; background: #444; border-radius: 2px; -webkit-appearance: none; margin: 8px 0; }
        input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 12px; height: 12px; background: var(--sm-gold); border-radius: 50%; cursor: pointer; }
        .sm-btn { background: #333; color: var(--sm-gold); border: 1px solid var(--sm-border); padding: 3px 8px; border-radius: 4px; cursor: pointer; transition: all 0.2s; font-size: 12px; line-height: 1.2; flex: 1; text-align: center; white-space: nowrap; }
        .sm-btn:hover { background: #444; border-color: var(--sm-gold); }
        .sm-btn.danger { color: #ff6b6b; border-color: #722; }
        .sm-btn.danger:hover { background: #311; }
        .sm-btn.is-disabled { opacity: 0.55; cursor: pointer; }
        .sm-btn-group { display: flex; gap: 5px; margin-top: 5px; }
        .sm-route-mode-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 6px; }
        .sm-route-mode-row .sm-switch.is-off .sm-slider { background-color: #555 !important; }
        .sm-route-mode-row .sm-switch.is-off .sm-slider:before { transform: translateX(0) !important; }
        .sm-route-mode-row .sm-switch.is-on .sm-slider { background-color: var(--sm-gold) !important; }
        .sm-route-mode-row .sm-switch.is-on .sm-slider:before { transform: translateX(16px) !important; }
        .sm-route-marker-mode { margin-top: 8px; }
        .sm-route-marker-mode .sm-seg { display: flex; width: 100%; margin-top: 5px; border-radius: 5px; }
        .sm-route-marker-mode .sm-seg-btn { flex: 1; padding-left: 4px; padding-right: 4px; }
        .sm-route-nav { display: flex; gap: 5px; margin-top: 6px; }
        .sm-route-nav .sm-btn { flex: 1; }
        .sm-btn:disabled {
            opacity: 0.45;
            cursor: not-allowed;
            filter: grayscale(0.35);
        }
        #sm-route-list { max-height: 150px; overflow-y: scroll; scrollbar-gutter: stable; background: rgba(0,0,0,0.2); border-radius: 4px; padding: 5px; }
        .sm-route-item { display: flex; align-items: center; gap: 6px; padding: 4px; border-bottom: 1px solid #333; }
        .sm-route-sel { flex: 0 0 auto; display: inline-flex; align-items: center; }
        .sm-route-sel input { transform: scale(0.95); }
        .sm-route-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 150px; font-size: 11px; color: #ddd; }
        .sm-route-acts { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; }
        .sm-route-acts button { background: #333; border: 1px solid #555; color: #ccc; cursor: pointer; opacity: 0.7; padding: 2px 6px; border-radius: 4px; font-size: 10px; }
        .sm-route-acts button:hover { opacity: 1; transform: scale(1.05); background: #444; color: #fff; border-color: #666; }
        .sm-route-acts button.del { color: #ff6b6b; border-color: #722; }
        .sm-route-acts button.del:hover { background: #311; color: #ff6b6b; border-color: #f44336; }
        .sm-input { width: 100%; padding: 8px; background: #111; border: 1px solid #444; color: white; border-radius: 4px; margin-bottom: 8px; box-sizing: border-box; }
        .sm-search-results { max-height: 200px; overflow-y: scroll; scrollbar-gutter: stable; background: #181818; border: 1px solid #333; border-radius: 4px; margin-top: 5px; display: none; }
        .sm-result-item { padding: 6px 10px; border-bottom: 1px solid #333; cursor: pointer; }
        .sm-result-item:hover { background: var(--sm-gold-dim); }
        .sm-result-item.active { background: rgba(220, 178, 104, 0.18); outline: 1px solid rgba(220, 178, 104, 0.35); }
        .sm-chip { background: rgba(255,255,255,0.1); padding: 4px 10px; border-radius: 12px; font-size: 11px; white-space: nowrap; cursor: pointer; border: 1px solid transparent; transition: 0.2s; color: #ccc; }
        .sm-chip:hover { border-color: var(--sm-gold); color: var(--sm-gold); background: var(--sm-gold-dim); }
        .sm-idle-top { display:flex; align-items:center; justify-content:space-between; gap:8px; padding: 8px 10px; border-bottom: 1px solid #333; background:#151515; position: sticky; top: 0; z-index: 1; }
        .sm-idle-title { color:#bbb; font-size: 11px; }
        .sm-idle-pager { display:flex; align-items:center; gap:6px; }
        .sm-idle-page { color:#777; font-size: 10px; min-width: 52px; text-align:center; }
        .sm-idle-pager .sm-btn { flex: 0 0 auto; padding: 2px 6px; font-size: 10px; width: auto; }
        .sm-carousel { display: flex; align-items: center; gap: 4px; position: relative; margin-bottom: 10px; }
        .sm-carousel-area { display: flex; gap: 6px; overflow-x: auto; scroll-behavior: smooth; scrollbar-width: none; flex: 1; mask-image: linear-gradient(to right, transparent, black 10px, black 90%, transparent); -webkit-mask-image: linear-gradient(to right, transparent, black 10px, black 90%, transparent); padding: 4px; }
        .sm-carousel-area::-webkit-scrollbar { display: none; }
        .sm-carousel-nav { background: rgba(50,50,50,0.8); border: 1px solid #555; color: var(--sm-gold); width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; font-size: 10px; }
        #sm-drag-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.8); color: var(--sm-gold); font-size: 24px; font-weight: bold; z-index: 100000; display: none; align-items: center; justify-content: center; border: 5px dashed var(--sm-gold); pointer-events: none; }

        #kmp-sidecar {
            position: absolute !important;
            top: 0 !important;
            left: 100% !important;
            margin-left: 10px !important;
            width: 240px !important;
            background: rgba(20, 20, 20, 0.95) !important;
            border: 1px solid #666 !important;
            border-radius: 8px !important;
            box-shadow: 0 4px 12px rgba(0,0,0,0.8) !important;
            color: #ececec !important;
            font-family: sans-serif !important;
            font-size: 13px !important;
            z-index: 99999 !important;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            backdrop-filter: blur(5px);
            pointer-events: auto !important;
            min-height: 150px;
            transition: opacity 0.1s ease-out;
            opacity: 1;
        }

        .leaflet-popup, .leaflet-popup-content-wrapper, .leaflet-popup-content {
            overflow: visible !important;
        }

        .kmp-header { padding: 12px; background: #2a2a2a; border-bottom: 1px solid #444; font-weight: bold; color: #dcb268; display: flex; justify-content: space-between; align-items: center; }
        .kmp-body { padding: 12px; flex: 1; }
        .kmp-btn { width: 100%; padding: 8px; margin-top: 10px; background: linear-gradient(to right, #dcb268, #c09440); border: none; border-radius: 4px; color: #000; font-weight: bold; cursor: pointer; }
        .kmp-btn:hover { opacity: 0.9; }

        .kmp-tag {
            background: rgba(220, 178, 104, 0.2);
            border: 1px solid #dcb268;
            color: #dcb268;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 11px;
        }

        .kmp-chip {
            background: rgba(255,255,255,0.1); color: #ccc;
            padding: 4px 8px; border-radius: 12px; font-size: 11px;
            white-space: nowrap; cursor: pointer; border: 1px solid transparent;
            transition: all 0.2s;
        }
        .kmp-chip:hover { border-color: #dcb268; color: #dcb268; background: rgba(220, 178, 104, 0.1); }

        .kmp-hot-carousel {
            display: flex; align-items: center; gap: 4px;
            width: 100%; position: relative;
        }

        .kmp-hot-scroll-area {
            display: flex; gap: 6px;
            overflow-x: auto;
            scroll-behavior: smooth;
            scrollbar-width: none;
            flex: 1;
            padding: 4px 2px;
            mask-image: linear-gradient(to right, transparent, black 10px, black 90%, transparent);
            -webkit-mask-image: linear-gradient(to right, transparent, black 10px, black 90%, transparent);
        }
        .kmp-hot-scroll-area::-webkit-scrollbar { display: none; }

        .kmp-carousel-btn {
            background: rgba(50,50,50,0.8); border: 1px solid #555; color: #dcb268;
            width: 20px; height: 20px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; font-size: 10px; flex-shrink: 0;
            z-index: 2; user-select: none;
        }
        .kmp-carousel-btn:hover { background: #dcb268; color: #000; }
        .kmp-carousel-btn:disabled { opacity: 0.3; cursor: default; border-color: #333; color: #555; background: transparent; }

        #kmp-bottom-bar {
            position: absolute;
            bottom: -50px; left: -20px;
            width: 160%;
            height: 40px;
            background: rgba(0,0,0,0.85);
            backdrop-filter: blur(4px);
            border-radius: 20px;
            display: flex; align-items: center; padding: 0 15px;
            z-index: 99990;
            border: 1px solid #444;
            box-shadow: 0 4px 10px rgba(0,0,0,0.5);

            opacity: 0; animation: slideUp 0.3s forwards 0.2s;
        }
        @keyframes slideUp { from {opacity:0; transform:translateY(10px);} to {opacity:1; transform:translateY(0);} }

        .kmp-tag-row {
            display: flex; justify-content: space-between; align-items: center;
            padding: 6px 4px;
            border-bottom: 1px dashed #333;
            animation: fadeIn 0.2s;
        }
        .kmp-tag-row:last-child { border-bottom: none; }

        .kmp-tag-text { display:flex; flex-direction:column; gap:2px; overflow:hidden; max-width: 130px; }
        .kmp-tag-title { font-size: 13px; color: #dcb268; font-weight: 500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .kmp-tag-author { font-size: 10px; color: #666; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

        .kmp-tag-acts { display: flex; align-items: center; gap: 4px; }

        .kmp-icon-btn {
            background: transparent; border: 1px solid #444; color: #666;
            width: 24px; height: 24px; border-radius: 4px;
            cursor: pointer; display: flex; align-items: center; justify-content: center;
            font-size: 10px; padding: 0;
            transition: all 0.1s;
        }
        .kmp-icon-btn:hover { border-color: #888; color: #aaa; }
        .kmp-icon-btn.active[data-act="up"] { border-color: #4caf50; background: rgba(76,175,80,0.1); color: #4caf50; }
        .kmp-icon-btn.active[data-act="down"] { border-color: #f44336; background: rgba(244,67,54,0.1); color: #f44336; }
        .kmp-icon-btn.active[data-act="delete"] { border-color: #f44336; background: rgba(244,67,54,0.1); color: #f44336; }
        .kmp-icon-btn:disabled { opacity: 0.25; cursor: not-allowed; }

        .kmp-btn-full {
            width: 100%; padding: 8px; background: #333; border: 1px solid #444; color: #ccc;
            border-radius: 4px; cursor: pointer; font-size: 12px;
        }
        .kmp-btn-full:hover { background: #444; color: #fff; }

        .kmp-page-btn {
            background: #222; border: 1px solid #444; color: #aaa;
            width: 24px; height: 24px; border-radius: 4px; cursor: pointer;
        }
        .kmp-page-btn:disabled { opacity: 0.3; cursor: default; }

        .kmp-input {
            width: 100%; background: #111; border: 1px solid #dcb268; color: #fff;
            padding: 6px; border-radius: 4px; font-size: 12px;
        }

        .kmp-loading-spinner {
            display: inline-block; animation: spin 1s linear infinite; margin-right: 5px; font-weight: bold;
        }
        @keyframes spin { 100% { transform: rotate(360deg); } }

        .leaflet-kmp-edit-line-pane,
        .leaflet-kmp-edit-marker-pane {
            pointer-events: none !important;
        }

        .leaflet-kmp-edit-line-pane svg {
            pointer-events: none !important;
        }

        path.kmp-hit-line {
            cursor: copy !important;
            pointer-events: stroke !important;
            stroke-opacity: 0;
            stroke: #ffffff;
            transition: stroke-opacity 0.2s ease;
        }

        path.kmp-hit-line:hover {
            stroke-opacity: 0.5 !important;
            stroke-width: 20px;
        }

        .kmp-edit-handle-icon {
            cursor: grab !important;
            pointer-events: auto !important;
        }
        .kmp-edit-handle-visual {
            background: #fff;
            border: 2px solid #000;
            border-radius: 50%;
            box-shadow: 0 0 4px rgba(0,0,0,0.8);
            width: 100%; height: 100%;
            transition: transform 0.1s;
        }
        .kmp-edit-handle-icon:hover .kmp-edit-handle-visual {
            transform: scale(1.5);
            background: #dcb268;
        }
        .kmp-edit-handle-icon.kmp-selected-node .kmp-edit-handle-visual {
            background: #ffffff !important;
            border-color: #dcb268;
            box-shadow: 0 0 0 4px rgba(220,178,104,0.35), 0 0 10px rgba(220,178,104,0.9);
            transform: scale(1.35);
        }
        .kmp-edit-handle-icon.kmp-connect-source .kmp-edit-handle-visual {
            background: #dcb268 !important;
            border-color: #fff;
            box-shadow: 0 0 0 5px rgba(220,178,104,0.35), 0 0 16px rgba(220,178,104,1);
            transform: scale(1.45);
        }
        .kmp-edit-handle-icon.kmp-connect-target .kmp-edit-handle-visual {
            background: #82d982 !important;
            border-color: #fff;
            box-shadow: 0 0 0 5px rgba(130,217,130,0.32), 0 0 16px rgba(130,217,130,0.9);
            transform: scale(1.45);
        }
        .kmp-edit-node-coordinate {
            position: absolute;
            top: calc(100% + 4px);
            left: 50%;
            transform: translateX(-50%);
            color: #fff;
            font-size: 11px;
            line-height: 1;
            white-space: nowrap;
            text-shadow: 0 1px 3px #000;
            pointer-events: none;
        }

        path.kmp-selected-edge {
            stroke-opacity: 0.9 !important;
            stroke: #dcb268 !important;
            stroke-width: 14px !important;
        }
        path.kmp-hover-edge {
            stroke-opacity: 0.75 !important;
            stroke: #ffffff !important;
            stroke-width: 18px !important;
        }
        .kmp-edit-arrow {
            display: flex;
            filter: drop-shadow(0 0 4px rgba(0,0,0,0.9));
        }
        .kmp-route-arrow svg {
            width: 100%;
            height: 100%;
            display: block;
            overflow: visible;
        }
        .kmp-edit-arrow.selected,
        .kmp-edit-arrow.hover {
            transform: scale(1.2);
        }
        .kmp-connect-preview {
            stroke: #dcb268;
            stroke-width: 3;
            stroke-dasharray: 8 8;
            opacity: 0.9;
            pointer-events: none;
        }

        #kmp-graph-edit-toolbar {
            position: fixed;
            left: 50%;
            bottom: 24px;
            transform: translateX(-50%);
            z-index: 100002;
            display: none;
            align-items: center;
            gap: 8px;
            padding: 8px 10px;
            border: 1px solid rgba(220,178,104,0.45);
            border-radius: 8px;
            background: rgba(18,18,18,0.92);
            box-shadow: 0 10px 30px rgba(0,0,0,0.45);
            color: #ddd;
            font-size: 12px;
            backdrop-filter: blur(10px);
        }
        #kmp-graph-edit-toolbar button,
        #kmp-graph-edit-toolbar label {
            height: 28px;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 0 9px;
            border-radius: 6px;
            border: 1px solid #444;
            background: #242424;
            color: #ddd;
            cursor: pointer;
            white-space: nowrap;
            user-select: none;
        }
        #kmp-graph-edit-toolbar button:hover,
        #kmp-graph-edit-toolbar label:hover {
            border-color: #dcb268;
            color: #fff;
        }
        #kmp-graph-edit-toolbar button.active,
        #kmp-graph-edit-toolbar label.active {
            border-color: #dcb268;
            background: rgba(220,178,104,0.18);
            color: #f7e5be;
        }
        #kmp-graph-edit-toolbar button.danger {
            border-color: rgba(211,47,47,0.65);
            color: #ffb8b8;
        }
        #kmp-graph-edit-toolbar .kmp-toolbar-status {
            min-width: 84px;
            color: #f7e5be;
            text-align: center;
        }
        #kmp-graph-edit-toolbar .kmp-toolbar-commit-group {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            margin-left: 4px;
            padding: 4px 5px 4px 12px;
            border-left: 2px solid rgba(220,178,104,0.65);
            border-radius: 0 6px 6px 0;
            background: rgba(255,255,255,0.06);
        }
        #kmp-toolbar-save { border-color: #4caf50 !important; color: #8ee694 !important; }
        #kmp-toolbar-cancel { border-color: #ff9800 !important; color: #ffc166 !important; }
        #kmp-graph-edit-toolbar input { margin: 0; }
        #kmp-graph-edit-help {
            position: fixed;
            right: 18px;
            bottom: 78px;
            z-index: 100001;
            display: none;
            max-width: 260px;
            padding: 10px 12px;
            border: 1px solid rgba(255,255,255,0.16);
            border-radius: 8px;
            background: rgba(18,18,18,0.86);
            color: #cfcfcf;
            font-size: 12px;
            line-height: 1.65;
            box-shadow: 0 10px 28px rgba(0,0,0,0.35);
            backdrop-filter: blur(8px);
            pointer-events: none;
            white-space: pre-line;
        }

        .kmp-edit-popup { font-size: 12px; color: #ccc; min-width: 140px; }
        .kmp-node-edit-actions {
            width: 88px;
        }
        .kmp-node-edit-actions .kmp-edit-input {
            width: 62px;
        }
        .kmp-node-edit-actions .kmp-edit-popup-btn {
            width: 74px;
            padding-left: 0;
            padding-right: 0;
        }
        #kmp-special-marker-sidebar {
            position: fixed;
            top: 76px;
            right: 18px;
            bottom: 78px;
            z-index: 100003;
            display: none;
            width: 340px;
            overflow: hidden;
            border: 1px solid rgba(220,178,104,0.55);
            border-radius: 12px;
            background: rgba(18,18,18,0.94);
            color: #eee;
            box-shadow: 0 18px 45px rgba(0,0,0,0.48);
            backdrop-filter: blur(10px);
        }
        .kmp-special-sidebar-layout { display:grid; grid-template-rows:auto minmax(0,1fr) auto; height:100%; }
        .kmp-special-sidebar-header,
        .kmp-special-summary-header { display:flex; align-items:center; justify-content:space-between; gap:8px; }
        .kmp-special-sidebar-header { padding:12px; border-bottom:1px solid rgba(255,255,255,0.1); font-weight:800; }
        .kmp-special-sidebar-tree { overflow:auto; padding:8px; }
        .kmp-special-group { margin-bottom:8px; border:1px solid rgba(255,255,255,0.12); border-radius:8px; background:rgba(255,255,255,0.035); }
        .kmp-special-group.selected { border-color:#dcb268; }
        .kmp-special-group summary { padding:9px 10px; cursor:pointer; user-select:none; font-weight:700; }
        .kmp-special-group-actions { display:flex; gap:5px; flex-wrap:wrap; padding:0 9px 9px; }
        .kmp-special-sidebar-btn,
        .kmp-special-member-btn,
        .kmp-special-modal-btn { border:1px solid #666; border-radius:6px; background:#282828; color:#eee; padding:5px 8px; cursor:pointer; }
        .kmp-special-sidebar-btn:hover,
        .kmp-special-member-btn:hover,
        .kmp-special-modal-btn:hover { border-color:#dcb268; }
        .kmp-special-sidebar-btn.active { border-color:#4caf50; color:#9bea9f; background:rgba(76,175,80,0.16); }
        .kmp-special-sidebar-btn.danger,
        .kmp-special-member-btn.danger { border-color:rgba(211,47,47,0.7); color:#ffb8b8; }
        .kmp-special-member-list { padding:0 9px 9px; }
        .kmp-special-member-row { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:7px; padding:6px 0; border-top:1px solid rgba(255,255,255,0.08); }
        .kmp-special-member-actions { display:flex; gap:4px; }
        .kmp-special-member-btn { padding:3px 6px; font-size:11px; }
        .kmp-special-empty { padding:16px 10px; color:#999; text-align:center; }
        .kmp-special-sidebar-summary { padding:12px; border-top:1px solid rgba(255,255,255,0.12); background:rgba(0,0,0,0.18); }
        .kmp-special-summary-body { display:flex; align-items:center; gap:14px; margin-top:10px; }
        .kmp-special-summary-meta { min-width:0; color:#bbb; font-size:12px; line-height:1.6; }
        #kmp-special-marker-style-modal {
            position:fixed; inset:0; z-index:100020; display:flex; align-items:center; justify-content:center;
            padding:28px; background:rgba(0,0,0,0.68); color:#eee;
        }
        .kmp-special-modal-panel { width:min(920px, calc(100vw - 56px)); max-height:calc(100vh - 56px); overflow:auto; border:1px solid rgba(220,178,104,0.65); border-radius:14px; background:#171717; box-shadow:0 28px 80px rgba(0,0,0,0.65); }
        .kmp-special-modal-header { padding:16px 20px; border-bottom:1px solid rgba(255,255,255,0.12); font-size:18px; font-weight:800; }
        .kmp-special-modal-body { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(280px,0.8fr); gap:22px; padding:20px; }
        .kmp-special-modal-section { margin-bottom:18px; }
        .kmp-special-modal-label { display:block; margin-bottom:8px; color:#d9c08d; font-weight:700; }
        .kmp-special-shape-grid { display:grid; grid-template-columns:repeat(4,minmax(86px,1fr)); gap:8px; }
        .kmp-special-shape-option { display:flex; flex-direction:column; align-items:center; gap:7px; min-height:88px; padding:8px 5px; border:1px solid #555; border-radius:8px; background:#232323; color:#ddd; cursor:pointer; }
        .kmp-special-shape-option.active { border-color:#dcb268; box-shadow:0 0 0 2px rgba(220,178,104,0.22); }
        .kmp-special-number-row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
        .kmp-special-number-input { width:100%; box-sizing:border-box; border:1px solid #666; border-radius:6px; background:#252525; color:#fff; padding:7px 8px; }
        .kmp-special-preview-stage { min-height:170px; display:flex; align-items:center; justify-content:center; border:1px solid rgba(255,255,255,0.12); border-radius:10px; background:radial-gradient(circle at center,#353535,#202020); }
        .kmp-special-modal-actions { display:flex; justify-content:flex-end; gap:10px; padding:14px 20px 18px; border-top:1px solid rgba(255,255,255,0.12); }
        .kmp-special-modal-btn.primary { border-color:#dcb268; background:#dcb268; color:#161616; font-weight:800; }
        .kmp-special-color-picker { display:grid; gap:9px; }
        .kmp-color-sv { position:relative; height:150px; border-radius:8px; overflow:hidden; cursor:crosshair; background-image:linear-gradient(to top,#000,transparent),linear-gradient(to right,#fff,transparent); touch-action:none; }
        .kmp-color-sv-cursor { position:absolute; width:14px; height:14px; border:2px solid #fff; border-radius:50%; box-shadow:0 0 0 1px #000; transform:translate(-50%,-50%); pointer-events:none; }
        .kmp-color-hue {
            width:100%; height:16px; margin:0; cursor:pointer; background:transparent;
            -webkit-appearance: none; appearance: none;
        }
        .kmp-color-hue::-webkit-slider-runnable-track {
            height:10px; border-radius:999px;
            background: linear-gradient(to right, #f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00);
        }
        .kmp-color-hue::-webkit-slider-thumb {
            width:16px; height:16px; margin-top:-3px; border:2px solid #fff; border-radius:50%;
            background:#222; box-shadow:0 1px 4px rgba(0,0,0,0.65);
            -webkit-appearance: none; appearance: none;
        }
        .kmp-color-row { display:grid; grid-template-columns:34px minmax(0,1fr); align-items:center; gap:8px; }
        .kmp-color-preview { width:32px; height:32px; border:1px solid rgba(255,255,255,0.65); border-radius:6px; }
        .kmp-color-hex { width:100%; box-sizing:border-box; border:1px solid #666; border-radius:6px; background:#252525; color:#fff; padding:7px 8px; font-family:monospace; }
        .kmp-route-node-style {
            position: relative;
            width: 28px;
            height: 28px;
            transform-origin: center;
            filter: drop-shadow(0 1px 3px rgba(0,0,0,0.75));
            pointer-events: none;
        }
        .kmp-route-node-core {
            position: absolute;
            inset: 1px;
            background: var(--node-color);
            border: 1.5px solid #fff;
            box-sizing: border-box;
        }
        .kmp-special-marker-shape.circle {
            border-radius: 50%;
        }
        .kmp-special-marker-shape.square {
            border-radius: 0;
        }
        .kmp-special-marker-shape.rounded-square {
            border-radius: 6px;
        }
        .kmp-special-marker-shape.diamond {
            inset: 4px;
            transform: rotate(45deg);
        }
        .kmp-special-marker-shape.triangle-up {
            clip-path: polygon(50% 0%, 100% 100%, 0% 100%);
        }
        .kmp-special-marker-shape.triangle-down {
            clip-path: polygon(0% 0%, 100% 0%, 50% 100%);
        }
        .kmp-special-marker-shape.pentagon {
            clip-path: polygon(50% 0%, 100% 38%, 82% 100%, 18% 100%, 0% 38%);
        }
        .kmp-special-marker-shape.hexagon {
            clip-path: polygon(25% 0%, 75% 0%, 100% 50%, 75% 100%, 25% 100%, 0% 50%);
        }
        .kmp-special-marker-shape.octagon {
            clip-path: polygon(30% 0%, 70% 0%, 100% 30%, 100% 70%, 70% 100%, 30% 100%, 0% 70%, 0% 30%);
        }
        .kmp-special-marker-shape.star {
            clip-path: polygon(50% 0%, 61% 34%, 98% 34%, 68% 55%, 79% 90%, 50% 69%, 21% 90%, 32% 55%, 2% 34%, 39% 34%);
        }
        .kmp-special-marker-shape.ellipse {
            inset: 5px 1px;
            border-radius: 50%;
        }
        .kmp-special-marker-shape.capsule {
            inset: 6px 1px;
            border-radius: 999px;
        }
        .kmp-special-marker-preview { width:64px; height:64px; flex:0 0 64px; }
        .kmp-special-marker-preview .kmp-special-marker-shape.diamond { inset:10px; }
        .kmp-special-marker-preview .kmp-special-marker-shape.ellipse { inset:12px 2px; }
        .kmp-special-marker-preview .kmp-special-marker-shape.capsule { inset:15px 2px; }
        .kmp-special-shape-option .kmp-special-marker-preview { width:40px; height:40px; flex-basis:40px; }
        .kmp-special-shape-option .kmp-special-marker-shape.diamond { inset:7px; }
        .kmp-route-node-text {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #111;
            font-size: 11px;
            font-weight: 900;
            line-height: 1;
            text-align: center;
            white-space: nowrap;
            text-shadow: 0 1px 0 rgba(255,255,255,0.55);
        }
        .kmp-edit-input {
            background: #222; border: 1px solid #dcb268; color: #fff;
            width: 80px; padding: 3px; border-radius: 3px; margin-left: 5px;
        }
        .kmp-edit-popup-btn {
            background: #dcb268; color: #000; border: none;
            padding: 5px 10px; border-radius: 4px; cursor: pointer;
            font-weight: bold; width: 100%; margin-top: 6px;
        }
        .kmp-edit-popup-btn.danger { background: #d32f2f; color: #fff; }
        .kmp-edit-popup-btn:hover { opacity: 0.9; }

        .kmp-crosshair-cursor {
            cursor: crosshair !important;
        }
        .leaflet-interactive.kmp-select-box {
            stroke: #f44336;
            stroke-width: 2;
            fill: #f44336;
            fill-opacity: 0.2;
            pointer-events: none;
        }
    `);

    const originalDrawImage = CanvasRenderingContext2D.prototype.drawImage;
    CanvasRenderingContext2D.prototype.drawImage = function(image, ...args) {
        if (!STATE.toggles.markerOptimization) {
            return originalDrawImage.apply(this, [image, ...args]);
        }
        const srcW = image.width;
        const srcH = image.height;
        if (!srcW || !srcH) return originalDrawImage.apply(this, [image, ...args]);

        if (srcW === 112 && srcH === 136) return;

        let drawW = srcW, drawH = srcH, dyIndex = 1;
        if (args.length === 4) { drawW = args[2]; drawH = args[3]; dyIndex = 1; }
        else if (args.length >= 8) { drawW = args[6]; drawH = args[7]; dyIndex = 5; }

        if (drawW > 200 || drawH > 200) return originalDrawImage.apply(this, [image, ...args]);

        try {
            const currentTransform = this.getTransform();
            this.restore(); this.save();
            this.setTransform(currentTransform);
            this.globalCompositeOperation = 'source-over';
        } catch (e) {}

        let newArgs = [...args];
        if (typeof newArgs[dyIndex] === 'number') {
            newArgs[dyIndex] += CONFIG.canvas.offsetY;
        }

        return originalDrawImage.apply(this, [image, ...newArgs]);
    };

    function hookNetwork() {
        const shouldProcessUrl = (url) => url.includes('/position.json') || url.includes('/getDetail');
        const processUrlData = (url, data) => {
            if (url.includes('/position.json')) processBulkData(data);
            else if (url.includes('/getDetail')) processDetailData(data);
        };
        installTileMetadataResourceObserver();

        const originalFetch = globalScope.fetch;
        globalScope.fetch = function(input, init) {
            const url = (typeof input === 'string' ? input : input.url) || '';
            observeTileMetadataUrl(url);
            if (shouldProcessUrl(url)) {
                return originalFetch.apply(this, arguments).then(response => {
                    if (!response.ok) return response;
                    const cType = response.headers.get('content-type');
                    if (cType && cType.includes('application/json')) {
                        response.clone().json().then(data => {
                            processUrlData(url, data);
                        }).catch(e => {});
                    }
                    return response;
                });
            }
            return originalFetch.apply(this, arguments);
        };

        const originalOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            observeTileMetadataUrl(url);
            this.addEventListener('load', function() {
                if (this.status === 200) {
                    try {
                        if (shouldProcessUrl(url)) processUrlData(url, JSON.parse(this.responseText));
                    } catch (e) {}
                }
            });
            return originalOpen.apply(this, arguments);
        };
    }

    const interceptMap = () => {
        console.log("[GM] Map interceptor started");
        function captureMapInstance(map, source) {
            if (!map) return false;
            if (STATE.mapInstance === map && STATE.mainLayerGroup && STATE.mainLayerGroup._map === map) return true;
            console.log(`%c[GM] Map instance captured via ${source}!`, "color: #00ff00; font-weight: bold;");
            STATE.mapInstance = map;
            if (typeof window !== 'undefined') window.discoveredMap = map;
            initMapLogic(map);
            return true;
        }
        // Try immediately first
        const tryPatch = () => {
            // 1. Check if already discovered by universal injector
            if (window.discoveredMap) {
                const LL = (globalScope && globalScope.L) ? globalScope.L : (typeof window !== 'undefined' ? window.L : null);
                if (LL) L = LL;
                if (captureMapInstance(window.discoveredMap, 'window.discoveredMap')) return true;
            }

            const LL = (globalScope && globalScope.L) ? globalScope.L : (typeof window !== 'undefined' ? window.L : null);
            if (typeof LL === 'object' && LL.Map && LL.Map.prototype.initialize) {
                L = LL;

                // 2. Patch prototype if not already done by US
                if (!LL.Map.prototype.initialize._patched) {
                    console.log("[GM] Patching L.Map.prototype.initialize...");
                    const originalInitialize = LL.Map.prototype.initialize;
                    LL.Map.prototype.initialize = function(...args) {
                        const map = originalInitialize.apply(this, args);
                        captureMapInstance(this, 'constructor');
                        return map;
                    };
                    LL.Map.prototype.initialize._patched = true;
                }

                // 3. Last resort: Look for existing map objects in common places or DOM
                // (Leaflet doesn't have a global registry, but we can check if window.map exists)
                if (window.map && window.map instanceof LL.Map) {
                    if (captureMapInstance(window.map, 'window.map')) return true;
                }
            }
            return false;
        };

        if (tryPatch()) return;

        const check = setInterval(() => {
            resourceProbeCount('map_intercept.tick');
            if (tryPatch()) {
                clearInterval(check);
            }
        }, 500);
    };

    function initMapLogic(map) {
        if (STATE.mainLayerGroup) {
            if (STATE.mainLayerGroup._map === map) return;
            try {
                if (STATE.mainLayerGroup._map && typeof STATE.mainLayerGroup._map.removeLayer === 'function') {
                    STATE.mainLayerGroup._map.removeLayer(STATE.mainLayerGroup);
                }
            } catch (e) {}
            STATE.mainLayerGroup = null;
        }
        if (STATE.routeMarkerHighlightLayer) {
            try {
                if (STATE.routeMarkerHighlightLayer._map) STATE.routeMarkerHighlightLayer._map.removeLayer(STATE.routeMarkerHighlightLayer);
            } catch (e) {}
            STATE.routeMarkerHighlightLayer = null;
        }
        uninstallRouteMarkerAssociationCapture();

        STATE.mainLayerGroup = L.layerGroup().addTo(map);

        if (!map.getPane('kmp-arrow-pane')) {
            map.createPane('kmp-arrow-pane');
        }
        const arrowPane = map.getPane('kmp-arrow-pane');
        arrowPane.style.zIndex = KMP_ARROW_PANE_Z_INDEX; arrowPane.style.pointerEvents = 'none';
        if (!map.getPane('kmp_highlight_pane')) {
            map.createPane('kmp_highlight_pane');
            const p = map.getPane('kmp_highlight_pane');
            p.style.zIndex = 450; p.style.pointerEvents = 'none';
        }

        map.on('popupopen', handlePopupOpen);
        map.on('popupclose', handlePopupClose);
        installMapControlApi();

        createUnifiedUI();
        setupDragAndDrop();
        setupPopupDomWatcher();
        scheduleAutoCalibrate('initMapLogic');
        scheduleRouteMarkerDisplay('map-instance-change');
    }

    function isPointPopupOpenForControl() {
        return !!findActivePointPopup();
    }

    function shouldPauseTrackingMove() {
        return STATE.toggles.pauseTrackingWhenPopupOpen && isPointPopupOpenForControl();
    }

    function mapControlFailure(reason, extra = {}) {
        return Object.assign({ ok: false, reason }, extra);
    }

    function mapControlSuccess(extra = {}) {
        return Object.assign({ ok: true }, extra);
    }

    function setViewViaControl(map, latNum, lngNum) {
        try {
            map.setView([latNum, lngNum]);
            return mapControlSuccess({ action: 'jumpToLatLng' });
        } catch (e) {
            if (STATE.mapInstance === map) STATE.mapInstance = null;
            if (typeof window !== 'undefined' && window.discoveredMap === map) window.discoveredMap = null;
            return mapControlFailure('map_setview_exception', {
                name: e && e.name ? String(e.name) : '',
                message: e && e.message ? String(e.message) : String(e || ''),
                stack: e && e.stack ? String(e.stack) : ''
            });
        }
    }

    function jumpToLatLngViaControl(lat, lng, options = {}) {
        let map = STATE.mapInstance;
        if (!map || typeof map.setView !== 'function') return mapControlFailure('map_not_ready');
        if (options && options.source === 'tracking' && shouldPauseTrackingMove()) return mapControlFailure('point_popup_open');

        const latNum = Number(lat);
        const lngNum = Number(lng);
        if (!Number.isFinite(latNum) || !Number.isFinite(lngNum)) return mapControlFailure('invalid_latlng');

        const LL = getLeafletForRecapture();
        if (!isUsableMapCandidate(map, LL)) {
            const recaptured = recaptureMapViaControl();
            if (!recaptured || !recaptured.captured) return mapControlFailure('map_not_ready');
            map = STATE.mapInstance;
            if (!isUsableMapCandidate(map, LL)) return mapControlFailure('map_not_ready');
        }
        return setViewViaControl(map, latNum, lngNum);
    }

    function jumpToGameViaControl(x, y, options = {}) {
        const latLng = gameToLatLng(x, y);
        if (!latLng) return mapControlFailure('invalid_game_coord');
        return jumpToLatLngViaControl(latLng[0], latLng[1], options);
    }

    function zoomViaControl(delta, options = {}) {
        const map = STATE.mapInstance;
        if (!map) return mapControlFailure('map_not_ready');

        const amount = Number(delta);
        if (!Number.isFinite(amount) || amount === 0) return mapControlFailure('invalid_zoom_delta');

        if (amount > 0 && typeof map.zoomIn === 'function') {
            map.zoomIn(Math.abs(amount));
            return mapControlSuccess({ action: 'zoomIn' });
        }
        if (amount < 0 && typeof map.zoomOut === 'function') {
            map.zoomOut(Math.abs(amount));
            return mapControlSuccess({ action: 'zoomOut' });
        }
        return mapControlFailure('zoom_not_supported');
    }

    function getLeafletForRecapture() {
        const LL = (globalScope && globalScope.L) ? globalScope.L : (typeof window !== 'undefined' ? window.L : null);
        if (LL) L = LL;
        return LL;
    }

    function hasUsableMapPane(map) {
        if (!map) return false;
        try {
            if (typeof map.getContainer === 'function') {
                const container = map.getContainer();
                if (!container || container.isConnected === false) return false;
            }
            let pane = null;
            if (typeof map.getPane === 'function') pane = map.getPane('mapPane');
            if (!pane && map._mapPane) pane = map._mapPane;
            if (!pane || pane.isConnected === false) return false;
            return true;
        } catch (e) {
            return false;
        }
    }

    function isUsableMapCandidate(map, LL) {
        if (!map || typeof map.setView !== 'function') return false;
        if (!hasUsableMapPane(map)) return false;
        if (LL && LL.Map && map instanceof LL.Map) return true;
        if (typeof map.getContainer === 'function') {
            try {
                const container = map.getContainer();
                if (container && container.isConnected === false) return false;
            } catch (e) {
                return false;
            }
        }
        return typeof map.addLayer === 'function';
    }

    function recaptureMapViaControl() {
        const LL = getLeafletForRecapture();
        STATE.mapInstance = null;

        const candidates = [];
        if (typeof window !== 'undefined') {
            candidates.push(window.map);
            candidates.push(window.discoveredMap);
        }

        for (const candidate of candidates) {
            if (!isUsableMapCandidate(candidate, LL)) continue;
            STATE.mapInstance = candidate;
            if (typeof window !== 'undefined') window.discoveredMap = candidate;
            initMapLogic(candidate);
            return mapControlSuccess({ action: 'recaptureMap', captured: true });
        }

        interceptMap();
        return mapControlSuccess({ action: 'recaptureMap', captured: false });
    }

    function handleMapControlCommand(command) {
        const cmd = command || {};
        const options = { source: cmd.source || 'manual' };

        if (cmd.type === 'jumpToGame') {
            const latLng = gameToLatLng(cmd.x, cmd.y);
            if (!latLng) return mapControlFailure('invalid_game_coord');
            return jumpToLatLngViaControl(latLng[0], latLng[1], options);
        }
        if (cmd.type === 'jumpToLatLng') return jumpToLatLngViaControl(cmd.lat, cmd.lng, options);
        if (cmd.type === 'zoom') return zoomViaControl(cmd.delta, options);
        if (cmd.type === 'recaptureMap') return recaptureMapViaControl();
        if (cmd.type === 'isPointPopupOpen') return mapControlSuccess({ open: isPointPopupOpenForControl() });
        if (cmd.type === 'getMapContext') return mapControlSuccess({ data: getMapContext() });
        if (cmd.type === 'getTileMetadataSnapshot') return mapControlSuccess({ data: getTileMetadataSnapshot() });

        return mapControlFailure('unknown_command');
    }

    function installMapControlApi() {
        const api = {
            handleCommand: handleMapControlCommand,
            jumpToGame: jumpToGameViaControl,
            jumpToLatLng: jumpToLatLngViaControl,
            zoom: zoomViaControl,
            recaptureMap: recaptureMapViaControl,
            isPointPopupOpen: isPointPopupOpenForControl,
            getMapContext: getMapContext,
            getTileMetadataSnapshot: getTileMetadataSnapshot
        };
        globalScope.__WuwaMapControl = api;
        if (typeof window !== 'undefined') window.__WuwaMapControl = api;
    }

    // ==============================
    // 坐标系统约定（强制统一，不做“猜测”）
    // ==============================
    // - Leaflet 坐标：lat/lng（地图渲染坐标）
    // - Game 坐标：浮点（官方接口/导入路线使用）
    // - JSON 坐标：数值（约定为 Game * 100，用于 fingerprint/持久化/精确匹配；来源数据可能带小数）

    // Game(Float) -> JSON(Int)
    const gameToJsonInt = (gameFloat) => Math.round(Number(gameFloat) * 100);

    // JSON(Int/Number) -> Game(Float)
    const jsonToGameFloat = (jsonNumber) => Number(jsonNumber) / 100;

    // 输入一律按 JSON(Number) 解析（不做“猜测”）
    function coerceJsonCoord(raw) {
        const n = Number(raw);
        if (!Number.isFinite(n)) return NaN;
        return n;
    }

    // 用于 fingerprint 的“稳定化”坐标：对 JSON 坐标进行取整（避免浮点抖动导致 key 漂移）
    function coerceFpCoord(raw) {
        const n = coerceJsonCoord(raw);
        return Number.isFinite(n) ? Math.round(n) : NaN;
    }

    // JSON(Int) -> Leaflet(lat,lng)（使用可持久化覆盖的变换参数）
    function jsonIntToLatLng(jsonXInt, jsonYInt) {
        const x = coerceJsonCoord(jsonXInt);
        const y = coerceJsonCoord(jsonYInt);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return [NaN, NaN];
        const t = getCoordTransform();
        const lng = (x * t.scaleX) + t.offsetX;
        const lat = -(y * t.scaleY) + t.offsetY; // Y轴反转
        return [lat, lng];
    }

    // Leaflet(lat,lng) -> JSON(Number)（使用可持久化覆盖的变换参数）
    function latLngToJson(lat, lng) {
        const t = getCoordTransform();
        const jsonX = (lng - t.offsetX) / t.scaleX;
        const jsonY = (t.offsetY - lat) / t.scaleY; // 由 lat = -y*scaleY + offsetY 推导
        return { x: jsonX, y: jsonY };
    }

    // Leaflet(lat,lng) -> Game(Float，保留两位小数，供编辑器/导出使用)
    function latLngToGame(lat, lng) {
        const { x: jsonX, y: jsonY } = latLngToJson(lat, lng);
        return {
            x: jsonToGameFloat(jsonX).toFixed(2),
            y: jsonToGameFloat(jsonY).toFixed(2)
        };
    }

    // Game(Float) -> Leaflet(lat,lng)
    function gameToLatLng(gameX, gameY) {
        return jsonIntToLatLng(gameToJsonInt(gameX), gameToJsonInt(gameY));
    }

    // 兼容旧调用：gameToLatLng / latLngToGame 保留签名，但内部已明确分层（JSON<->Leaflet, JSON<->Game）

    function showExportToast(message = '✅ 导出完成') {
        try {
            const old = document.getElementById('__kmp_export_toast');
            if (old && old.parentNode) old.parentNode.removeChild(old);

            const toast = document.createElement('div');
            toast.id = '__kmp_export_toast';
            toast.textContent = message;
            toast.style.cssText = [
                'position:fixed',
                'right:16px',
                'bottom:16px',
                'z-index:2147483647',
                'max-width:320px',
                'padding:10px 14px',
                'border-radius:10px',
                'background:rgba(28,28,32,.92)',
                'color:#fff',
                'font-size:13px',
                'line-height:1.4',
                'box-shadow:0 6px 20px rgba(0,0,0,.28)',
                'backdrop-filter:blur(3px)',
                'user-select:none',
                'cursor:default'
            ].join(';');

            const remove = () => {
                if (toast && toast.parentNode) toast.parentNode.removeChild(toast);
            };

            toast.addEventListener('mouseenter', remove);
            (document.body || document.documentElement).appendChild(toast);
            setTimeout(remove, 2000);
        } catch (e) {}
    }

    function downloadObjectAsJson(exportObj, exportName) {
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exportObj, null, 2));
        const downloadAnchorNode = document.createElement('a');
        downloadAnchorNode.setAttribute("href", dataStr);
        downloadAnchorNode.setAttribute("download", exportName);
        document.body.appendChild(downloadAnchorNode);
        downloadAnchorNode.click();
        downloadAnchorNode.remove();
        showExportToast(`✅ 导出完成: ${exportName}`);
    }

    function downloadTextAsFile(text, fileName, mimeType = 'text/plain;charset=utf-8') {
        const blob = new Blob([text], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        showExportToast(`✅ 导出完成: ${fileName}`);
    }

    function sanitizeFileName(name, fallback) {
        const s = String(name || '').trim();
        const clean = s.replace(/[<>:"/\\|?*\u0000-\u001F]/g, '_').slice(0, 150);
        return clean || (fallback || 'route');
    }

    function ensureExt(name, ext) {
        const s = String(name || '');
        return s.toLowerCase().endsWith(ext) ? s : (s + ext);
    }

    function makeUniqueFileName(existingSet, desired) {
        let base = desired;
        let n = 1;
        while (existingSet.has(base)) {
            const dot = desired.lastIndexOf('.');
            if (dot > 0) base = `${desired.slice(0, dot)} (${n++})${desired.slice(dot)}`;
            else base = `${desired} (${n++})`;
        }
        existingSet.add(base);
        return base;
    }

    async function exportRoutesAsZip(routes, zipFileName) {
        const JSZipLib = await ensurePageJSZip();
        const zip = new JSZipLib();
        const used = new Set();
        const failures = [];

        routes.forEach(r => {
            try {
                if (r.type === 'json') {
                    const fn = makeUniqueFileName(used, ensureExt(sanitizeFileName(r.name, 'route'), '.json'));
                    zip.file(fn, JSON.stringify(normalizeRouteGraph(r.rawData, r.name), null, 2));
                } else if (r.type === 'svg') {
                    if (!r.rawText) throw new Error('未保留SVG原始内容，无法导出');
                    const fn = makeUniqueFileName(used, ensureExt(sanitizeFileName(r.name, 'route'), '.svg'));
                    zip.file(fn, r.rawText);
                }
            } catch (e) {
                failures.push(`${r.name} -> ${toReason(e)}`);
            }
        });

        const blob = await zip.generateAsync({ type: 'blob' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = zipFileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);

        if (failures.length) {
            showExportToast(`⚠ 批量导出完成（${failures.length} 项失败）`);
        } else {
            showExportToast(`✅ 批量导出完成: ${zipFileName}`);
        }

        if (failures.length) alert(`批量导出完成，但有 ${failures.length} 个失败：\n\n${failures.join('\n')}`);
    }

    // fingerprint：输入按 position.json 的 JSON 坐标处理（不做类型猜测，仅做取整稳定化）
    function generateGlobalFP(rawX, rawY, rawLevel) {
        const level = rawLevel || "0";
        const x = coerceFpCoord(rawX);
        const y = coerceFpCoord(rawY);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return '';
        return `${x}_${y}_${level}`;
    }

    function processBulkData(data) {
        const traverse = (node, parentName = '') => {
            if (!node) return;
            if (Array.isArray(node)) { node.forEach(item => traverse(item, parentName)); return; }
            if (typeof node === 'object') {
                if (node.location) { node.location.forEach(p => savePoint(p, node.name || parentName)); return; }
                if (node.children) { traverse(node.children, node.name || parentName); return; }
                if (node.x !== undefined) savePoint(node, parentName);
            }
        };
        const savePoint = (p, categoryName) => {
            const finalName = p.name || categoryName || '未知点位';
            const fp = generateGlobalFP(p.x, p.y, p.mapLevel || p.level);
            if (!fp) return;
            if (!STATE.pointCache.has(fp)) {
                // 统一存储为 position.json 的 JSON 坐标
                const x = coerceJsonCoord(p.x);
                const y = coerceJsonCoord(p.y);
                if (!Number.isFinite(x) || !Number.isFinite(y)) return;
                STATE.pointCache.set(fp, { fp, name: finalName, x, y, level: p.mapLevel||p.level||"0" });
            }

            // 尽可能缓存 id -> JSON 坐标（用于自动校准/精确匹配）
            const id = p.id ?? p.positionId ?? p.position_id ?? p.positionID ?? p.poiId ?? p.poi_id;
            if (id !== undefined && id !== null && id !== '') {
                const k = String(id);
                if (!STATE.pointIdCache.has(k)) {
                    const typeId = p.typeId ?? p.positionType ?? p.type ?? null;
                    STATE.pointIdCache.set(k, {
                        id: k,
                        name: finalName,
                        x: coerceJsonCoord(p.x),
                        y: coerceJsonCoord(p.y),
                        level: p.mapLevel||p.level||"0",
                        type: typeId,
                        fp
                    });
                    try {
                        let m = STATE.fpIdIndex.get(fp);
                        if (!m) { m = new Map(); STATE.fpIdIndex.set(fp, m); }
                        if (!m.has(k)) m.set(k, typeId ? String(typeId) : null);
                    } catch (e) {}
                }
            }
        };
        traverse(data);
        scheduleAutoCalibrate('processBulkData');
    }

    function processDetailData(data) {
        STATE.currentDetail = data.data || data;
        const sidecar = document.getElementById('kmp-sidecar');
        if (sidecar) renderSidecar(sidecar, STATE.currentDetail);
    }

    function getColorForZ(z) {
        let normalizedZ = ((z - CONFIG.route.zMin) % CONFIG.route.zRange) / CONFIG.route.zRange;
        if (normalizedZ < 0) normalizedZ += 1;
        const hue = Math.floor(normalizedZ * 360);
        return `hsl(${hue}, 85%, 65%)`;
    }

    function getAngle(latLng1, latLng2) {
        const p1 = STATE.mapInstance.project(latLng1);
        const p2 = STATE.mapInstance.project(latLng2);
        return Math.atan2(p2.y - p1.y, p2.x - p1.x) * (180 / Math.PI);
    }

    function createRouteDirectionArrowHtml(angle, sizePx, options = {}) {
        const fill = options.fill || 'black';
        const stroke = options.stroke || 'white';
        const strokeWidth = options.strokeWidth ?? 0.5;
        const scale = options.scale || 1;
        const transform = `rotate(${angle}deg)${scale !== 1 ? ` scale(${scale})` : ''}`;
        const extraClass = options.className ? ` ${options.className}` : '';
        return `<div class="kmp-route-arrow${extraClass}" style="width:${sizePx}px; height:${sizePx}px; transform: ${transform}; transform-origin: center; display:flex;"><svg viewBox="0 0 10 10"><path d="M 0 0 L 10 5 L 0 10 L 3 5 Z" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" /></svg></div>`;
    }

    function normalizeRouteCoordinate(value) {
        const number = Number(value);
        return Number.isFinite(number) ? Math.round(number) : 0;
    }

    function reserveRouteCoordinate(x, y, usedCoordinates) {
        const normalizedX = normalizeRouteCoordinate(x);
        const normalizedY = normalizeRouteCoordinate(y);
        const coordinateKey = `${normalizedX},${normalizedY}`;
        if (!usedCoordinates.has(coordinateKey)) {
            usedCoordinates.add(coordinateKey);
            return { x: normalizedX, y: normalizedY };
        }

        const neighborOffsets = [
            [1, 0], [-1, 0], [0, 1], [0, -1],
            [1, 1], [1, -1], [-1, 1], [-1, -1]
        ];
        const availableOffset = neighborOffsets.find(([dx, dy]) => !usedCoordinates.has(`${normalizedX + dx},${normalizedY + dy}`));
        if (!availableOffset) return null;

        const resolved = {
            x: normalizedX + availableOffset[0],
            y: normalizedY + availableOffset[1]
        };
        usedCoordinates.add(`${resolved.x},${resolved.y}`);
        return resolved;
    }

    function normalizeHexColor(value, fallback) {
        return typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)
            ? value.toUpperCase()
            : fallback;
    }

    function hexToRgb(value) {
        if (typeof value !== 'string' || !/^#[0-9a-f]{6}$/i.test(value)) return null;
        return {
            r: parseInt(value.slice(1, 3), 16),
            g: parseInt(value.slice(3, 5), 16),
            b: parseInt(value.slice(5, 7), 16)
        };
    }

    function rgbToHex(r, g, b) {
        const channel = value => Math.round(Math.min(255, Math.max(0, Number(value) || 0)))
            .toString(16).padStart(2, '0');
        return `#${channel(r)}${channel(g)}${channel(b)}`.toUpperCase();
    }

    function rgbToHsv(r, g, b) {
        const red = Math.min(255, Math.max(0, Number(r) || 0)) / 255;
        const green = Math.min(255, Math.max(0, Number(g) || 0)) / 255;
        const blue = Math.min(255, Math.max(0, Number(b) || 0)) / 255;
        const max = Math.max(red, green, blue);
        const min = Math.min(red, green, blue);
        const delta = max - min;
        let hue = 0;
        if (delta) {
            if (max === red) hue = 60 * (((green - blue) / delta) % 6);
            else if (max === green) hue = 60 * (((blue - red) / delta) + 2);
            else hue = 60 * (((red - green) / delta) + 4);
        }
        if (hue < 0) hue += 360;
        return { h: hue, s: max ? (delta / max) * 100 : 0, v: max * 100 };
    }

    function hsvToRgb(h, s, v) {
        const hue = ((Number(h) || 0) % 360 + 360) % 360;
        const saturation = Math.min(100, Math.max(0, Number(s) || 0)) / 100;
        const value = Math.min(100, Math.max(0, Number(v) || 0)) / 100;
        const chroma = value * saturation;
        const component = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
        const match = value - chroma;
        let red = 0;
        let green = 0;
        let blue = 0;
        if (hue < 60) [red, green, blue] = [chroma, component, 0];
        else if (hue < 120) [red, green, blue] = [component, chroma, 0];
        else if (hue < 180) [red, green, blue] = [0, chroma, component];
        else if (hue < 240) [red, green, blue] = [0, component, chroma];
        else if (hue < 300) [red, green, blue] = [component, 0, chroma];
        else [red, green, blue] = [chroma, 0, component];
        return {
            r: Math.round((red + match) * 255),
            g: Math.round((green + match) * 255),
            b: Math.round((blue + match) * 255)
        };
    }

    function clampNumber(value, min, max, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback;
    }

    function normalizeSpecialMarkerStyle(style) {
        const source = style && typeof style === 'object' ? style : {};
        const number = source.number && typeof source.number === 'object' ? source.number : {};
        const outline = number.outline && typeof number.outline === 'object' ? number.outline : {};
        return {
            shape: SPECIAL_MARKER_SHAPES.includes(source.shape) ? source.shape : DEFAULT_SPECIAL_MARKER_STYLE.shape,
            fill_color: normalizeHexColor(source.fill_color, DEFAULT_SPECIAL_MARKER_STYLE.fill_color),
            number: {
                font_size: clampNumber(number.font_size, 8, 72, DEFAULT_SPECIAL_MARKER_STYLE.number.font_size),
                color: normalizeHexColor(number.color, DEFAULT_SPECIAL_MARKER_STYLE.number.color),
                outline: {
                    enabled: typeof outline.enabled === 'boolean' ? outline.enabled : DEFAULT_SPECIAL_MARKER_STYLE.number.outline.enabled,
                    width: clampNumber(outline.width, 0, 8, DEFAULT_SPECIAL_MARKER_STYLE.number.outline.width),
                    color: normalizeHexColor(outline.color, DEFAULT_SPECIAL_MARKER_STYLE.number.outline.color)
                }
            }
        };
    }

    function createSpecialMarkerStyleDraft(style) {
        return normalizeSpecialMarkerStyle(style);
    }

    function restoreSpecialMarkerGroupStyle(route, groupId, snapshot) {
        const groups = route && route.editingGraph && route.editingGraph.special_marker_groups;
        const group = Array.isArray(groups) ? groups.find(item => item.id === groupId) : null;
        if (!group) return false;
        group.style = createSpecialMarkerStyleDraft(snapshot);
        return true;
    }

    function normalizeSpecialMarkerGroups(rawData, nodeIds) {
        const source = rawData && Array.isArray(rawData.special_marker_groups) ? rawData.special_marker_groups : [];
        const validNodeIds = nodeIds instanceof Set ? nodeIds : new Set(nodeIds || []);
        const claimedNodeIds = new Set();
        return source.map((group, index) => {
            const normalizedNodeIds = [];
            const sourceNodeIds = group && Array.isArray(group.node_ids) ? group.node_ids : [];
            sourceNodeIds.forEach(nodeId => {
                const id = String(nodeId);
                if (!validNodeIds.has(id) || claimedNodeIds.has(id)) return;
                claimedNodeIds.add(id);
                normalizedNodeIds.push(id);
            });
            return {
                id: group && group.id ? String(group.id) : `smg${index + 1}`,
                style: normalizeSpecialMarkerStyle(group && group.style),
                node_ids: normalizedNodeIds
            };
        });
    }

    function renderSpecialMarkerGroups(layerGroup, graph, options = {}) {
        const nodeById = new Map((graph.nodes || []).map(node => [node.id, node]));
        const pane = options.pane || 'kmp-arrow-pane';
        normalizeSpecialMarkerGroups(graph, new Set(nodeById.keys())).forEach(group => {
            group.node_ids.forEach((nodeId, index) => {
                const node = nodeById.get(nodeId);
                if (!node) return;
                const style = group.style;
                const outlineStyle = style.number.outline.enabled
                    ? `-webkit-text-stroke:${style.number.outline.width}px ${style.number.outline.color};paint-order:stroke fill;`
                    : '';
                const numberStyle = `font-size:${style.number.font_size}px;color:${style.number.color};${outlineStyle}`;
                const html = `<div class="kmp-route-node-style kmp-special-marker" data-special-marker-shape="${style.shape}" style="--node-color:${style.fill_color}"><span class="kmp-route-node-core kmp-special-marker-shape ${style.shape}"></span><span class="kmp-route-node-text" style="${numberStyle}">${index + 1}</span></div>`;
                const sizePx = 28;
                L.marker(gameToLatLng(node.x, node.y), {
                    icon: L.divIcon({
                        className: '',
                        html,
                        iconSize: [sizePx, sizePx],
                        iconAnchor: [sizePx / 2, sizePx / 2]
                    }),
                    interactive: false,
                    pane
                }).addTo(layerGroup);
            });
        });
    }

    function makeGraphNodeId(index) {
        return `n${index}`;
    }

    function makeGraphEdgeId(index) {
        return `e${index}`;
    }

    function pointToGraphNode(point, id) {
        return {
            id,
            x: normalizeRouteCoordinate(point && point.x),
            y: normalizeRouteCoordinate(point && point.y),
            z: normalizeRouteCoordinate(point && point.z)
        };
    }

    function normalizeRouteAssociatedMarkers(rawData) {
        const source = rawData && Array.isArray(rawData.associated_markers) ? rawData.associated_markers : [];
        const seen = new Set();
        const markers = [];
        source.forEach(marker => {
            if (!marker || marker.id === undefined || marker.id === null || marker.type === undefined || marker.type === null) return;
            const id = String(marker.id);
            const type = String(marker.type);
            const key = `${type}::${id}`;
            if (!id || !type || seen.has(key)) return;
            seen.add(key);
            const numberOrNull = value => {
                if (value === undefined || value === null || value === '') return null;
                const n = Number(value);
                return Number.isFinite(n) ? n : null;
            };
            markers.push({
                id,
                type,
                fp: marker.fp ? String(marker.fp) : '',
                name: marker.name ? String(marker.name) : '',
                x: numberOrNull(marker.x),
                y: numberOrNull(marker.y),
                level: marker.level === undefined || marker.level === null ? '0' : String(marker.level),
                lat: numberOrNull(marker.lat),
                lng: numberOrNull(marker.lng)
            });
        });
        return markers;
    }

    function isRouteGraphV2(rawData) {
        return !!(
            rawData &&
            rawData.schema === ROUTE_GRAPH_SCHEMA &&
            Number(rawData.version) === ROUTE_GRAPH_VERSION &&
            Array.isArray(rawData.nodes) &&
            Array.isArray(rawData.edges)
        );
    }

    function getLegacyRouteSegments(rawData) {
        if (!rawData) return [];
        if (Array.isArray(rawData.routes)) {
            return rawData.routes
                .map(route => Array.isArray(route && route.points) ? route.points : [])
                .filter(points => points.length > 0);
        }
        if (Array.isArray(rawData.points)) return [rawData.points];
        return [];
    }

    function normalizeLegacyRouteGraph(rawData, routeName) {
        const nodes = [];
        const edges = [];
        const usedCoordinates = new Set();
        let nodeIndex = 1;
        let edgeIndex = 1;
        getLegacyRouteSegments(rawData).forEach(segment => {
            let prevNode = null;
            segment.forEach(point => {
                const node = pointToGraphNode(point, makeGraphNodeId(nodeIndex));
                if (prevNode && node.x === prevNode.x && node.y === prevNode.y) return;
                const coordinate = reserveRouteCoordinate(node.x, node.y, usedCoordinates);
                if (!coordinate) return;
                node.x = coordinate.x;
                node.y = coordinate.y;
                nodeIndex++;
                nodes.push(node);
                if (prevNode) {
                    edges.push({ id: makeGraphEdgeId(edgeIndex++), from: prevNode.id, to: node.id });
                }
                prevNode = node;
            });
        });
        return {
            schema: ROUTE_GRAPH_SCHEMA,
            version: ROUTE_GRAPH_VERSION,
            route_info: (rawData && rawData.route_info) || { name: routeName, created_time: new Date().toLocaleString() },
            associated_markers: normalizeRouteAssociatedMarkers(rawData),
            nodes,
            edges,
            special_marker_groups: []
        };
    }

    function normalizeRouteGraph(rawData, routeName = 'route') {
        if (isRouteGraphV2(rawData)) {
            const nodes = rawData.nodes
                .filter(node => node && typeof node.id === 'string')
                .map(node => ({
                    id: node.id,
                    x: normalizeRouteCoordinate(node.x),
                    y: normalizeRouteCoordinate(node.y),
                    z: normalizeRouteCoordinate(node.z)
                }));
            const nodeIds = new Set(nodes.map(node => node.id));
            const edges = rawData.edges
                .filter(edge => edge && typeof edge.id === 'string' && nodeIds.has(edge.from) && nodeIds.has(edge.to))
                .map(edge => ({ id: edge.id, from: edge.from, to: edge.to }));
            return {
                schema: ROUTE_GRAPH_SCHEMA,
                version: ROUTE_GRAPH_VERSION,
                route_info: rawData.route_info || { name: routeName, created_time: new Date().toLocaleString() },
                associated_markers: normalizeRouteAssociatedMarkers(rawData),
                nodes,
                edges,
                special_marker_groups: normalizeSpecialMarkerGroups(rawData, nodeIds)
            };
        }
        return normalizeLegacyRouteGraph(rawData, routeName);
    }

    function serializeRouteGraph(route) {
        const graph = normalizeRouteGraph(route.editingGraph || route.rawData, route.name);
        return {
            schema: ROUTE_GRAPH_SCHEMA,
            version: ROUTE_GRAPH_VERSION,
            route_info: graph.route_info || { name: route.name, created_time: new Date().toLocaleString() },
            associated_markers: normalizeRouteAssociatedMarkers(graph),
            nodes: graph.nodes,
            edges: graph.edges,
            special_marker_groups: graph.special_marker_groups
        };
    }

    function createEmptyRouteGraph(routeName) {
        return {
            schema: ROUTE_GRAPH_SCHEMA,
            version: ROUTE_GRAPH_VERSION,
            route_info: { name: routeName, created_time: new Date().toLocaleString() },
            associated_markers: [],
            nodes: [],
            edges: [],
            special_marker_groups: []
        };
    }

    function collectSelectedJsonRoutes(routeManager) {
        if (!routeManager || routeManager.singleVisibleMode) return [];
        const routes = Array.isArray(routeManager.routes) ? routeManager.routes : [];
        if (routes.some(route => route && route.isEditing)) return [];
        const selectedIds = routeManager.selectedIds;
        if (!(selectedIds instanceof Set)) return [];
        const selectedRoutes = routes.filter(route => route && selectedIds.has(route.id));
        if (selectedRoutes.length < 2 || selectedRoutes.some(route => route.type !== 'json')) return [];
        return selectedRoutes;
    }

    function mergeRouteGraphs(routes, routeName) {
        const merged = createEmptyRouteGraph(routeName);
        const usedCoordinates = new Set();
        const associatedMarkers = [];

        (routes || []).forEach(route => {
            const graph = normalizeRouteGraph(route.rawData, route.name);
            const nodeIdMap = new Map();
            graph.nodes.forEach(node => {
                const coordinate = reserveRouteCoordinate(node.x, node.y, usedCoordinates);
                if (!coordinate) return;
                const nodeId = makeGraphNodeId(merged.nodes.length + 1);
                nodeIdMap.set(node.id, nodeId);
                merged.nodes.push({
                    id: nodeId,
                    x: coordinate.x,
                    y: coordinate.y,
                    z: normalizeRouteCoordinate(node.z)
                });
            });

            graph.edges.forEach(edge => {
                const from = nodeIdMap.get(edge.from);
                const to = nodeIdMap.get(edge.to);
                if (!from || !to) return;
                merged.edges.push({
                    id: makeGraphEdgeId(merged.edges.length + 1),
                    from,
                    to
                });
            });

            graph.special_marker_groups.forEach(group => {
                const nodeIds = group.node_ids.map(nodeId => nodeIdMap.get(nodeId)).filter(Boolean);
                merged.special_marker_groups.push({
                    id: createSpecialMarkerGroupId(merged),
                    style: normalizeSpecialMarkerStyle(group.style),
                    node_ids: nodeIds
                });
            });
            associatedMarkers.push(...graph.associated_markers);
        });

        merged.associated_markers = normalizeRouteAssociatedMarkers({ associated_markers: associatedMarkers });
        return merged;
    }

    function buildDirectedGraphChains(graph) {
        const edges = Array.isArray(graph && graph.edges) ? graph.edges : [];
        const inDegree = new Map();
        const outDegree = new Map();
        const outgoing = new Map();
        (graph.nodes || []).forEach(node => {
            inDegree.set(node.id, 0);
            outDegree.set(node.id, 0);
            outgoing.set(node.id, []);
        });
        edges.forEach(edge => {
            inDegree.set(edge.to, (inDegree.get(edge.to) || 0) + 1);
            outDegree.set(edge.from, (outDegree.get(edge.from) || 0) + 1);
            if (!outgoing.has(edge.from)) outgoing.set(edge.from, []);
            outgoing.get(edge.from).push(edge);
        });

        const visitedEdgeIds = new Set();
        const chains = [];
        const followChain = firstEdge => {
            if (!firstEdge || visitedEdgeIds.has(firstEdge.id)) return;
            const chain = [];
            let edge = firstEdge;
            while (edge && !visitedEdgeIds.has(edge.id)) {
                visitedEdgeIds.add(edge.id);
                chain.push(edge);
                const currentNodeId = edge.to;
                const continues = inDegree.get(currentNodeId) === 1 && outDegree.get(currentNodeId) === 1;
                if (!continues) break;
                edge = (outgoing.get(currentNodeId) || [])[0] || null;
            }
            if (chain.length) chains.push(chain);
        };

        edges.forEach(edge => {
            if ((inDegree.get(edge.from) || 0) !== 1 || (outDegree.get(edge.from) || 0) !== 1) {
                followChain(edge);
            }
        });
        edges.slice().sort((a, b) => String(a.id).localeCompare(String(b.id))).forEach(followChain);
        return chains;
    }

    function getGraphChainArrowPlacements(chain, nodeById, arrowGap) {
        const segments = [];
        let totalLength = 0;
        (chain || []).forEach(edge => {
            const fromNode = nodeById.get(edge.from);
            const toNode = nodeById.get(edge.to);
            if (!fromNode || !toNode) return;
            const length = Math.hypot(toNode.x - fromNode.x, toNode.y - fromNode.y);
            if (!(length > 0)) return;
            segments.push({ edge, fromNode, toNode, length, start: totalLength });
            totalLength += length;
        });
        if (!segments.length || !(totalLength > 0)) return [];

        const gap = Math.max(1, Number(arrowGap) || CONFIG.route.defaultGap);
        const arrowCount = Math.max(1, Math.floor(totalLength / gap));
        const firstDistance = (totalLength - (arrowCount - 1) * gap) / 2;
        const nodeDistances = [0, ...segments.slice(0, -1).map(segment => segment.start + segment.length), totalLength];
        const nodeMargin = Math.min(20, Math.max(0.5, gap * 0.1), totalLength * 0.2);

        const moveOffNode = distance => {
            let nearest = nodeDistances[0];
            let nearestDelta = Math.abs(distance - nearest);
            nodeDistances.forEach(nodeDistance => {
                const delta = Math.abs(distance - nodeDistance);
                if (delta < nearestDelta) {
                    nearest = nodeDistance;
                    nearestDelta = delta;
                }
            });
            if (nearestDelta >= nodeMargin) return distance;
            const candidates = [nearest + nodeMargin, nearest - nodeMargin]
                .filter(candidate => candidate > 0 && candidate < totalLength);
            if (!candidates.length) return distance;
            let best = candidates[0];
            let bestClearance = Math.min(...nodeDistances.map(nodeDistance => Math.abs(best - nodeDistance)));
            candidates.slice(1).forEach(candidate => {
                const clearance = Math.min(...nodeDistances.map(nodeDistance => Math.abs(candidate - nodeDistance)));
                if (clearance > bestClearance) {
                    best = candidate;
                    bestClearance = clearance;
                }
            });
            return best;
        };

        const placements = [];
        for (let index = 0; index < arrowCount; index++) {
            const distance = moveOffNode(firstDistance + index * gap);
            const segment = segments.find(item => distance < item.start + item.length) || segments[segments.length - 1];
            const t = Math.max(0, Math.min(1, (distance - segment.start) / segment.length));
            const x = segment.fromNode.x + (segment.toNode.x - segment.fromNode.x) * t;
            const y = segment.fromNode.y + (segment.toNode.y - segment.fromNode.y) * t;
            placements.push({ edge: segment.edge, fromNode: segment.fromNode, toNode: segment.toNode, x, y });
        }
        return placements;
    }

    function drawGraphOnLayer(layerGroup, graph, options = {}) {
        const nodeById = new Map(graph.nodes.map(node => [node.id, node]));
        const showDirectionArrows = options.showDirectionArrows !== false;
        graph.edges.forEach(edge => {
            const fromNode = nodeById.get(edge.from);
            const toNode = nodeById.get(edge.to);
            if (!fromNode || !toNode) return;
            const startLatLng = gameToLatLng(fromNode.x, fromNode.y);
            const endLatLng = gameToLatLng(toNode.x, toNode.y);
            L.polyline([startLatLng, endLatLng], {
                color: getColorForZ(fromNode.z || 0),
                weight: parseInt(SETTINGS.pathWeight),
                opacity: 1,
                interactive: false
            }).addTo(layerGroup);
        });

        if (showDirectionArrows) {
            const sizePx = 12 * SETTINGS.arrowSize;
            const chains = buildDirectedGraphChains(graph);
            chains.forEach(chain => {
                getGraphChainArrowPlacements(chain, nodeById, SETTINGS.arrowGap).forEach(placement => {
                    const startLatLng = gameToLatLng(placement.fromNode.x, placement.fromNode.y);
                    const endLatLng = gameToLatLng(placement.toNode.x, placement.toNode.y);
                    const arrowLatLng = gameToLatLng(placement.x, placement.y);
                    const angle = getAngle(startLatLng, endLatLng);
                    const arrowIcon = L.divIcon({
                        className: '',
                        html: createRouteDirectionArrowHtml(angle, sizePx),
                        iconSize: [sizePx, sizePx],
                        iconAnchor: [sizePx / 2, sizePx / 2]
                    });
                    L.marker(arrowLatLng, { icon: arrowIcon, interactive: false, pane: 'kmp-arrow-pane' }).addTo(layerGroup);
                });
            });
        }
        if (options.renderSpecialMarkers !== false) {
            renderSpecialMarkerGroups(layerGroup, graph, { pane: options.specialMarkerPane || 'kmp-arrow-pane' });
        }
    }

    function drawJsonOnLayer(layerGroup, data) {
        drawGraphOnLayer(layerGroup, normalizeRouteGraph(data));
    }

    function getClosestSegmentIndex(latlng, polyline) {
        const points = polyline.getLatLngs();
        let minInfo = { dist: Infinity, index: -1 };
        const p = STATE.mapInstance.project(latlng);
        for (let i = 0; i < points.length - 1; i++) {
            const p1 = STATE.mapInstance.project(points[i]);
            const p2 = STATE.mapInstance.project(points[i+1]);
            const L2 = (p1.x-p2.x)**2 + (p1.y-p2.y)**2;
            if (L2 === 0) continue;
            let t = ((p.x-p1.x)*(p2.x-p1.x) + (p.y-p1.y)*(p2.y-p1.y)) / L2;
            t = Math.max(0, Math.min(1, t));
            const projX = p1.x + t * (p2.x-p1.x);
            const projY = p1.y + t * (p2.y-p1.y);
            const dist = Math.sqrt((p.x-projX)**2 + (p.y-projY)**2);
            if (dist < minInfo.dist) { minInfo = { dist, index: i }; }
        }
        return minInfo.index;
    }

    function routeAssociatedMarkerKey(marker) {
        return marker ? `${String(marker.type)}::${String(marker.id)}` : '';
    }

    function getRouteGraphForMarkerDisplay(route) {
        if (!route || route.type !== 'json') return null;
        return route.editingGraph || route.rawData || null;
    }

    function getRouteAssociatedMarkers(route) {
        return normalizeRouteAssociatedMarkers(getRouteGraphForMarkerDisplay(route));
    }

    function getControllerLeafletMarkers(controller) {
        const markers = [];
        if (!controller) return markers;
        if (controller._icon || typeof controller.getElement === 'function') markers.push(controller);
        if (Array.isArray(controller.markers)) {
            controller.markers.forEach(marker => {
                if (marker && !markers.includes(marker)) markers.push(marker);
            });
        }
        return markers;
    }

    function getControllerLatLng(controller) {
        const markers = getControllerLeafletMarkers(controller);
        for (const marker of markers) {
            try {
                const latlng = typeof marker.getLatLng === 'function' ? marker.getLatLng() : marker._latlng;
                if (latlng && Number.isFinite(Number(latlng.lat)) && Number.isFinite(Number(latlng.lng))) return latlng;
            } catch (e) {}
        }
        try {
            const latlng = typeof controller.getLatLng === 'function' ? controller.getLatLng() : controller._latlng;
            if (latlng && Number.isFinite(Number(latlng.lat)) && Number.isFinite(Number(latlng.lng))) return latlng;
        } catch (e) {}
        return null;
    }

    function getLeafletMapContainer(map) {
        if (!map) return null;
        try {
            if (map._container) return map._container;
        } catch (e) {}
        try {
            if (typeof map.getContainer === 'function') return map.getContainer();
        } catch (e) {}
        return null;
    }

    function isSameLeafletMap(candidate, expected) {
        if (!candidate || !expected) return false;
        if (candidate === expected) return true;
        const candidateContainer = getLeafletMapContainer(candidate);
        const expectedContainer = getLeafletMapContainer(expected);
        return !!candidateContainer && candidateContainer === expectedContainer;
    }

    function isControllerVisibleOnOfficialMap(controller) {
        const capturedMap = STATE.mapInstance;
        const storeMap = getMapStore()?.mapInstance || null;
        return getControllerLeafletMarkers(controller).some(marker => {
            try {
                if (marker._map) {
                    if (!capturedMap && !storeMap) return true;
                    if (isSameLeafletMap(marker._map, storeMap)) return true;
                    if (isSameLeafletMap(marker._map, capturedMap)) return true;
                }
                const icon = marker._icon || (typeof marker.getElement === 'function' ? marker.getElement() : null);
                return !!(icon && icon.isConnected);
            } catch (e) {
                return false;
            }
        });
    }

    function getAssociatedMarkerController(marker) {
        return marker ? getMarkerControllerById(marker.id, marker.type) : null;
    }

    function buildOfficialMarkerRecord(typeId, pointId, controller) {
        const id = String(pointId);
        const type = String(typeId);
        const cached = STATE.pointIdCache.get(id) || null;
        const latlng = getControllerLatLng(controller);
        return {
            id,
            type,
            fp: cached && cached.fp ? String(cached.fp) : '',
            name: (cached && cached.name) || (controller.options && controller.options.name) || '',
            x: cached && Number.isFinite(Number(cached.x)) ? Number(cached.x) : null,
            y: cached && Number.isFinite(Number(cached.y)) ? Number(cached.y) : null,
            level: cached && cached.level !== undefined ? String(cached.level) : '0',
            lat: latlng ? Number(latlng.lat) : null,
            lng: latlng ? Number(latlng.lng) : null
        };
    }

    function findOfficialMarkerHitByCanvas(target) {
        if (!target) return null;
        const mapStore = getMapStore();
        const cache = mapStore && mapStore.markersCache;
        if (!(cache instanceof Map) || !mapStore.mapInstance || !mapStore.mapInstance._layers) return null;

        const renderer = Object.values(mapStore.mapInstance._layers).find(
            layer => layer && layer._container === target
        );
        const hoveredLayer = renderer && renderer._hoveredLayer;
        if (!hoveredLayer) return null;

        for (const [typeId, inner] of cache.entries()) {
            if (!(inner instanceof Map)) continue;
            for (const [pointId, controller] of inner.entries()) {
                if (!controller || !Array.isArray(controller.markers)) continue;
                if (!controller.markers.includes(hoveredLayer)) continue;
                return buildOfficialMarkerRecord(typeId, pointId, controller);
            }
        }
        return null;
    }

    function toggleRouteAssociatedMarker(route, markerRecord) {
        if (!route || !route.editingGraph || !markerRecord) return false;
        const markers = normalizeRouteAssociatedMarkers(route.editingGraph);
        const key = routeAssociatedMarkerKey(markerRecord);
        const index = markers.findIndex(marker => routeAssociatedMarkerKey(marker) === key);
        if (index >= 0) markers.splice(index, 1);
        else markers.push(markerRecord);
        route.editingGraph.associated_markers = normalizeRouteAssociatedMarkers({ associated_markers: markers });
        updateGraphEditToolbar(route);
        updateGraphEditHelpPanel(route);
        scheduleRouteMarkerDisplay('association-toggle');
        return index < 0;
    }

    function uninstallRouteMarkerAssociationCapture() {
        const container = STATE._routeMarkerCaptureContainer;
        if (container && STATE._routeMarkerCaptureHandler) {
            try { container.removeEventListener('click', STATE._routeMarkerCaptureHandler, true); } catch (e) {}
        }
        if (container && STATE._routeMarkerPointerMoveHandler) {
            try { container.removeEventListener('pointermove', STATE._routeMarkerPointerMoveHandler, true); } catch (e) {}
        }
        if (container && STATE._routeMarkerPointerLeaveHandler) {
            try { container.removeEventListener('pointerleave', STATE._routeMarkerPointerLeaveHandler, true); } catch (e) {}
        }
        if (STATE._routeMarkerHoverFrame) {
            try { cancelAnimationFrame(STATE._routeMarkerHoverFrame); } catch (e) {}
        }
        STATE._routeMarkerCaptureContainer = null;
        STATE._routeMarkerCaptureHandler = null;
        STATE._routeMarkerPointerMoveHandler = null;
        STATE._routeMarkerPointerLeaveHandler = null;
        STATE._routeMarkerHoverFrame = null;
        STATE._routeMarkerHoveredRecord = null;
    }

    function installRouteMarkerAssociationCapture() {
        const map = STATE.mapInstance;
        const container = map && typeof map.getContainer === 'function' ? map.getContainer() : null;
        if (!container) return;
        if (STATE._routeMarkerCaptureContainer === container && STATE._routeMarkerCaptureHandler) return;
        uninstallRouteMarkerAssociationCapture();
        STATE._routeMarkerPointerMoveHandler = event => {
            if (STATE._routeMarkerHoverFrame) cancelAnimationFrame(STATE._routeMarkerHoverFrame);
            STATE._routeMarkerHoverFrame = requestAnimationFrame(() => {
                STATE._routeMarkerHoverFrame = null;
                if (STATE._routeMarkerCaptureContainer !== container) return;
                STATE._routeMarkerHoveredRecord = findOfficialMarkerHitByCanvas(event.target);
            });
        };
        STATE._routeMarkerPointerLeaveHandler = () => {
            STATE._routeMarkerHoveredRecord = null;
        };
        STATE._routeMarkerCaptureHandler = event => {
            const route = getActiveEditingRoute();
            if (!route || !route.markerAssociationMode) return;
            const markerRecord = findOfficialMarkerHitByCanvas(event.target);
            if (!markerRecord) return;
            event.preventDefault();
            event.stopPropagation();
            if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
            toggleRouteAssociatedMarker(route, markerRecord);
        };
        container.addEventListener('pointermove', STATE._routeMarkerPointerMoveHandler, true);
        container.addEventListener('pointerleave', STATE._routeMarkerPointerLeaveHandler, true);
        container.addEventListener('click', STATE._routeMarkerCaptureHandler, true);
        STATE._routeMarkerCaptureContainer = container;
    }

    function setRouteMarkerAssociationMode(route, enabled) {
        if (!route || !route.isEditing) return;
        setExclusiveGraphEditMode(route, 'markers', enabled);
    }

    function getVisibleRouteAssociatedMarkers() {
        const seen = new Set();
        const markers = [];
        (STATE.routeManager.routes || []).forEach(route => {
            if (!route || route.type !== 'json' || !route.visible) return;
            getRouteAssociatedMarkers(route).forEach(marker => {
                const key = routeAssociatedMarkerKey(marker);
                if (!key || seen.has(key)) return;
                seen.add(key);
                markers.push(marker);
            });
        });
        return markers;
    }

    function hasVisibleJsonRoute() {
        return (STATE.routeManager.routes || []).some(route => route && route.type === 'json' && route.visible);
    }

    function getEnabledAssociatedMarkers(markers) {
        return (markers || []).filter(marker => {
            const controller = getAssociatedMarkerController(marker);
            return controller && isControllerVisibleOnOfficialMap(controller);
        });
    }

    function clearRouteMarkerHighlights() {
        if (STATE.routeMarkerHighlightLayer) STATE.routeMarkerHighlightLayer.clearLayers();
    }

    function highlightRouteAssociatedMarkers(markers) {
        if (!STATE.mapInstance) return;
        if (!STATE.routeMarkerHighlightLayer) STATE.routeMarkerHighlightLayer = L.layerGroup().addTo(STATE.mapInstance);
        STATE.routeMarkerHighlightLayer.clearLayers();
        getEnabledAssociatedMarkers(markers).forEach(marker => {
            const latlng = getControllerLatLng(getAssociatedMarkerController(marker));
            if (!latlng) return;
            L.circleMarker(latlng, {
                radius: 12,
                color: '#00ff00',
                weight: 3,
                fill: false,
                opacity: 0.9,
                pane: 'kmp_highlight_pane'
            }).addTo(STATE.routeMarkerHighlightLayer);
        });
    }

    function applyRouteMarkerDisplay(reason) {
        const editingRoute = getActiveEditingRoute();
        const selectingMarkers = editingRoute && editingRoute.markerAssociationMode;
        ensureMapStoreActionHook();

        if (selectingMarkers) {
            installRouteMarkerAssociationCapture();
            clearMarkerFocus();
            highlightRouteAssociatedMarkers(getRouteAssociatedMarkers(editingRoute));
            return;
        }

        if (editingRoute && !editingRoute.graphPreviewMode) {
            clearMarkerFocus('route');
            highlightRouteAssociatedMarkers(getRouteAssociatedMarkers(editingRoute));
            return;
        }

        const markers = getVisibleRouteAssociatedMarkers();
        const mode = STATE.routeManager.markerDisplayMode;
        if (mode === 'highlight') {
            clearMarkerFocus('route');
            highlightRouteAssociatedMarkers(markers);
            return;
        }

        clearRouteMarkerHighlights();
        if (mode === 'focus') {
            if (!hasVisibleJsonRoute()) {
                clearMarkerFocus('route');
                return;
            }
            const keys = new Set(getEnabledAssociatedMarkers(markers).map(routeAssociatedMarkerKey).filter(Boolean));
            applyMarkerFocusByKeys(keys, 'route', reason || 'route-marker-display');
            return;
        }
        clearMarkerFocus('route');
    }

    function scheduleRouteMarkerDisplay(reason) {
        if (STATE._routeMarkerDisplayTimer) clearTimeout(STATE._routeMarkerDisplayTimer);
        STATE._routeMarkerDisplayTimer = setTimeout(() => {
            STATE._routeMarkerDisplayTimer = null;
            applyRouteMarkerDisplay(reason);
        }, 0);
    }

    function syncRouteMarkerDisplayModeUI() {
        const wrap = document.getElementById('sm-route-marker-display-mode');
        if (!wrap) return;
        wrap.querySelectorAll('[data-route-marker-mode]').forEach(button => {
            button.classList.toggle('active', button.dataset.routeMarkerMode === STATE.routeManager.markerDisplayMode);
        });
    }

    STATE.routeManager.add = function(routeObj) {
        this.routes.push(routeObj);
        if (this.singleVisibleMode && routeObj && routeObj.visible) {
            this.setRouteVisible(routeObj, true, { exclusive: true });
        }
        renderRouteListUI();
    };

    STATE.routeManager.createNewRoute = function() {
        if (getActiveEditingRoute()) {
            alert('请先保存或取消当前路线编辑');
            return null;
        }
        if (!STATE.mapInstance || !STATE.mainLayerGroup) {
            alert('地图尚未初始化，暂时无法新建路线');
            return null;
        }

        const name = `未命名路线_${Date.now()}`;
        const route = {
            id: `route-${Date.now()}-${Math.random()}`,
            name,
            type: 'json',
            layer: L.layerGroup(),
            rawData: createEmptyRouteGraph(name),
            visible: true,
            isNewRoute: true
        };
        STATE.mainLayerGroup.addLayer(route.layer);
        this.add(route);
        this.startEdit(route.id);
        return route;
    };

    STATE.routeManager._setRouteLayerVisible = function(route, visible) {
        if (!route || !route.layer || !STATE.mainLayerGroup) return;
        if (visible) STATE.mainLayerGroup.addLayer(route.layer);
        else STATE.mainLayerGroup.removeLayer(route.layer);
    };

    STATE.routeManager.syncSingleVisibleIndex = function(preferredRoute = null) {
        const routes = this.routes || [];
        const visibleRoutes = routes.filter(r => r && r.visible && !r.isEditing);
        if (!visibleRoutes.length) {
            this.activeRouteIndex = -1;
            return;
        }
        if (preferredRoute && preferredRoute.visible) {
            const idx = routes.findIndex(r => r && r.id === preferredRoute.id);
            this.activeRouteIndex = idx >= 0 ? idx : routes.findIndex(r => r && r.visible && !r.isEditing);
            return;
        }
        const idx = routes.findIndex(r => r && r.visible && !r.isEditing);
        this.activeRouteIndex = idx >= 0 ? idx : -1;
    };

    STATE.routeManager.applySingleVisibleMode = function(enabled, options = {}) {
        this.singleVisibleMode = !!enabled;
        const routes = this.routes || [];
        if (!this.singleVisibleMode) {
            this.syncSingleVisibleIndex();
            if (!options.silent) renderRouteListUI();
            return;
        }

        const visibleRoutes = routes.filter(r => r && r.visible && !r.isEditing);
        if (!visibleRoutes.length) {
            this.activeRouteIndex = -1;
            if (!options.silent) renderRouteListUI();
            return;
        }

        const keep = visibleRoutes[0];
        routes.forEach(r => {
            if (!r || r.id === keep.id || r.isEditing) return;
            if (r.visible) {
                r.visible = false;
                this._setRouteLayerVisible(r, false);
            }
        });
        keep.visible = true;
        this._setRouteLayerVisible(keep, true);
        this.syncSingleVisibleIndex(keep);
        if (!options.silent) renderRouteListUI();
    };

    STATE.routeManager.setRouteVisible = function(route, visible, options = {}) {
        if (!route) return;
        const exclusive = !!options.exclusive;
        if (visible && exclusive) {
            this.routes.forEach(r => {
                if (!r || r.id === route.id || r.isEditing) return;
                if (r.visible) {
                    r.visible = false;
                    this._setRouteLayerVisible(r, false);
                }
            });
        }
        route.visible = !!visible;
        this._setRouteLayerVisible(route, route.visible);
        this.syncSingleVisibleIndex(route.visible ? route : null);
    };

    STATE.routeManager.shiftVisibleRoute = function(direction) {
        const routes = this.routes || [];
        if (!routes.length) return null;
        const total = routes.length;
        let idx = this.activeRouteIndex;
        if (idx < 0 || idx >= total) idx = direction > 0 ? -1 : 0;
        const nextIndex = direction > 0
            ? (idx + 1) % total
            : (idx < 0 ? total - 1 : (idx - 1 + total) % total);
        const target = routes[nextIndex];
        if (!target) return null;
        this.setRouteVisible(target, true, { exclusive: true });
        this.activeRouteIndex = nextIndex;
        renderRouteListUI();
        return target;
    };

    function syncSingleRouteToggleUI() {
        const singleToggle = document.getElementById('sm-single-route-toggle');
        if (!singleToggle) return;
        const singleMode = !!STATE.routeManager.singleVisibleMode;
        singleToggle.checked = singleMode;
        const switchEl = singleToggle.closest('.sm-switch');
        if (switchEl) {
            switchEl.classList.toggle('is-on', singleMode);
            switchEl.classList.toggle('is-off', !singleMode);
        }
    }

    STATE.routeManager.remove = function(id) {
        const idx = this.routes.findIndex(r => r.id === id);
        if (idx !== -1) {
            const r = this.routes[idx];
            if (this.selectedIds) this.selectedIds.delete(id);
            // 清理编辑状态
            if (r.isEditing) {
                closeSpecialMarkerStyleModal(r, false);
                r.specialMarkerGroupMode = false;
                r.specialMarkerAddingGroupId = null;
                r.specialMarkerSelectedGroupId = null;
                updateSpecialMarkerGroupSidebar(null);
                this.disableBoxSelect(r); // 确保退出框选模式
                if (r.editorGroup) STATE.mapInstance.removeLayer(r.editorGroup);
            }
            if (r.layer) STATE.mainLayerGroup.removeLayer(r.layer);
            this.routes.splice(idx, 1);
            if (this.activeRouteIndex >= this.routes.length) this.activeRouteIndex = this.routes.length - 1;
            this.syncSingleVisibleIndex();
            renderRouteListUI();
        }
    };

    STATE.routeManager.toggleVisible = function(id) {
        const route = this.routes.find(r => r.id === id);
        if (route) {
            if (route.isEditing) { alert("请先保存或取消编辑！"); return; }
            this.setRouteVisible(route, !route.visible, { exclusive: this.singleVisibleMode });
            renderRouteListUI();
        }
    };

    STATE.routeManager.exportOne = function(id) {
        const route = this.routes.find(r => r.id === id);
        if (!route) return;
        if (route.isEditing) { alert('请先保存或取消编辑'); return; }

        if (route.type === 'json') {
            const fn = ensureExt(sanitizeFileName(route.name, 'route'), '.json');
            downloadObjectAsJson(normalizeRouteGraph(route.rawData, route.name), fn);
            return;
        }
        if (route.type === 'svg') {
            if (!route.rawText) { alert('该SVG路线未保留原始内容，无法导出'); return; }
            const fn = ensureExt(sanitizeFileName(route.name, 'route'), '.svg');
            downloadTextAsFile(route.rawText, fn, 'image/svg+xml;charset=utf-8');
            return;
        }
    };

    STATE.routeManager.exportSelected = async function() {
        const selected = this.selectedIds || new Set();
        const candidates = selected.size ? this.routes.filter(r => selected.has(r.id)) : this.routes.slice();
        if (!candidates.length) { alert('暂无可导出路线'); return; }

        const routes = candidates.filter(r => !r.isEditing);
        if (!routes.length) { alert('请先保存或取消编辑后再导出'); return; }

        if (routes.length === 1) {
            this.exportOne(routes[0].id);
            return;
        }

        const stamp = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        const zipName = `routes_${stamp.getFullYear()}${pad(stamp.getMonth()+1)}${pad(stamp.getDate())}_${pad(stamp.getHours())}${pad(stamp.getMinutes())}${pad(stamp.getSeconds())}.zip`;
        await exportRoutesAsZip(routes, zipName);
    };

    STATE.routeManager.mergeSelected = function() {
        const routes = collectSelectedJsonRoutes(this);
        if (routes.length < 2 || !STATE.mainLayerGroup) return null;

        const name = `${ROUTE_LIST_TEXT.mergedRoutePrefix}_${Date.now()}`;
        const rawData = mergeRouteGraphs(routes, name);
        const layer = L.layerGroup();
        drawJsonOnLayer(layer, rawData);
        STATE.mainLayerGroup.addLayer(layer);

        const mergedRoute = {
            id: `route-${Date.now()}-${Math.random()}`,
            name,
            type: 'json',
            layer,
            rawData,
            visible: true
        };
        this.add(mergedRoute);
        return mergedRoute;
    };

    STATE.routeManager.redraw = function() {
        this.routes.forEach(route => {
            if (!route.visible) return;
            if (route.isEditing) {
                this.updateEditLayer(route);
            } else if (route.type === 'json') {
                route.layer.clearLayers();
                drawJsonOnLayer(route.layer, route.rawData);
            }
        });
    };

    // --- 框选模式逻辑 (New) ---

    // 开启/关闭框选模式
    STATE.routeManager.toggleBoxSelect = function(id) {
        const route = this.routes.find(r => r.id === id);
        if (!route || !route.isEditing) return;

        route.isBoxSelecting = !route.isBoxSelecting;

        const container = STATE.mapInstance.getContainer();
        if (route.isBoxSelecting) {
            // 开启模式：禁用地图拖动，变光标
            STATE.mapInstance.dragging.disable();
            container.classList.add('kmp-crosshair-cursor');
            this.enableBoxSelectEvents(route);
        } else {
            // 关闭模式：恢复地图拖动
            STATE.mapInstance.dragging.enable();
            container.classList.remove('kmp-crosshair-cursor');
            this.disableBoxSelectEvents(route);
        }
        renderRouteListUI();
    };

    // 禁用框选 (用于保存或取消时清理)
    STATE.routeManager.disableBoxSelect = function(route) {
        if (route && route.isBoxSelecting) {
            route.isBoxSelecting = false;
            STATE.mapInstance.dragging.enable();
            STATE.mapInstance.getContainer().classList.remove('kmp-crosshair-cursor');
            this.disableBoxSelectEvents(route);
        }
    };

    // 绑定框选事件
    STATE.routeManager.enableBoxSelectEvents = function(route) {
        const map = STATE.mapInstance;
        let startLatLng = null;
        let selectionBox = null;

        // 1. 按下：记录起点
        route._onMouseDown = (e) => {
            // 如果点到了控制点，且控制点允许交互，可能会冲突。
            // 由于我们在CSS里设置了 crosshair，且逻辑是批量删除，
            // 建议这里直接开始画框，忽略单个点的点击（或者用户需要避开点点击）
            if (e.originalEvent.which !== 1) return; // 只响应左键
            startLatLng = e.latlng;
            selectionBox = L.rectangle(L.latLngBounds(startLatLng, startLatLng), {
                className: 'kmp-select-box',
                pane: 'overlayPane' // 放在最上层
            }).addTo(map);
        };

        // 2. 移动：更新矩形
        route._onMouseMove = (e) => {
            if (!selectionBox || !startLatLng) return;
            const bounds = L.latLngBounds(startLatLng, e.latlng);
            selectionBox.setBounds(bounds);
        };

        // 3. 松开：执行删除
        route._onMouseUp = (e) => {
            if (!selectionBox) return;
            const bounds = selectionBox.getBounds();

            let hasDeleted = false;

            for (let i = route.editingGraph.nodes.length - 1; i >= 0; i--) {
                const node = route.editingGraph.nodes[i];
                const ll = gameToLatLng(node.x, node.y);
                if (bounds.contains(ll)) {
                    deleteGraphNode(route, node.id);
                    hasDeleted = true;
                }
            }

            map.removeLayer(selectionBox);
            selectionBox = null;
            startLatLng = null;

            if (hasDeleted) {
                this.updateEditLayer(route);
            }
        };

        map.on('mousedown', route._onMouseDown);
        map.on('mousemove', route._onMouseMove);
        map.on('mouseup', route._onMouseUp);
    };

    // 解绑框选事件
    STATE.routeManager.disableBoxSelectEvents = function(route) {
        const map = STATE.mapInstance;
        if (route._onMouseDown) map.off('mousedown', route._onMouseDown);
        if (route._onMouseMove) map.off('mousemove', route._onMouseMove);
        if (route._onMouseUp) map.off('mouseup', route._onMouseUp);
        route._onMouseDown = null;
        route._onMouseMove = null;
        route._onMouseUp = null;
    };


    // --- 之前修复过的编辑器逻辑 (startEdit / updateEditLayer) ---

    function ensureEditPanes() {
        const map = STATE.mapInstance;
        if (!map) return;
        if (!map.getPane('kmp-edit-line-pane')) {
            map.createPane('kmp-edit-line-pane');
        }
        map.getPane('kmp-edit-line-pane').style.zIndex = KMP_EDIT_LINE_PANE_Z_INDEX;
        map.getPane('kmp-edit-line-pane').style.pointerEvents = 'none';
        if (!map.getPane('kmp-edit-marker-pane')) {
            map.createPane('kmp-edit-marker-pane');
        }
        map.getPane('kmp-edit-marker-pane').style.zIndex = KMP_EDIT_MARKER_PANE_Z_INDEX;
        map.getPane('kmp-edit-marker-pane').style.pointerEvents = 'none';
        if (!map.getPane('kmp-edit-decoration-pane')) {
            map.createPane('kmp-edit-decoration-pane');
        }
        map.getPane('kmp-edit-decoration-pane').style.zIndex = KMP_EDIT_DECORATION_PANE_Z_INDEX;
        map.getPane('kmp-edit-decoration-pane').style.pointerEvents = 'none';
    }

    function deepCloneJson(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function renderEditVisualLayer(route) {
        const layerGroup = L.layerGroup();
        const graph = route.editingGraph || normalizeRouteGraph(route.rawData, route.name);
        drawGraphOnLayer(
            layerGroup,
            graph,
            { showDirectionArrows: !!route.graphPreviewMode, renderSpecialMarkers: false }
        );
        renderSpecialMarkerGroups(layerGroup, graph, { pane: 'kmp-edit-decoration-pane' });
        return layerGroup;
    }

    function getActiveEditingRoute() {
        return STATE.routeManager.routes.find(route => route && route.isEditing) || null;
    }

    function ensureGraphSelectionState(route) {
        if (!route.graphSelectedIds) route.graphSelectedIds = new Set();
        if (!route.graphSelectionType) route.graphSelectionType = null;
        return route.graphSelectedIds;
    }

    function isGraphElementSelected(route, type, id) {
        ensureGraphSelectionState(route);
        return route.graphSelectionType === type && route.graphSelectedIds.has(id);
    }

    function clearGraphSelection(route) {
        if (!route) return;
        route.graphSelectionType = null;
        route.graphSelectedIds = new Set();
        updateGraphEditToolbar(route);
    }

    function isGraphEditBackgroundEvent(e) {
        const target = (e && e.originalEvent && e.originalEvent.target) || (e && e.target);
        if (!target) return true;
        if (target.closest && target.closest('#kmp-graph-edit-toolbar, #kmp-graph-edit-help, .kmp-edit-popup')) return false;
        if (target.closest && target.closest('.leaflet-interactive, .leaflet-marker-icon, .leaflet-marker-shadow, .leaflet-popup, .leaflet-tooltip')) return false;
        return true;
    }

    function syncGraphBoxSelectionMapDrag(route) {
        const map = STATE.mapInstance;
        if (!map || !map.dragging || !route) return;
        if (route.graphBoxSelectMode) {
            if (!route._graphHadDragging && map.dragging.enabled()) {
                route._graphHadDragging = true;
                map.dragging.disable();
            }
        } else if (route._graphHadDragging) {
            map.dragging.enable();
            route._graphHadDragging = false;
        }
    }

    function setExclusiveGraphEditMode(route, mode, enabled = true) {
        if (!route) return;
        const activeMode = enabled ? mode : null;
        route.continuousDrawMode = activeMode === 'draw';
        route.continuousDrawLastNodeId = null;
        route.markerAssociationMode = activeMode === 'markers';
        route.continuousSelectionMode = activeMode === 'selection';
        route.graphBoxSelectMode = activeMode === 'box-node'
            ? 'node'
            : activeMode === 'box-edge' ? 'edge' : null;
        route.graphPreviewMode = activeMode === 'preview';
        route.specialMarkerGroupMode = activeMode === 'special-groups';
        route.specialMarkerAddingGroupId = null;
        if (!route.specialMarkerGroupMode) {
            route.specialMarkerSelectedGroupId = null;
            closeSpecialMarkerStyleModal(route, false);
        }
        if (route.specialMarkerGroupMode) {
            route.graphSelectionType = null;
            route.graphSelectedIds = new Set();
            route.pendingConnectFromNodeId = null;
            removeEditConnectionPreview(route);
        }
        if (route.markerAssociationMode) installRouteMarkerAssociationCapture();
        syncGraphBoxSelectionMapDrag(route);
        try { STATE.mapInstance.closePopup(); } catch (e) {}
        refreshGraphEditRoute(route);
        scheduleRouteMarkerDisplay(`edit-mode:${activeMode || 'none'}`);
    }

    function setGraphBoxSelectMode(route, mode) {
        if (!route) return;
        setExclusiveGraphEditMode(route, `box-${mode}`, route.graphBoxSelectMode !== mode);
    }

    function selectSingleGraphElement(route, type, id) {
        route.graphSelectionType = type;
        route.graphSelectedIds = new Set([id]);
        updateGraphEditToolbar(route);
    }

    function toggleGraphSelection(route, type, id) {
        const selected = ensureGraphSelectionState(route);
        if (route.graphSelectionType && route.graphSelectionType !== type) return false;
        route.graphSelectionType = type;
        if (selected.has(id)) selected.delete(id);
        else selected.add(id);
        if (!selected.size) route.graphSelectionType = null;
        updateGraphEditToolbar(route);
        return true;
    }

    function refreshGraphEditRoute(route) {
        updateGraphEditToolbar(route);
        updateGraphEditHelpPanel(route);
        updateSpecialMarkerGroupSidebar(route);
        STATE.routeManager.updateEditLayer(route);
    }

    function createEditHitPolyline(group, latLngs, route, svgRenderer, selected = false) {
        return L.polyline(latLngs, {
            color: '#ffffff',
            opacity: selected ? 0.9 : 0,
            weight: Number(SETTINGS.pathWeight) + 15,
            className: selected ? 'kmp-hit-line kmp-selected-edge' : 'kmp-hit-line',
            pane: 'kmp-edit-line-pane',
            renderer: svgRenderer,
            interactive: !route.isBoxSelecting && !route.graphPreviewMode && !route.specialMarkerGroupMode
        }).addTo(group);
    }

    function drawEditDirectionArrow(group, fromLatLng, toLatLng, state) {
        const map = STATE.mapInstance;
        if (!map) return null;
        const from = L.latLng(fromLatLng);
        const to = L.latLng(toLatLng);
        if (!Number.isFinite(from.lat) || !Number.isFinite(from.lng) || !Number.isFinite(to.lat) || !Number.isFinite(to.lng)) {
            return null;
        }
        const fromPoint = map.latLngToLayerPoint(from);
        const toPoint = map.latLngToLayerPoint(to);
        const angle = Math.atan2(toPoint.y - fromPoint.y, toPoint.x - fromPoint.x) * 180 / Math.PI;
        const midLat = (from.lat + to.lat) / 2;
        const midLng = (from.lng + to.lng) / 2;
        const classes = ['kmp-edit-arrow'];
        if (state && state.selected) classes.push('selected');
        if (state && state.hover) classes.push('hover');
        const sizePx = 18;
        const scale = state && (state.selected || state.hover) ? 1.2 : 1;
        const icon = L.divIcon({
            className: '',
            html: createRouteDirectionArrowHtml(angle, sizePx, {
                className: classes.join(' '),
                fill: state && (state.selected || state.hover) ? '#dcb268' : '#f7e5be',
                stroke: '#fff',
                strokeWidth: 0.5,
                scale
            }),
            iconSize: [18, 18],
            iconAnchor: [9, 9]
        });
        return L.marker([midLat, midLng], { icon, interactive: false, pane: 'kmp-arrow-pane' }).addTo(group);
    }

    function getGraphNodeById(graph, nodeId) {
        return (graph.nodes || []).find(node => node.id === nodeId) || null;
    }

    function getGraphEdgeById(graph, edgeId) {
        return (graph.edges || []).find(edge => edge.id === edgeId) || null;
    }

    function nextGraphNodeId(graph) {
        return makeGraphNodeId((graph.nodes || []).length + 1 + Math.floor(Math.random() * 1000000));
    }

    function nextGraphEdgeId(graph) {
        return makeGraphEdgeId((graph.edges || []).length + 1 + Math.floor(Math.random() * 1000000));
    }

    function deleteGraphEdge(route, edgeId) {
        const graph = route.editingGraph;
        const idx = graph.edges.findIndex(edge => edge.id === edgeId);
        if (idx < 0) return false;
        graph.edges.splice(idx, 1);
        if (route.graphSelectedIds) route.graphSelectedIds.delete(edgeId);
        if (route.graphSelectedIds && !route.graphSelectedIds.size) route.graphSelectionType = null;
        return true;
    }

    function reverseGraphEdge(route, edgeId) {
        const edge = getGraphEdgeById(route.editingGraph, edgeId);
        if (!edge) return false;
        const oldFrom = edge.from;
        edge.from = edge.to;
        edge.to = oldFrom;
        return true;
    }

    function reverseSelectedGraphEdges(route) {
        ensureGraphSelectionState(route);
        if (route.graphSelectionType !== 'edge') return false;
        Array.from(route.graphSelectedIds).forEach(edgeId => reverseGraphEdge(route, edgeId));
        return true;
    }

    function deleteSelectedGraphEdges(route) {
        ensureGraphSelectionState(route);
        if (route.graphSelectionType !== 'edge') return false;
        Array.from(route.graphSelectedIds).forEach(edgeId => deleteGraphEdge(route, edgeId));
        clearGraphSelection(route);
        return true;
    }

    function deleteSelectedGraphNodes(route) {
        ensureGraphSelectionState(route);
        if (route.graphSelectionType !== 'node') return false;
        Array.from(route.graphSelectedIds).forEach(nodeId => deleteGraphNode(route, nodeId));
        clearGraphSelection(route);
        return true;
    }

    function insertNodeOnEdge(route, edge, latlng) {
        const graph = route.editingGraph;
        const fromNode = getGraphNodeById(graph, edge.from);
        if (!fromNode) return false;
        const gamePos = latLngToGame(latlng.lat, latlng.lng);
        const node = {
            id: nextGraphNodeId(graph),
            x: normalizeRouteCoordinate(gamePos.x),
            y: normalizeRouteCoordinate(gamePos.y),
            z: normalizeRouteCoordinate(fromNode.z)
        };
        graph.nodes.push(node);
        deleteGraphEdge(route, edge.id);
        graph.edges.push({ id: nextGraphEdgeId(graph), from: edge.from, to: node.id });
        graph.edges.push({ id: nextGraphEdgeId(graph), from: node.id, to: edge.to });
        return true;
    }

    function addGraphNodeAtLatLng(route, latlng) {
        const graph = route && route.editingGraph;
        if (!graph || !latlng) return null;
        const gamePos = latLngToGame(latlng.lat, latlng.lng);
        const node = {
            id: nextGraphNodeId(graph),
            x: normalizeRouteCoordinate(gamePos.x),
            y: normalizeRouteCoordinate(gamePos.y),
            z: 0
        };
        graph.nodes.push(node);
        const previousNode = route.continuousDrawMode && route.continuousDrawLastNodeId
            ? getGraphNodeById(graph, route.continuousDrawLastNodeId)
            : null;
        if (previousNode) {
            graph.edges.push({ id: nextGraphEdgeId(graph), from: previousNode.id, to: node.id });
        }
        if (route.continuousDrawMode) route.continuousDrawLastNodeId = node.id;
        selectSingleGraphElement(route, 'node', node.id);
        return node;
    }

    function removeNodeFromSpecialMarkerGroups(graph, nodeId) {
        (graph.special_marker_groups || []).forEach(group => {
            group.node_ids = (group.node_ids || []).filter(id => id !== nodeId);
        });
    }

    function createSpecialMarkerGroupId(graph) {
        const usedIds = new Set((graph && graph.special_marker_groups || []).map(group => group.id));
        let index = 1;
        while (usedIds.has(`smg${index}`)) index++;
        return `smg${index}`;
    }

    function addNodeToSpecialMarkerGroup(route, groupId, nodeId) {
        const graph = route && route.editingGraph;
        if (!graph || !(graph.nodes || []).some(node => node.id === nodeId)) return false;
        const targetGroup = (graph.special_marker_groups || []).find(group => group.id === groupId);
        if (!targetGroup) return false;
        const targetNodeIds = targetGroup.node_ids || [];
        if (targetNodeIds.includes(nodeId)) return false;
        (graph.special_marker_groups || []).forEach(group => {
            if (group !== targetGroup) group.node_ids = (group.node_ids || []).filter(id => id !== nodeId);
        });
        targetGroup.node_ids = targetNodeIds;
        targetGroup.node_ids.push(nodeId);
        return true;
    }

    function removeNodeFromSpecialMarkerGroup(route, groupId, nodeId) {
        const graph = route && route.editingGraph;
        const group = graph && (graph.special_marker_groups || []).find(item => item.id === groupId);
        if (!group || !(group.node_ids || []).includes(nodeId)) return false;
        group.node_ids = group.node_ids.filter(id => id !== nodeId);
        return true;
    }

    function moveSpecialMarkerGroupMember(route, groupId, nodeId, direction) {
        const graph = route && route.editingGraph;
        const group = graph && (graph.special_marker_groups || []).find(item => item.id === groupId);
        if (!group) return false;
        const currentIndex = (group.node_ids || []).indexOf(nodeId);
        const targetIndex = direction === 'up'
            ? currentIndex - 1
            : direction === 'down' ? currentIndex + 1 : currentIndex;
        if (currentIndex < 0 || targetIndex < 0 || targetIndex >= group.node_ids.length || targetIndex === currentIndex) {
            return false;
        }
        [group.node_ids[currentIndex], group.node_ids[targetIndex]] = [group.node_ids[targetIndex], group.node_ids[currentIndex]];
        return true;
    }

    function deleteSpecialMarkerGroup(route, groupId) {
        const graph = route && route.editingGraph;
        if (!graph) return false;
        const groupIndex = (graph.special_marker_groups || []).findIndex(group => group.id === groupId);
        if (groupIndex < 0) return false;
        graph.special_marker_groups.splice(groupIndex, 1);
        return true;
    }

    function createSpecialMarkerPreviewHtml(style, numberValue = 1, extraClass = '') {
        const normalized = normalizeSpecialMarkerStyle(style);
        const outline = normalized.number.outline;
        const outlineStyle = outline.enabled
            ? `-webkit-text-stroke:${outline.width}px ${outline.color};paint-order:stroke fill;`
            : '';
        const numberStyle = `font-size:${normalized.number.font_size}px;color:${normalized.number.color};${outlineStyle}`;
        return `<div class="kmp-route-node-style kmp-special-marker-preview ${extraClass}" style="--node-color:${normalized.fill_color}"><span class="kmp-route-node-core kmp-special-marker-shape ${normalized.shape}"></span><span class="kmp-route-node-text" style="${numberStyle}">${numberValue}</span></div>`;
    }

    function createSpecialMarkerColorPicker(container, initialColor, onChange) {
        const initialRgb = hexToRgb(initialColor) || hexToRgb(DEFAULT_SPECIAL_MARKER_STYLE.fill_color);
        const hsv = rgbToHsv(initialRgb.r, initialRgb.g, initialRgb.b);
        const state = { h: hsv.h, s: hsv.s, v: hsv.v };
        container.className = 'kmp-special-color-picker';
        container.innerHTML = `
            <div class="kmp-color-sv"><span class="kmp-color-sv-cursor"></span></div>
            <input class="kmp-color-hue" type="range" min="0" max="360" step="1" aria-label="${SPECIAL_MARKER_GROUP_TEXT.hue}">
            <div class="kmp-color-row">
                <span class="kmp-color-preview"></span>
                <input class="kmp-color-hex" type="text" maxlength="7" aria-label="${SPECIAL_MARKER_GROUP_TEXT.hex}">
            </div>
        `;
        const svPanel = container.querySelector('.kmp-color-sv');
        const svCursor = container.querySelector('.kmp-color-sv-cursor');
        const hueInput = container.querySelector('.kmp-color-hue');
        const preview = container.querySelector('.kmp-color-preview');
        const hexInput = container.querySelector('.kmp-color-hex');

        const currentHex = () => {
            const rgb = hsvToRgb(state.h, state.s, state.v);
            return rgbToHex(rgb.r, rgb.g, rgb.b);
        };
        const render = emit => {
            const hex = currentHex();
            svPanel.style.backgroundColor = `hsl(${state.h}, 100%, 50%)`;
            svCursor.style.left = `${state.s}%`;
            svCursor.style.top = `${100 - state.v}%`;
            hueInput.value = String(Math.round(state.h));
            preview.style.background = hex;
            hexInput.value = hex;
            if (emit && typeof onChange === 'function') onChange(hex);
        };
        const updateFromPointer = event => {
            const rect = svPanel.getBoundingClientRect();
            if (!rect.width || !rect.height) return;
            state.s = Math.min(100, Math.max(0, ((event.clientX - rect.left) / rect.width) * 100));
            state.v = 100 - Math.min(100, Math.max(0, ((event.clientY - rect.top) / rect.height) * 100));
            render(true);
        };
        let dragging = false;
        svPanel.addEventListener('pointerdown', event => {
            dragging = true;
            if (svPanel.setPointerCapture) svPanel.setPointerCapture(event.pointerId);
            updateFromPointer(event);
        });
        svPanel.addEventListener('pointermove', event => {
            if (dragging) updateFromPointer(event);
        });
        const stopDragging = () => { dragging = false; };
        svPanel.addEventListener('pointerup', stopDragging);
        svPanel.addEventListener('pointercancel', stopDragging);
        hueInput.addEventListener('input', () => {
            state.h = Number(hueInput.value);
            render(true);
        });
        hexInput.addEventListener('change', () => {
            const rgb = hexToRgb(hexInput.value);
            if (!rgb) {
                render(false);
                return;
            }
            const next = rgbToHsv(rgb.r, rgb.g, rgb.b);
            state.h = next.h;
            state.s = next.s;
            state.v = next.v;
            render(true);
        });
        render(false);
        return { getColor: currentHex };
    }

    function refreshSpecialMarkerGroupPreview(route) {
        if (route && route.isEditing && route.editorGroup) STATE.routeManager.updateEditLayer(route);
        updateSpecialMarkerGroupSidebar(route);
    }

    function closeSpecialMarkerStyleModal(route, keepChanges) {
        const modal = document.getElementById('kmp-special-marker-style-modal');
        if (!modal) return false;
        const state = modal._specialMarkerState;
        if (!keepChanges && state && !state.isNew) {
            restoreSpecialMarkerGroupStyle(state.route, state.groupId, state.snapshot);
        }
        modal.remove();
        refreshSpecialMarkerGroupPreview((state && state.route) || route);
        return true;
    }

    function openSpecialMarkerStyleModal(route, groupId = null) {
        if (!route || !route.editingGraph) return;
        closeSpecialMarkerStyleModal(route, false);
        const groups = route.editingGraph.special_marker_groups || [];
        const group = groupId ? groups.find(item => item.id === groupId) : null;
        if (groupId && !group) return;
        const isNew = !group;
        const draft = createSpecialMarkerStyleDraft(group ? group.style : DEFAULT_SPECIAL_MARKER_STYLE);
        const snapshot = group ? createSpecialMarkerStyleDraft(group.style) : null;
        const modal = document.createElement('div');
        modal.id = 'kmp-special-marker-style-modal';
        modal._specialMarkerState = { route, groupId, isNew, draft, snapshot };
        modal.innerHTML = `
            <div class="kmp-special-modal-panel" role="dialog" aria-modal="true">
                <div class="kmp-special-modal-header">${isNew ? SPECIAL_MARKER_GROUP_TEXT.createTitle : SPECIAL_MARKER_GROUP_TEXT.editTitle}</div>
                <div class="kmp-special-modal-body">
                    <div>
                        <section class="kmp-special-modal-section">
                            <span class="kmp-special-modal-label">${SPECIAL_MARKER_GROUP_TEXT.shape}</span>
                            <div class="kmp-special-shape-grid">
                                ${SPECIAL_MARKER_SHAPES.map(shape => `<button type="button" class="kmp-special-shape-option${shape === draft.shape ? ' active' : ''}" data-shape="${shape}">${createSpecialMarkerPreviewHtml({ ...draft, shape }, 1)}<span>${SPECIAL_MARKER_GROUP_TEXT.shapeLabels[shape]}</span></button>`).join('')}
                            </div>
                        </section>
                        <section class="kmp-special-modal-section">
                            <span class="kmp-special-modal-label">${SPECIAL_MARKER_GROUP_TEXT.fillColor}</span>
                            <div data-color-picker="fill"></div>
                        </section>
                    </div>
                    <div>
                        <section class="kmp-special-modal-section">
                            <span class="kmp-special-modal-label">${SPECIAL_MARKER_GROUP_TEXT.preview}</span>
                            <div class="kmp-special-preview-stage" data-style-preview></div>
                        </section>
                        <section class="kmp-special-modal-section">
                            <span class="kmp-special-modal-label">${SPECIAL_MARKER_GROUP_TEXT.numberColor}</span>
                            <div data-color-picker="number"></div>
                        </section>
                        <section class="kmp-special-modal-section kmp-special-number-row">
                            <label><span class="kmp-special-modal-label">${SPECIAL_MARKER_GROUP_TEXT.numberSize}</span><input class="kmp-special-number-input" data-style-input="font-size" type="number" min="8" max="72" value="${draft.number.font_size}"></label>
                            <label><span class="kmp-special-modal-label">${SPECIAL_MARKER_GROUP_TEXT.outlineWidth}</span><input class="kmp-special-number-input" data-style-input="outline-width" type="number" min="0" max="8" step="1" value="${draft.number.outline.width}"></label>
                        </section>
                        <section class="kmp-special-modal-section">
                            <label><input data-style-input="outline-enabled" type="checkbox"${draft.number.outline.enabled ? ' checked' : ''}> ${SPECIAL_MARKER_GROUP_TEXT.outlineEnabled}</label>
                        </section>
                        <section class="kmp-special-modal-section">
                            <span class="kmp-special-modal-label">${SPECIAL_MARKER_GROUP_TEXT.outlineColor}</span>
                            <div data-color-picker="outline"></div>
                        </section>
                    </div>
                </div>
                <div class="kmp-special-modal-actions">
                    <button type="button" class="kmp-special-modal-btn" data-modal-action="cancel">${SPECIAL_MARKER_GROUP_TEXT.cancel}</button>
                    <button type="button" class="kmp-special-modal-btn primary" data-modal-action="confirm">${isNew ? SPECIAL_MARKER_GROUP_TEXT.create : SPECIAL_MARKER_GROUP_TEXT.done}</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        const state = modal._specialMarkerState;
        const renderDraft = () => {
            modal.querySelector('[data-style-preview]').innerHTML = createSpecialMarkerPreviewHtml(state.draft, 1);
            modal.querySelectorAll('.kmp-special-shape-option').forEach(button => {
                button.classList.toggle('active', button.dataset.shape === state.draft.shape);
            });
        };
        const applyDraft = mutator => {
            mutator(state.draft);
            state.draft = createSpecialMarkerStyleDraft(state.draft);
            if (!state.isNew) {
                const target = route.editingGraph.special_marker_groups.find(item => item.id === state.groupId);
                if (target) target.style = createSpecialMarkerStyleDraft(state.draft);
            }
            renderDraft();
            if (!state.isNew) refreshSpecialMarkerGroupPreview(route);
        };
        modal.querySelectorAll('.kmp-special-shape-option').forEach(button => {
            button.addEventListener('click', () => applyDraft(next => { next.shape = button.dataset.shape; }));
        });
        modal.querySelector('[data-style-input="font-size"]').addEventListener('input', event => {
            applyDraft(next => { next.number.font_size = event.target.value; });
        });
        modal.querySelector('[data-style-input="outline-width"]').addEventListener('input', event => {
            applyDraft(next => { next.number.outline.width = event.target.value; });
        });
        modal.querySelector('[data-style-input="outline-enabled"]').addEventListener('change', event => {
            applyDraft(next => { next.number.outline.enabled = event.target.checked; });
        });
        createSpecialMarkerColorPicker(modal.querySelector('[data-color-picker="fill"]'), draft.fill_color, color => {
            applyDraft(next => { next.fill_color = color; });
        });
        createSpecialMarkerColorPicker(modal.querySelector('[data-color-picker="number"]'), draft.number.color, color => {
            applyDraft(next => { next.number.color = color; });
        });
        createSpecialMarkerColorPicker(modal.querySelector('[data-color-picker="outline"]'), draft.number.outline.color, color => {
            applyDraft(next => { next.number.outline.color = color; });
        });
        modal.querySelector('[data-modal-action="cancel"]').addEventListener('click', () => closeSpecialMarkerStyleModal(route, false));
        modal.querySelector('[data-modal-action="confirm"]').addEventListener('click', () => {
            if (state.isNew) {
                const id = createSpecialMarkerGroupId(route.editingGraph);
                route.editingGraph.special_marker_groups.push({ id, style: createSpecialMarkerStyleDraft(state.draft), node_ids: [] });
                route.specialMarkerSelectedGroupId = id;
            }
            closeSpecialMarkerStyleModal(route, true);
        });
        renderDraft();
    }

    function updateSpecialMarkerGroupSidebar(route) {
        let sidebar = document.getElementById('kmp-special-marker-sidebar');
        if (!sidebar) {
            sidebar = document.createElement('aside');
            sidebar.id = 'kmp-special-marker-sidebar';
            document.body.appendChild(sidebar);
        }
        if (!sidebar.dataset.eventsBound) {
            sidebar.addEventListener('click', event => {
                const target = event.target.closest('[data-special-action]');
                if (!target || !sidebar.contains(target)) return;
                const activeRoute = getActiveEditingRoute();
                if (!activeRoute || !activeRoute.specialMarkerGroupMode || !activeRoute.editingGraph) return;
                const action = target.dataset.specialAction;
                const groupId = target.dataset.groupId || null;
                const nodeId = target.dataset.nodeId || null;
                const groups = activeRoute.editingGraph.special_marker_groups || [];
                if (action === 'create-group') {
                    openSpecialMarkerStyleModal(activeRoute);
                    return;
                }
                if (action === 'select-group') {
                    activeRoute.specialMarkerSelectedGroupId = groupId;
                    updateSpecialMarkerGroupSidebar(activeRoute);
                    return;
                }
                if (action === 'toggle-add') {
                    activeRoute.specialMarkerSelectedGroupId = groupId;
                    activeRoute.specialMarkerAddingGroupId = activeRoute.specialMarkerAddingGroupId === groupId ? null : groupId;
                    updateSpecialMarkerGroupSidebar(activeRoute);
                    return;
                }
                if (action === 'edit-style') {
                    activeRoute.specialMarkerSelectedGroupId = groupId;
                    openSpecialMarkerStyleModal(activeRoute, groupId);
                    updateSpecialMarkerGroupSidebar(activeRoute);
                    return;
                }
                if (action === 'delete-group') {
                    const index = groups.findIndex(group => group.id === groupId);
                    if (index < 0 || !deleteSpecialMarkerGroup(activeRoute, groupId)) return;
                    if (activeRoute.specialMarkerAddingGroupId === groupId) activeRoute.specialMarkerAddingGroupId = null;
                    const remaining = activeRoute.editingGraph.special_marker_groups;
                    activeRoute.specialMarkerSelectedGroupId = remaining.length ? remaining[Math.min(index, remaining.length - 1)].id : null;
                    refreshGraphEditRoute(activeRoute);
                    return;
                }
                if (action === 'move-up' || action === 'move-down') {
                    if (moveSpecialMarkerGroupMember(activeRoute, groupId, nodeId, action === 'move-up' ? 'up' : 'down')) {
                        refreshGraphEditRoute(activeRoute);
                    }
                    return;
                }
                if (action === 'remove-member' && removeNodeFromSpecialMarkerGroup(activeRoute, groupId, nodeId)) {
                    refreshGraphEditRoute(activeRoute);
                }
            });
            sidebar.dataset.eventsBound = 'true';
        }
        if (!route || !route.isEditing || !route.specialMarkerGroupMode || !route.editingGraph) {
            sidebar.style.display = 'none';
            return;
        }
        const groups = route.editingGraph.special_marker_groups || [];
        const selected = groups.find(group => group.id === route.specialMarkerSelectedGroupId) || null;
        const nodeById = new Map((route.editingGraph.nodes || []).map(node => [node.id, node]));
        const treeHtml = groups.length ? groups.map((group, groupIndex) => {
            const isSelected = selected && selected.id === group.id;
            const isAdding = route.specialMarkerAddingGroupId === group.id;
            const escapedGroupId = escapeHtml(String(group.id));
            const members = group.node_ids.map((nodeId, memberIndex) => {
                const node = nodeById.get(nodeId);
                if (!node) return '';
                const escapedNodeId = escapeHtml(String(nodeId));
                return `<div class="kmp-special-member-row"><span>${memberIndex + 1}. ${normalizeRouteCoordinate(node.x)}, ${normalizeRouteCoordinate(node.y)}</span><span class="kmp-special-member-actions"><button type="button" class="kmp-special-member-btn" data-special-action="move-up" data-group-id="${escapedGroupId}" data-node-id="${escapedNodeId}"${memberIndex === 0 ? ' disabled' : ''}>${SPECIAL_MARKER_GROUP_TEXT.moveUp}</button><button type="button" class="kmp-special-member-btn" data-special-action="move-down" data-group-id="${escapedGroupId}" data-node-id="${escapedNodeId}"${memberIndex === group.node_ids.length - 1 ? ' disabled' : ''}>${SPECIAL_MARKER_GROUP_TEXT.moveDown}</button><button type="button" class="kmp-special-member-btn danger" data-special-action="remove-member" data-group-id="${escapedGroupId}" data-node-id="${escapedNodeId}">${SPECIAL_MARKER_GROUP_TEXT.removeMember}</button></span></div>`;
            }).join('');
            return `<details class="kmp-special-group${isSelected ? ' selected' : ''}" data-group-id="${escapedGroupId}"${isSelected ? ' open' : ''}><summary data-special-action="select-group" data-group-id="${escapedGroupId}">${SPECIAL_MARKER_GROUP_TEXT.groupLabel}${groupIndex + 1} (${group.node_ids.length})</summary><div class="kmp-special-group-actions"><button type="button" class="kmp-special-sidebar-btn${isAdding ? ' active' : ''}" data-special-action="toggle-add" data-group-id="${escapedGroupId}">${isAdding ? SPECIAL_MARKER_GROUP_TEXT.stopAdding : SPECIAL_MARKER_GROUP_TEXT.addNode}</button><button type="button" class="kmp-special-sidebar-btn" data-special-action="edit-style" data-group-id="${escapedGroupId}">${SPECIAL_MARKER_GROUP_TEXT.editStyle}</button><button type="button" class="kmp-special-sidebar-btn danger" data-special-action="delete-group" data-group-id="${escapedGroupId}">${SPECIAL_MARKER_GROUP_TEXT.deleteGroup}</button></div><div class="kmp-special-member-list">${members || `<div class="kmp-special-empty">${SPECIAL_MARKER_GROUP_TEXT.emptyMembers}</div>`}</div></details>`;
        }).join('') : `<div class="kmp-special-empty">${SPECIAL_MARKER_GROUP_TEXT.emptyGroups}</div>`;
        const selectedIndex = selected ? groups.indexOf(selected) : -1;
        const escapedSelectedGroupId = selected ? escapeHtml(String(selected.id)) : '';
        const summaryHtml = selected
            ? `<div class="kmp-special-summary-header"><strong>${SPECIAL_MARKER_GROUP_TEXT.styleSummary}</strong><button type="button" class="kmp-special-sidebar-btn" data-special-action="edit-style" data-group-id="${escapedSelectedGroupId}">${SPECIAL_MARKER_GROUP_TEXT.editStyle}</button></div><div class="kmp-special-summary-body">${createSpecialMarkerPreviewHtml(selected.style, 1)}<div class="kmp-special-summary-meta">${SPECIAL_MARKER_GROUP_TEXT.groupLabel}${selectedIndex + 1}<br>${selected.node_ids.length} ${SPECIAL_MARKER_GROUP_TEXT.members}<br>${SPECIAL_MARKER_GROUP_TEXT.shapeLabels[normalizeSpecialMarkerStyle(selected.style).shape]}</div></div>`
            : `<div class="kmp-special-empty">${SPECIAL_MARKER_GROUP_TEXT.noSelection}</div>`;
        sidebar.innerHTML = `<div class="kmp-special-sidebar-layout"><div class="kmp-special-sidebar-header"><span>${SPECIAL_MARKER_GROUP_TEXT.sidebarTitle}</span><button type="button" class="kmp-special-sidebar-btn" data-special-action="create-group">${SPECIAL_MARKER_GROUP_TEXT.createGroup}</button></div><div class="kmp-special-sidebar-tree">${treeHtml}</div><div class="kmp-special-sidebar-summary">${summaryHtml}</div></div>`;
        sidebar.style.display = 'block';
    }

    function deleteGraphNode(route, nodeId) {
        const graph = route.editingGraph;
        removeNodeFromSpecialMarkerGroups(graph, nodeId);
        graph.nodes = graph.nodes.filter(node => node.id !== nodeId);
        graph.edges = graph.edges.filter(edge => edge.from !== nodeId && edge.to !== nodeId);
        if (route.pendingConnectFromNodeId === nodeId) route.pendingConnectFromNodeId = null;
        if (route.graphSelectedIds) route.graphSelectedIds.delete(nodeId);
        if (route.graphSelectedIds && !route.graphSelectedIds.size) route.graphSelectionType = null;
        return true;
    }

    function deleteAdjacentGraphNode(route, edgeId, side) {
        const graph = route.editingGraph;
        const edge = getGraphEdgeById(graph, edgeId);
        if (!edge) return false;
        const nodeId = side === 'prev' ? edge.from : edge.to;
        const incoming = graph.edges.filter(item => item.to === nodeId);
        const outgoing = graph.edges.filter(item => item.from === nodeId);
        if (incoming.length === 1 && outgoing.length === 1) {
            const fromNodeId = incoming[0].from;
            const toNodeId = outgoing[0].to;
            removeNodeFromSpecialMarkerGroups(graph, nodeId);
            graph.nodes = graph.nodes.filter(node => node.id !== nodeId);
            graph.edges = graph.edges.filter(item => item.from !== nodeId && item.to !== nodeId);
            if (fromNodeId !== toNodeId && !graph.edges.some(item => item.from === fromNodeId && item.to === toNodeId)) {
                graph.edges.push({ id: nextGraphEdgeId(graph), from: fromNodeId, to: toNodeId });
            }
            return true;
        }
        return deleteGraphNode(route, nodeId);
    }

    function connectGraphNodes(route, fromNodeId, toNodeId) {
        const graph = route.editingGraph;
        if (!fromNodeId || !toNodeId || fromNodeId === toNodeId) return false;
        if (!getGraphNodeById(graph, fromNodeId) || !getGraphNodeById(graph, toNodeId)) return false;
        const exists = graph.edges.some(edge => edge.from === fromNodeId && edge.to === toNodeId);
        if (exists) return false;
        graph.edges.push({ id: nextGraphEdgeId(graph), from: fromNodeId, to: toNodeId });
        return true;
    }

    function createEditConnectionPreview(route) {
        if (!route || route.connectionPreview) return route && route.connectionPreview;
        route.connectionPreview = L.polyline([], {
            className: 'kmp-connect-preview',
            pane: 'kmp-edit-line-pane',
            interactive: false
        }).addTo(route.editorGroup);
        return route.connectionPreview;
    }

    function updateEditConnectionPreview(route, latlng) {
        if (!route || !route.pendingConnectFromNodeId) return;
        const node = getGraphNodeById(route.editingGraph, route.pendingConnectFromNodeId);
        if (!node) return;
        const preview = createEditConnectionPreview(route);
        preview.setLatLngs([gameToLatLng(node.x, node.y), latlng]);
    }

    function removeEditConnectionPreview(route) {
        if (!route || !route.connectionPreview) return;
        try { route.editorGroup.removeLayer(route.connectionPreview); } catch (e) {}
        route.connectionPreview = null;
    }

    function graphPopupButton(id, handler) {
        setTimeout(() => {
            const btn = document.getElementById(id);
            if (btn) btn.onclick = handler;
        }, 50);
    }

    function updateGraphEditToolbar(route) {
        let toolbar = document.getElementById('kmp-graph-edit-toolbar');
        if (!toolbar) {
            toolbar = document.createElement('div');
            toolbar.id = 'kmp-graph-edit-toolbar';
            toolbar.innerHTML = `
                <button type="button" id="kmp-toolbar-draw-mode">连续绘制</button>
                <button type="button" id="kmp-toolbar-route-markers">关联标记点</button>
                <button type="button" id="kmp-toolbar-special-groups">${SPECIAL_MARKER_GROUP_TEXT.toolbar}</button>
                <button type="button" id="kmp-toolbar-continuous">连续选择</button>
                <button type="button" id="kmp-toolbar-box-node">框选节点</button>
                <button type="button" id="kmp-toolbar-box-edge">框选路线</button>
                <label id="kmp-toolbar-preview-wrap"><input type="checkbox" id="kmp-toolbar-preview"> 预览</label>
                <span class="kmp-toolbar-status" id="kmp-toolbar-status">未选择</span>
                <button type="button" id="kmp-toolbar-reverse">反转方向</button>
                <button type="button" class="danger" id="kmp-toolbar-delete">删除</button>
                <button type="button" id="kmp-toolbar-clear">取消选中</button>
                <span class="kmp-toolbar-commit-group">
                    <button type="button" id="kmp-toolbar-save">保存</button>
                    <button type="button" id="kmp-toolbar-cancel">取消</button>
                </span>
            `;
            document.body.appendChild(toolbar);
        }
        const activeRoute = route || getActiveEditingRoute();
        if (!activeRoute || !activeRoute.isEditing) {
            toolbar.style.display = 'none';
            return;
        }
        ensureGraphSelectionState(activeRoute);
        toolbar.style.display = 'flex';
        const count = activeRoute.graphSelectedIds.size;
        const typeLabel = activeRoute.graphSelectionType === 'node' ? '节点' : activeRoute.graphSelectionType === 'edge' ? '线段' : '';
        const normalSelectionActionsEnabled = !activeRoute.specialMarkerGroupMode && count > 0;
        const status = document.getElementById('kmp-toolbar-status');
        if (status) {
            status.style.display = activeRoute.specialMarkerGroupMode ? 'none' : '';
            status.innerText = count ? `已选 ${count} ${typeLabel}` : '未选择';
        }

        const drawModeBtn = document.getElementById('kmp-toolbar-draw-mode');
        const routeMarkersBtn = document.getElementById('kmp-toolbar-route-markers');
        const specialGroupsBtn = document.getElementById('kmp-toolbar-special-groups');
        const continuousBtn = document.getElementById('kmp-toolbar-continuous');
        const previewInput = document.getElementById('kmp-toolbar-preview');
        const previewWrap = document.getElementById('kmp-toolbar-preview-wrap');
        const reverseBtn = document.getElementById('kmp-toolbar-reverse');
        const deleteBtn = document.getElementById('kmp-toolbar-delete');
        const saveEditBtn = document.getElementById('kmp-toolbar-save');
        const cancelEditBtn = document.getElementById('kmp-toolbar-cancel');
        if (drawModeBtn) {
            drawModeBtn.classList.toggle('active', !!activeRoute.continuousDrawMode);
            drawModeBtn.title = activeRoute.continuousDrawMode
                ? '右键立即添加节点，并与上一个连续绘制节点相连'
                : '右键打开节点插入菜单';
            drawModeBtn.onclick = () => {
                setExclusiveGraphEditMode(activeRoute, 'draw', !activeRoute.continuousDrawMode);
            };
        }
        if (routeMarkersBtn) {
            const markerCount = getRouteAssociatedMarkers(activeRoute).length;
            routeMarkersBtn.innerText = `关联标记点(${markerCount})`;
            routeMarkersBtn.classList.toggle('active', !!activeRoute.markerAssociationMode);
            routeMarkersBtn.title = activeRoute.markerAssociationMode
                ? '点击官方地图标记点可添加或移除关联'
                : '进入官方地图标记点关联模式';
            routeMarkersBtn.onclick = () => setRouteMarkerAssociationMode(activeRoute, !activeRoute.markerAssociationMode);
        }
        if (specialGroupsBtn) {
            specialGroupsBtn.classList.toggle('active', !!activeRoute.specialMarkerGroupMode);
            specialGroupsBtn.onclick = () => {
                setExclusiveGraphEditMode(activeRoute, 'special-groups', !activeRoute.specialMarkerGroupMode);
            };
        }
        if (continuousBtn) {
            continuousBtn.classList.toggle('active', !!activeRoute.continuousSelectionMode);
            continuousBtn.onclick = () => {
                setExclusiveGraphEditMode(activeRoute, 'selection', !activeRoute.continuousSelectionMode);
            };
        }
        const boxNodeBtn = document.getElementById('kmp-toolbar-box-node');
        const boxEdgeBtn = document.getElementById('kmp-toolbar-box-edge');
        if (boxNodeBtn) {
            boxNodeBtn.classList.toggle('active', activeRoute.graphBoxSelectMode === 'node');
            boxNodeBtn.onclick = () => setGraphBoxSelectMode(activeRoute, 'node');
        }
        if (boxEdgeBtn) {
            boxEdgeBtn.classList.toggle('active', activeRoute.graphBoxSelectMode === 'edge');
            boxEdgeBtn.onclick = () => setGraphBoxSelectMode(activeRoute, 'edge');
        }
        if (previewInput) {
            previewInput.checked = !!activeRoute.graphPreviewMode;
            previewInput.onchange = () => {
                setExclusiveGraphEditMode(activeRoute, 'preview', !!previewInput.checked);
            };
        }
        if (previewWrap) previewWrap.classList.toggle('active', !!activeRoute.graphPreviewMode);
        if (reverseBtn) {
            reverseBtn.style.display = normalSelectionActionsEnabled && activeRoute.graphSelectionType === 'edge' ? 'inline-flex' : 'none';
            reverseBtn.onclick = () => {
                if (activeRoute.specialMarkerGroupMode) return;
                reverseSelectedGraphEdges(activeRoute);
                refreshGraphEditRoute(activeRoute);
            };
        }
        if (deleteBtn) {
            deleteBtn.style.display = normalSelectionActionsEnabled ? 'inline-flex' : 'none';
            deleteBtn.onclick = () => {
                if (activeRoute.specialMarkerGroupMode) return;
                if (activeRoute.graphSelectionType === 'edge') deleteSelectedGraphEdges(activeRoute);
                else if (activeRoute.graphSelectionType === 'node') deleteSelectedGraphNodes(activeRoute);
                refreshGraphEditRoute(activeRoute);
            };
        }
        const clearBtn = document.getElementById('kmp-toolbar-clear');
        if (clearBtn) {
            clearBtn.style.display = normalSelectionActionsEnabled ? 'inline-flex' : 'none';
            clearBtn.onclick = () => {
                if (activeRoute.specialMarkerGroupMode) return;
                clearGraphSelection(activeRoute);
                refreshGraphEditRoute(activeRoute);
            };
        }
        if (saveEditBtn) saveEditBtn.onclick = () => STATE.routeManager.saveEdit(activeRoute.id);
        if (cancelEditBtn) cancelEditBtn.onclick = () => STATE.routeManager.cancelEdit(activeRoute.id);
    }

    function updateGraphEditHelpPanel(route) {
        let panel = document.getElementById('kmp-graph-edit-help');
        if (!panel) {
            panel = document.createElement('div');
            panel.id = 'kmp-graph-edit-help';
            document.body.appendChild(panel);
        }
        const activeRoute = route || getActiveEditingRoute();
        if (!activeRoute || !activeRoute.isEditing) {
            panel.style.display = 'none';
            return;
        }
        if (activeRoute.specialMarkerGroupMode) {
            panel.style.display = 'none';
            return;
        }
        panel.style.display = 'block';
        if (activeRoute.markerAssociationMode) {
            const markerCount = getRouteAssociatedMarkers(activeRoute).length;
            panel.innerText = `关联标记点模式\n点击官方地图标记点：添加或移除关联\n当前已关联 ${markerCount} 个标记点`;
        } else if (activeRoute.graphPreviewMode) {
            panel.innerText = '预览模式\n编辑节点、选中状态和编辑交互已隐藏';
        } else if (activeRoute.pendingConnectFromNodeId) {
            panel.innerText = '连接模式\n左键点击目标节点：完成连接\nEsc / 点击空白处：取消连接';
        } else if (activeRoute.continuousDrawMode) {
            panel.innerText = '连续绘制模式\n右键地图：连续添加并连接路线点\n再次点击“连续绘制”可切回弹窗插入';
        } else {
            panel.innerText = '左键：选中节点/线段\nShift + 左键：追加或取消选择\n右键：打开上下文菜单\nEsc：取消选中';
        }
    }

    function getLatLngDistance(a, b) {
        const map = STATE.mapInstance;
        if (!map || !a || !b) return Infinity;
        const ap = map.latLngToLayerPoint(a);
        const bp = map.latLngToLayerPoint(b);
        const dx = ap.x - bp.x;
        const dy = ap.y - bp.y;
        return Math.sqrt(dx * dx + dy * dy);
    }

    function getEdgeLatLngs(graph, edge) {
        const fromNode = getGraphNodeById(graph, edge.from);
        const toNode = getGraphNodeById(graph, edge.to);
        if (!fromNode || !toNode) return null;
        return [gameToLatLng(fromNode.x, fromNode.y), gameToLatLng(toNode.x, toNode.y)];
    }

    function findNearestAdjacentEdge(route, currentEdgeId, latlng) {
        const graph = route.editingGraph;
        const current = getGraphEdgeById(graph, currentEdgeId);
        if (!current) return null;
        const currentNodeIds = new Set([current.from, current.to]);
        let best = null;
        let bestDistance = Infinity;
        graph.edges.forEach(edge => {
            if (edge.id === currentEdgeId) return;
            if (!currentNodeIds.has(edge.from) && !currentNodeIds.has(edge.to)) return;
            const latLngs = getEdgeLatLngs(graph, edge);
            if (!latLngs) return;
            const distance = Math.min(getLatLngDistance(latlng, latLngs[0]), getLatLngDistance(latlng, latLngs[1]));
            if (distance < bestDistance) {
                bestDistance = distance;
                best = edge;
            }
        });
        return best;
    }

    function findNearestAdjacentNode(route, currentNodeId, latlng) {
        const graph = route.editingGraph;
        const candidates = new Set();
        graph.edges.forEach(edge => {
            if (edge.from === currentNodeId) candidates.add(edge.to);
            if (edge.to === currentNodeId) candidates.add(edge.from);
        });
        let best = null;
        let bestDistance = Infinity;
        candidates.forEach(nodeId => {
            const node = getGraphNodeById(graph, nodeId);
            if (!node) return;
            const distance = getLatLngDistance(latlng, gameToLatLng(node.x, node.y));
            if (distance < bestDistance) {
                bestDistance = distance;
                best = node;
            }
        });
        return best;
    }

    function startGraphBrushSelection(route, type, id) {
        ensureGraphSelectionState(route);
        if (route.graphSelectionType && route.graphSelectionType !== type) return false;
        route._graphBrushSelectionStarted = true;
        route._graphBrushSelectionMoved = false;
        route._graphSuppressSelectionClick = true;
        route.graphBrushSelection = { type, path: [id], headId: id };
        toggleGraphSelection(route, type, id);
        return true;
    }

    function updateGraphBrushSelection(route, latlng) {
        const brush = route && route.graphBrushSelection;
        if (!brush) return false;
        if (brush.path.length > 1) {
            const prevId = brush.path[brush.path.length - 2];
            if (brush.type === 'edge') {
                const prev = getGraphEdgeById(route.editingGraph, prevId);
                const prevLatLngs = prev ? getEdgeLatLngs(route.editingGraph, prev) : null;
                if (prevLatLngs && Math.min(getLatLngDistance(latlng, prevLatLngs[0]), getLatLngDistance(latlng, prevLatLngs[1])) < 28) {
                    const removed = brush.path.pop();
                    route.graphSelectedIds.delete(removed);
                    brush.headId = prevId;
                    route._graphBrushSelectionMoved = true;
                    updateGraphEditToolbar(route);
                    return true;
                }
            } else {
                const prevNode = getGraphNodeById(route.editingGraph, prevId);
                if (prevNode && getLatLngDistance(latlng, gameToLatLng(prevNode.x, prevNode.y)) < 28) {
                    const removed = brush.path.pop();
                    route.graphSelectedIds.delete(removed);
                    brush.headId = prevId;
                    route._graphBrushSelectionMoved = true;
                    updateGraphEditToolbar(route);
                    return true;
                }
            }
        }
        const next = brush.type === 'edge'
            ? findNearestAdjacentEdge(route, brush.headId, latlng)
            : findNearestAdjacentNode(route, brush.headId, latlng);
        if (!next || route.graphSelectedIds.has(next.id)) return false;
        brush.path.push(next.id);
        brush.headId = next.id;
        route.graphSelectedIds.add(next.id);
        route._graphBrushSelectionMoved = true;
        updateGraphEditToolbar(route);
        return true;
    }

    function finishGraphBrushSelection(route) {
        if (!route) return;
        route.graphBrushSelection = null;
    }

    function startGraphBoxSelection(route, type, latlng, additive) {
        route.isBoxSelecting = true;
        route.graphBoxSelection = { type, startLatLng: latlng, additive: !!additive, rect: null };
        const map = STATE.mapInstance;
        if (map && map.dragging && map.dragging.enabled()) {
            route._graphHadDragging = true;
            map.dragging.disable();
        }
        STATE.routeManager.updateEditLayer(route);
        route.graphBoxSelection.rect = L.rectangle(L.latLngBounds(latlng, latlng), {
            className: 'kmp-select-box',
            pane: 'overlayPane'
        }).addTo(map);
    }

    function selectGraphElementsInBounds(route, type, bounds, additive) {
        if (!additive) clearGraphSelection(route);
        if (route.graphSelectionType && route.graphSelectionType !== type) clearGraphSelection(route);
        route.graphSelectionType = type;
        const selected = ensureGraphSelectionState(route);
        const graph = route.editingGraph;
        if (type === 'node') {
            graph.nodes.forEach(node => {
                if (bounds.contains(gameToLatLng(node.x, node.y))) selected.add(node.id);
            });
        } else {
            graph.edges.forEach(edge => {
                const latLngs = getEdgeLatLngs(graph, edge);
                if (!latLngs) return;
                const hits = latLngs.filter(point => bounds.contains(point)).length;
                if (hits / latLngs.length >= GRAPH_BOX_SELECT_THRESHOLD_RATIO) selected.add(edge.id);
            });
        }
        if (!selected.size) route.graphSelectionType = null;
        updateGraphEditToolbar(route);
    }

    function finishGraphBoxSelection(route) {
        const box = route && route.graphBoxSelection;
        if (!box) return;
        if (box.rect) {
            const bounds = box.rect.getBounds();
            selectGraphElementsInBounds(route, box.type, bounds, box.additive);
            try { STATE.mapInstance.removeLayer(box.rect); } catch (e) {}
        }
        route.graphBoxSelection = null;
        route.isBoxSelecting = false;
        route._graphIgnoreNextBlankClick = true;
        syncGraphBoxSelectionMapDrag(route);
        refreshGraphEditRoute(route);
    }

    function openEdgeEditPopup(route, edge, latlng) {
        L.popup({ offset: [0, -10], closeButton: false })
            .setLatLng(latlng)
            .setContent(`
                <div class="kmp-edit-popup">
                    <button class="kmp-edit-popup-btn" id="btn-add-node">插入节点</button>
                    <button class="kmp-edit-popup-btn" id="btn-reverse-edge">反转方向</button>
                    <button class="kmp-edit-popup-btn" id="btn-del-prev-node">删除上一个节点</button>
                    <button class="kmp-edit-popup-btn" id="btn-del-next-node">删除下一个节点</button>
                    <button class="kmp-edit-popup-btn danger" id="btn-del-edge">删除连线</button>
                </div>
            `)
            .openOn(STATE.mapInstance);
        graphPopupButton('btn-add-node', () => {
            STATE.mapInstance.closePopup();
            insertNodeOnEdge(route, edge, latlng);
            refreshGraphEditRoute(route);
        });
        graphPopupButton('btn-reverse-edge', () => {
            STATE.mapInstance.closePopup();
            reverseGraphEdge(route, edge.id);
            refreshGraphEditRoute(route);
        });
        graphPopupButton('btn-del-prev-node', () => {
            STATE.mapInstance.closePopup();
            deleteAdjacentGraphNode(route, edge.id, 'prev');
            refreshGraphEditRoute(route);
        });
        graphPopupButton('btn-del-next-node', () => {
            STATE.mapInstance.closePopup();
            deleteAdjacentGraphNode(route, edge.id, 'next');
            refreshGraphEditRoute(route);
        });
        graphPopupButton('btn-del-edge', () => {
            STATE.mapInstance.closePopup();
            deleteGraphEdge(route, edge.id);
            refreshGraphEditRoute(route);
        });
    }

    function openGraphBackgroundEditPopup(route, latlng) {
        L.popup({ offset: [0, -10], closeButton: false })
            .setLatLng(latlng)
            .setContent(`
                <div class="kmp-edit-popup">
                    <button class="kmp-edit-popup-btn" id="btn-add-standalone-node">插入节点</button>
                </div>
            `)
            .openOn(STATE.mapInstance);
        graphPopupButton('btn-add-standalone-node', () => {
            STATE.mapInstance.closePopup();
            addGraphNodeAtLatLng(route, latlng);
            refreshGraphEditRoute(route);
        });
    }

    function openGraphMultiSelectPopup(route, latlng) {
        ensureGraphSelectionState(route);
        const type = route.graphSelectionType;
        const count = route.graphSelectedIds.size;
        if (!type || !count) return;
        const isEdge = type === 'edge';
        L.popup({ offset: [0, -10], closeButton: false })
            .setLatLng(latlng)
            .setContent(`
                <div class="kmp-edit-popup">
                    <div style="margin-bottom:6px">已选 ${count} ${isEdge ? '条线段' : '个节点'}</div>
                    ${isEdge ? '<button class="kmp-edit-popup-btn" id="btn-multi-reverse">反转方向</button>' : ''}
                    <button class="kmp-edit-popup-btn danger" id="btn-multi-delete">${isEdge ? '删除所选连线' : '删除所选节点'}</button>
                </div>
            `)
            .openOn(STATE.mapInstance);
        graphPopupButton('btn-multi-reverse', () => {
            STATE.mapInstance.closePopup();
            reverseSelectedGraphEdges(route);
            refreshGraphEditRoute(route);
        });
        graphPopupButton('btn-multi-delete', () => {
            STATE.mapInstance.closePopup();
            if (isEdge) deleteSelectedGraphEdges(route);
            else deleteSelectedGraphNodes(route);
            refreshGraphEditRoute(route);
        });
    }

    function openGraphContextMenu(route, type, id, latlng) {
        ensureGraphSelectionState(route);
        if (route.graphSelectedIds.has(id) && route.graphSelectionType === type && route.graphSelectedIds.size > 1) {
            openGraphMultiSelectPopup(route, latlng);
            return;
        }
        selectSingleGraphElement(route, type, id);
        if (type === 'edge') {
            const edge = getGraphEdgeById(route.editingGraph, id);
            if (edge) openEdgeEditPopup(route, edge, latlng);
        } else {
            const node = getGraphNodeById(route.editingGraph, id);
            if (node) openGraphNodeEditPopup(route, node, latlng, 14 * SETTINGS.arrowSize);
        }
        STATE.routeManager.updateEditLayer(route);
    }

    function openGraphBackgroundContextMenu(route, latlng) {
        if (route.specialMarkerGroupMode) return;
        clearGraphEditSelection(route);
        if (route.continuousDrawMode) {
            addGraphNodeAtLatLng(route, latlng);
            refreshGraphEditRoute(route);
            return;
        }
        openGraphBackgroundEditPopup(route, latlng);
    }

    function bindHitPolylineEvents(hitPolyline, route, edge) {
        hitPolyline.on('mousedown', (e) => {
            if (route.specialMarkerGroupMode) return;
            if (!e.originalEvent || e.originalEvent.button !== 0 || !(e.originalEvent.shiftKey || route.continuousSelectionMode)) return;
            L.DomEvent.stopPropagation(e);
            startGraphBrushSelection(route, 'edge', edge.id);
        });
        hitPolyline.on('click', (e) => {
            L.DomEvent.stopPropagation(e);
            if (route.specialMarkerGroupMode) return;
            if (route._graphSuppressSelectionClick) {
                route._graphSuppressSelectionClick = false;
                STATE.mapInstance.closePopup();
                STATE.routeManager.updateEditLayer(route);
                return;
            }
            if (e.originalEvent && (e.originalEvent.shiftKey || route.continuousSelectionMode)) {
                toggleGraphSelection(route, 'edge', edge.id);
            } else {
                selectSingleGraphElement(route, 'edge', edge.id);
            }
            STATE.mapInstance.closePopup();
            STATE.routeManager.updateEditLayer(route);
        });
        hitPolyline.on('contextmenu', (e) => {
            L.DomEvent.stopPropagation(e);
            if (route.specialMarkerGroupMode) return;
            openGraphContextMenu(route, 'edge', edge.id, e.latlng);
        });
    }

    function createEditNodeIcon(pIdx, node, nodeSize, state = {}) {
        const classes = ['kmp-edit-handle-icon'];
        if (state.selected) classes.push('kmp-selected-node');
        if (state.connectSource) classes.push('kmp-connect-source');
        if (state.connectTarget) classes.push('kmp-connect-target');
        const coordinateHtml = state.specialMarkerGroupMode
            ? `<div class="kmp-edit-node-coordinate">${normalizeRouteCoordinate(node.x)}, ${normalizeRouteCoordinate(node.y)}</div>`
            : '';
        return L.divIcon({
            className: classes.join(' '),
            html: `<div class="kmp-edit-handle-visual" style="${pIdx === 0 ? 'background:#4caf50' : ''}"></div>${coordinateHtml}`,
            iconSize: [nodeSize, nodeSize],
            iconAnchor: [nodeSize / 2, nodeSize / 2]
        });
    }

    function openGraphNodeEditPopup(route, node, latlng, nodeSize) {
        L.popup({ offset: [0, -nodeSize / 2], closeButton: false })
            .setLatLng(latlng)
            .setContent(`
                <div class="kmp-edit-popup kmp-node-edit-popup">
                    <div class="kmp-node-edit-actions">
                        <div style="margin-bottom:8px">Z: <input type="number" id="node-z-input" class="kmp-edit-input" value="${node.z || 0}"></div>
                        <button class="kmp-edit-popup-btn" id="btn-save-node">保存Z</button>
                        <button class="kmp-edit-popup-btn" id="btn-connect-node">开始连接</button>
                        <button class="kmp-edit-popup-btn danger" id="btn-del-node">删除点</button>
                    </div>
                </div>
            `)
            .openOn(STATE.mapInstance);

        setTimeout(() => {
            const btnSave = document.getElementById('btn-save-node');
            const btnConnect = document.getElementById('btn-connect-node');
            const btnDel = document.getElementById('btn-del-node');
            const zInput = document.getElementById('node-z-input');
            if (btnSave && zInput) {
                btnSave.onclick = () => {
                    node.z = normalizeRouteCoordinate(zInput.value);
                    STATE.mapInstance.closePopup();
                    refreshGraphEditRoute(route);
                };
            }

            if (btnConnect) {
                btnConnect.onclick = () => {
                    route.pendingConnectFromNodeId = node.id;
                    STATE.mapInstance.closePopup();
                    refreshGraphEditRoute(route);
                };
            }

            if (btnDel) {
                btnDel.onclick = () => {
                    STATE.mapInstance.closePopup();
                    deleteGraphNode(route, node.id);
                    refreshGraphEditRoute(route);
                };
            }
        }, 50);
    }

    function bindEditMarkerEvents(marker, route, node, nodeSize) {
        marker.on('mousedown', (e) => {
            if (route.specialMarkerGroupMode) return;
            if (!e.originalEvent || e.originalEvent.button !== 0 || !(e.originalEvent.shiftKey || route.continuousSelectionMode)) return;
            L.DomEvent.stopPropagation(e);
            startGraphBrushSelection(route, 'node', node.id);
        });
        marker.on('drag', (e) => {
            const newPos = e.target.getLatLng();
            const newGamePos = latLngToGame(newPos.lat, newPos.lng);
            node.x = normalizeRouteCoordinate(newGamePos.x);
            node.y = normalizeRouteCoordinate(newGamePos.y);
        });

        marker.on('dragend', () => STATE.routeManager.updateEditLayer(route));

        marker.on('click', (e) => {
            L.DomEvent.stopPropagation(e);
            if (route.graphPreviewMode) return;
            if (route.specialMarkerGroupMode) {
                if (route.specialMarkerAddingGroupId) {
                    addNodeToSpecialMarkerGroup(route, route.specialMarkerAddingGroupId, node.id);
                    refreshGraphEditRoute(route);
                }
                return;
            }
            if (route.pendingConnectFromNodeId) {
                connectGraphNodes(route, route.pendingConnectFromNodeId, node.id);
                route.pendingConnectFromNodeId = null;
                removeEditConnectionPreview(route);
                STATE.mapInstance.closePopup();
                refreshGraphEditRoute(route);
                return;
            }
            if (route._graphSuppressSelectionClick) {
                route._graphSuppressSelectionClick = false;
                STATE.mapInstance.closePopup();
                STATE.routeManager.updateEditLayer(route);
                return;
            }
            if (e.originalEvent && (e.originalEvent.shiftKey || route.continuousSelectionMode)) {
                toggleGraphSelection(route, 'node', node.id);
            } else {
                selectSingleGraphElement(route, 'node', node.id);
            }
            STATE.mapInstance.closePopup();
            STATE.routeManager.updateEditLayer(route);
        });
        marker.on('contextmenu', (e) => {
            L.DomEvent.stopPropagation(e);
            if (route.graphPreviewMode || route.specialMarkerGroupMode) return;
            openGraphContextMenu(route, 'node', node.id, e.latlng);
        });
    }

    function handleGraphEditKeydown(e) {
        const route = getActiveEditingRoute();
        if (!route) return;
        if (e.key === 'Tab') {
            e.preventDefault();
            e.stopPropagation();
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            if (closeSpecialMarkerStyleModal(route, false)) return;
            if (route.specialMarkerAddingGroupId) {
                route.specialMarkerAddingGroupId = null;
                refreshGraphEditRoute(route);
                return;
            }
            clearGraphEditSelection(route);
        }
    }

    function handleGraphEditContextMenu(e) {
        const route = getActiveEditingRoute();
        if (!route) return;
        const mapEl = STATE.mapInstance && STATE.mapInstance.getContainer ? STATE.mapInstance.getContainer() : null;
        if (mapEl && mapEl.contains(e.target)) {
            e.preventDefault();
            if (route.specialMarkerGroupMode) return;
            if (isGraphEditBackgroundEvent(e)) clearGraphEditSelection(route);
        }
    }

    function installGraphEditInputInterceptors() {
        if (STATE.graphEditInputInterceptorsInstalled) return;
        window.addEventListener('keydown', handleGraphEditKeydown, true);
        window.addEventListener('contextmenu', handleGraphEditContextMenu, true);
        STATE.graphEditInputInterceptorsInstalled = true;
    }

    function disableGraphEditMapDefaults(route) {
        const map = STATE.mapInstance;
        if (!map) return;
        installGraphEditInputInterceptors();
        if (map.boxZoom && map.boxZoom.enabled()) {
            route._graphHadBoxZoom = true;
            map.boxZoom.disable();
        }
    }

    function enableGraphEditMapDefaults(route) {
        const map = STATE.mapInstance;
        if (!map) return;
        if (route && route._graphHadBoxZoom && map.boxZoom) map.boxZoom.enable();
        if (route) route._graphHadBoxZoom = false;
    }

    function clearGraphEditSelection(route) {
        if (!route) return;
        route.pendingConnectFromNodeId = null;
        route.hoverConnectTargetNodeId = null;
        removeEditConnectionPreview(route);
        route._graphSuppressSelectionClick = false;
        route._graphIgnoreNextBlankClick = false;
        clearGraphSelection(route);
        refreshGraphEditRoute(route);
    }

    function installGraphEditMapSelectionEvents(route) {
        const map = STATE.mapInstance;
        if (!map || route._graphMapSelectionInstalled) return;
        route._graphOnMapClick = (e) => {
            if (!isGraphEditBackgroundEvent(e)) return;
            if (route.specialMarkerGroupMode) return;
            if (route._graphIgnoreNextBlankClick) {
                route._graphIgnoreNextBlankClick = false;
                return;
            }
            clearGraphEditSelection(route);
        };
        route._graphOnMapContextMenu = (e) => {
            const ev = e.originalEvent || {};
            if (route.specialMarkerGroupMode) {
                L.DomEvent.preventDefault(e);
                L.DomEvent.stopPropagation(e);
                return;
            }
            if (route._graphSuppressNextContextMenu || ev.ctrlKey) {
                route._graphSuppressNextContextMenu = false;
                L.DomEvent.preventDefault(e);
                L.DomEvent.stopPropagation(e);
                return;
            }
            if (!isGraphEditBackgroundEvent(e)) return;
            L.DomEvent.preventDefault(e);
            openGraphBackgroundContextMenu(route, e.latlng);
        };
        route._graphOnMapMouseDown = (e) => {
            if (!isGraphEditBackgroundEvent(e)) return;
            if (route.specialMarkerGroupMode) return;
            if (route.pendingConnectFromNodeId) {
                route.pendingConnectFromNodeId = null;
                route.hoverConnectTargetNodeId = null;
                removeEditConnectionPreview(route);
                refreshGraphEditRoute(route);
                return;
            }
            const ev = e.originalEvent || {};
            if (route.graphBoxSelectMode && ev.button === 0) {
                startGraphBoxSelection(route, route.graphBoxSelectMode, e.latlng, !!ev.shiftKey);
                L.DomEvent.stopPropagation(e);
                return;
            }
            if (!ev.ctrlKey) return;
            const type = ev.button === 2 ? 'edge' : 'node';
            if (ev.button === 2) route._graphSuppressNextContextMenu = true;
            startGraphBoxSelection(route, type, e.latlng, !!ev.shiftKey);
            L.DomEvent.stopPropagation(e);
        };
        route._graphOnMapMouseMove = (e) => {
            if (route.pendingConnectFromNodeId) updateEditConnectionPreview(route, e.latlng);
            if (route.graphBrushSelection && updateGraphBrushSelection(route, e.latlng)) {
                STATE.routeManager.updateEditLayer(route);
            }
            if (route.graphBoxSelection && route.graphBoxSelection.rect) {
                route.graphBoxSelection.rect.setBounds(L.latLngBounds(route.graphBoxSelection.startLatLng, e.latlng));
            }
        };
        route._graphOnMapMouseUp = () => {
            finishGraphBrushSelection(route);
            if (route.graphBoxSelection) finishGraphBoxSelection(route);
            if (route._graphSuppressNextContextMenu) {
                setTimeout(() => { route._graphSuppressNextContextMenu = false; }, 250);
            }
        };
        map.on('click', route._graphOnMapClick);
        map.on('contextmenu', route._graphOnMapContextMenu);
        map.on('mousedown', route._graphOnMapMouseDown);
        map.on('mousemove', route._graphOnMapMouseMove);
        map.on('mouseup', route._graphOnMapMouseUp);
        route._graphMapSelectionInstalled = true;
    }

    function uninstallGraphEditMapSelectionEvents(route) {
        const map = STATE.mapInstance;
        if (!map || !route || !route._graphMapSelectionInstalled) return;
        if (route._graphOnMapClick) map.off('click', route._graphOnMapClick);
        if (route._graphOnMapContextMenu) map.off('contextmenu', route._graphOnMapContextMenu);
        if (route._graphOnMapMouseDown) map.off('mousedown', route._graphOnMapMouseDown);
        if (route._graphOnMapMouseMove) map.off('mousemove', route._graphOnMapMouseMove);
        if (route._graphOnMapMouseUp) map.off('mouseup', route._graphOnMapMouseUp);
        route._graphOnMapClick = null;
        route._graphOnMapContextMenu = null;
        route._graphOnMapMouseDown = null;
        route._graphOnMapMouseMove = null;
        route._graphOnMapMouseUp = null;
        route._graphSuppressNextContextMenu = false;
        route._graphMapSelectionInstalled = false;
    }

    STATE.routeManager.startEdit = function(id) {
        const route = this.routes.find(r => r.id === id);
        if (!route || route.type !== 'json') return;
        const editingRoute = getActiveEditingRoute();
        if (editingRoute) {
            if (editingRoute.id !== route.id) alert('请先保存或取消当前路线编辑');
            return;
        }
        ensureEditPanes();

        if (!route.visible) {
            this.setRouteVisible(route, true, { exclusive: this.singleVisibleMode });
        }
        route.isEditing = true;
        route.isBoxSelecting = false; // 初始化

        route.layer.clearLayers();
        route.editorGroup = L.layerGroup().addTo(STATE.mapInstance);
        route.editingGraph = deepCloneJson(normalizeRouteGraph(route.rawData, route.name));
        route.pendingConnectFromNodeId = null;
        route.hoverConnectTargetNodeId = null;
        route.connectionPreview = null;
        route.graphSelectionType = null;
        route.graphSelectedIds = new Set();
        route.markerAssociationMode = false;
        route.continuousDrawMode = !!route.isNewRoute;
        route.continuousDrawLastNodeId = null;
        route.continuousSelectionMode = false;
        route.graphPreviewMode = false;
        route.graphBoxSelectMode = null;
        route.specialMarkerGroupMode = false;
        route.specialMarkerAddingGroupId = null;
        route.specialMarkerSelectedGroupId = null;
        route._graphSuppressSelectionClick = false;
        route._graphIgnoreNextBlankClick = false;
        route._graphSuppressNextContextMenu = false;
        route._graphBrushSelectionStarted = false;
        route._graphBrushSelectionMoved = false;
        route._editSnapshotStr = JSON.stringify(route.editingGraph);
        disableGraphEditMapDefaults(route);
        installGraphEditMapSelectionEvents(route);
        syncGraphBoxSelectionMapDrag(route);

        this.updateEditLayer(route);
        updateGraphEditToolbar(route);
        updateGraphEditHelpPanel(route);
        updateSpecialMarkerGroupSidebar(route);
        renderRouteListUI();
    };

    STATE.routeManager.updateEditLayer = function(route) {
        const group = route.editorGroup;
        if (!group) return;
        group.clearLayers();

        const svgRenderer = L.svg({ pane: 'kmp-edit-line-pane' });
        const baseSize = 12;
        const nodeSize = baseSize * SETTINGS.arrowSize;

        if (!route.graphPreviewMode) {
            group.addLayer(renderEditVisualLayer(route));
        } else {
            group.addLayer(renderEditVisualLayer(route));
            updateGraphEditToolbar(route);
            updateGraphEditHelpPanel(route);
            return;
        }

        const graph = route.editingGraph || normalizeRouteGraph(route.rawData, route.name);
        const nodeById = new Map(graph.nodes.map(node => [node.id, node]));

        graph.edges.forEach(edge => {
            const fromNode = nodeById.get(edge.from);
            const toNode = nodeById.get(edge.to);
            if (!fromNode || !toNode) return;
            const latLngs = [
                gameToLatLng(fromNode.x, fromNode.y),
                gameToLatLng(toNode.x, toNode.y)
            ];
            const selected = isGraphElementSelected(route, 'edge', edge.id);
            drawEditDirectionArrow(group, latLngs[0], latLngs[1], { selected });
            const hitPolyline = createEditHitPolyline(group, latLngs, route, svgRenderer, selected);
            if (!route.isBoxSelecting && !route.specialMarkerGroupMode) bindHitPolylineEvents(hitPolyline, route, edge);
        });

        graph.nodes.forEach((node, nodeIndex) => {
            const ll = gameToLatLng(node.x, node.y);
            const icon = createEditNodeIcon(nodeIndex, node, nodeSize, {
                selected: isGraphElementSelected(route, 'node', node.id),
                connectSource: route.pendingConnectFromNodeId === node.id,
                connectTarget: route.hoverConnectTargetNodeId === node.id,
                specialMarkerGroupMode: route.specialMarkerGroupMode
            });
            const marker = L.marker(ll, {
                icon: icon,
                draggable: !route.isBoxSelecting && !route.specialMarkerGroupMode,
                pane: 'kmp-edit-marker-pane',
                interactive: !route.isBoxSelecting
            }).addTo(group);
            if (!route.isBoxSelecting) bindEditMarkerEvents(marker, route, node, nodeSize);
        });

        if (route.pendingConnectFromNodeId) {
            const source = getGraphNodeById(graph, route.pendingConnectFromNodeId);
            const target = route.hoverConnectTargetNodeId ? getGraphNodeById(graph, route.hoverConnectTargetNodeId) : null;
            if (source && target) {
                route.connectionPreview = L.polyline([gameToLatLng(source.x, source.y), gameToLatLng(target.x, target.y)], {
                    className: 'kmp-connect-preview',
                    pane: 'kmp-edit-line-pane',
                    interactive: false
                }).addTo(group);
            }
        }
        updateGraphEditToolbar(route);
        updateGraphEditHelpPanel(route);
    };

    STATE.routeManager.cancelEdit = function(id) {
        const route = this.routes.find(r => r.id === id);
        if (!route || !route.isEditing) return;
        const discardNewRoute = !!route.isNewRoute;

        closeSpecialMarkerStyleModal(route, false);
        this.disableBoxSelect(route);
        try { STATE.mapInstance.closePopup(); } catch (e) {}
        uninstallGraphEditMapSelectionEvents(route);
        enableGraphEditMapDefaults(route);
        clearGraphSelection(route);
        route._graphSuppressSelectionClick = false;
        route._graphIgnoreNextBlankClick = false;
        route._graphBrushSelectionStarted = false;
        route._graphBrushSelectionMoved = false;
        route.graphBoxSelectMode = null;
        syncGraphBoxSelectionMapDrag(route);

        route.isEditing = false;
        if (route.editorGroup) STATE.mapInstance.removeLayer(route.editorGroup);
        route.editorGroup = null;
        route.editingGraph = null;
        route.pendingConnectFromNodeId = null;
        route.hoverConnectTargetNodeId = null;
        route.connectionPreview = null;
        route.markerAssociationMode = false;
        route.continuousDrawMode = false;
        route.continuousDrawLastNodeId = null;
        route.specialMarkerGroupMode = false;
        route.specialMarkerAddingGroupId = null;
        route.specialMarkerSelectedGroupId = null;
        route._editSnapshotStr = null;
        updateGraphEditToolbar(route);
        updateGraphEditHelpPanel(route);
        updateSpecialMarkerGroupSidebar(route);

        if (discardNewRoute) {
            this.remove(route.id);
            return;
        }

        route.layer.clearLayers();
        drawJsonOnLayer(route.layer, route.rawData);
        renderRouteListUI();
    };

    STATE.routeManager.saveEdit = function(id) {
        const route = this.routes.find(r => r.id === id);
        if (!route) return;

        closeSpecialMarkerStyleModal(route, false);
        // 确保先关闭框选模式
        this.disableBoxSelect(route);
        try { STATE.mapInstance.closePopup(); } catch (e) {}
        uninstallGraphEditMapSelectionEvents(route);
        enableGraphEditMapDefaults(route);
        route._graphSuppressSelectionClick = false;
        route._graphIgnoreNextBlankClick = false;
        route._graphBrushSelectionStarted = false;
        route._graphBrushSelectionMoved = false;
        route.graphBoxSelectMode = null;
        syncGraphBoxSelectionMapDrag(route);

        const snapshotStr = route._editSnapshotStr || '';
        const currentStr = JSON.stringify(route.editingGraph || {});
        const hasChanges = currentStr !== snapshotStr;

        if (hasChanges) {
            route.rawData = serializeRouteGraph(route);
        }

        route.isNewRoute = false;
        route.markerAssociationMode = false;
        route.continuousDrawMode = false;
        route.continuousDrawLastNodeId = null;
        route.specialMarkerGroupMode = false;
        route.specialMarkerAddingGroupId = null;
        route.specialMarkerSelectedGroupId = null;

        route.isEditing = false;
        STATE.mapInstance.removeLayer(route.editorGroup);
        route.editorGroup = null;
        route.editingGraph = null;
        route.pendingConnectFromNodeId = null;
        route.hoverConnectTargetNodeId = null;
        route.connectionPreview = null;
        route._editSnapshotStr = null;
        clearGraphSelection(route);
        updateGraphEditToolbar(route);
        updateGraphEditHelpPanel(route);
        updateSpecialMarkerGroupSidebar(route);

        route.layer.clearLayers();
        drawJsonOnLayer(route.layer, route.rawData);
        renderRouteListUI();
    };

    // Route list UI (v2): adds selection + manual export + cancel/save editing UX.
    window.renderRouteListUI = function() {
        const list = document.getElementById('sm-route-list');
        if (!list) return;
 
        const updateBulkButtons = () => {
            const exportBtn = document.getElementById('sm-export-selected');
            const toggleBtn = document.getElementById('sm-toggle-visible');
            const clearBtn = document.getElementById('sm-clear-route');
            const mergeBtn = document.getElementById('sm-merge-selected');
            const singleToggle = document.getElementById('sm-single-route-toggle');
            const prevBtn = document.getElementById('sm-prev-route');
            const nextBtn = document.getElementById('sm-next-route');
            const createBtn = document.getElementById('sm-create-route-btn');
            if (!exportBtn && !toggleBtn && !clearBtn && !mergeBtn && !singleToggle && !prevBtn && !nextBtn && !createBtn) return;

            const total = STATE.routeManager.routes.length;
            const selected = STATE.routeManager.selectedIds || new Set();
            const singleMode = !!STATE.routeManager.singleVisibleMode;

            const existing = new Set(STATE.routeManager.routes.map(r => r.id));
            for (const id of Array.from(selected)) {
                if (!existing.has(id)) selected.delete(id);
            }

            const n = selected.size;
            const targets = n ? STATE.routeManager.routes.filter(r => selected.has(r.id)) : STATE.routeManager.routes.slice();
            const targetCount = targets.length;
            const mergeCandidates = collectSelectedJsonRoutes(STATE.routeManager);

            if (exportBtn) {
                exportBtn.disabled = total === 0;
                exportBtn.style.opacity = total === 0 ? 0.5 : 1;
                exportBtn.innerText = n ? `批量导出(${targetCount})` : `批量导出`;
            }

            if (toggleBtn) {
                toggleBtn.disabled = singleMode || total === 0 || targetCount === 0;
                toggleBtn.style.opacity = (singleMode || total === 0 || targetCount === 0) ? 0.5 : 1;
                const anyHidden = targets.some(r => !r.visible);
                const act = anyHidden ? '显示' : '隐藏';
                toggleBtn.innerText = n ? `批量${act}(${targetCount})` : `${act}全部`;
                toggleBtn.title = singleMode ? '仅显示单条路线开启时不可用' : '批量显示或隐藏路线';
            }

            if (clearBtn) {
                clearBtn.disabled = total === 0 || targetCount === 0;
                clearBtn.style.opacity = (total === 0 || targetCount === 0) ? 0.5 : 1;
                clearBtn.innerText = n ? `清空路线(${targetCount})` : `清空路线`;
            }

            if (mergeBtn) {
                mergeBtn.disabled = mergeCandidates.length < 2;
                mergeBtn.style.opacity = mergeCandidates.length < 2 ? 0.5 : 1;
                mergeBtn.innerText = mergeCandidates.length
                    ? `${ROUTE_LIST_TEXT.mergeSelected}(${mergeCandidates.length})`
                    : ROUTE_LIST_TEXT.mergeSelected;
            }

            if (singleToggle) {
                syncSingleRouteToggleUI();
            }
            if (prevBtn) {
                prevBtn.disabled = !singleMode || total === 0;
                prevBtn.style.opacity = (!singleMode || total === 0) ? 0.5 : 1;
            }
            if (nextBtn) {
                nextBtn.disabled = !singleMode || total === 0;
                nextBtn.style.opacity = (!singleMode || total === 0) ? 0.5 : 1;
            }
            if (createBtn) {
                const editing = STATE.routeManager.routes.some(route => route && route.isEditing);
                createBtn.disabled = editing;
                createBtn.title = editing ? '请先保存或取消当前路线编辑' : '新建空白路线';
            }
        };

        if (!STATE.routeManager.routes.length) {
            list.innerHTML = '<div style="text-align:center;color:#666;font-size:12px">暂无路径</div>';
            updateBulkButtons();
            scheduleRouteMarkerDisplay('route-list-empty');
            return;
        }

        list.innerHTML = '';

        STATE.routeManager.routes.forEach(r => {
            const div = document.createElement('div');
            div.className = 'sm-route-item';

            let btnGroupHtml = '';
            if (r.isEditing) {
                btnGroupHtml = `
                    <button class="save" style="border-color:#4caf50;color:#4caf50">保存</button>
                    <button class="cancel" style="border-color:#ff9800;color:#ff9800">取消</button>
                `;
            } else {
                const editBtn = r.type === 'json'
                    ? `<button class="edit" style="color:#dcb268;border-color:#dcb268">编辑</button>`
                    : '';
                btnGroupHtml = `
                    ${editBtn}
                    <button class="exp" style="border-color:#4caf50;color:#4caf50">导出</button>
                    <button class="tgl" style="filter:${r.visible?'none':'grayscale(1);opacity:0.5'}">${r.visible?'显示':'隐藏'}</button>
                    <button class="del">删除</button>
                `;
            }

            const singleMode = !!STATE.routeManager.singleVisibleMode;
            const isSelected = STATE.routeManager.selectedIds && STATE.routeManager.selectedIds.has(r.id);
            const selChecked = singleMode ? !!r.visible : !!isSelected;
            const selTitle = singleMode ? '仅显示单条路线模式下切换当前显示路线' : ROUTE_LIST_TEXT.selectionTitle;
            const selHtml = `<label class="sm-route-sel" title="${selTitle}"><input class="sel" type="checkbox" ${selChecked ? 'checked' : ''} ${r.isEditing ? 'disabled' : ''}></label>`;

            div.innerHTML = `
                ${selHtml}
                <span class="sm-route-name" title="${r.name}">${r.type==='json'?'[JSON]':'[SVG]'} ${r.name}</span>
                <span class="sm-route-acts">${btnGroupHtml}</span>
            `;

            const sel = div.querySelector('.sel');
            if (sel) {
                sel.onchange = (e) => {
                    if (STATE.routeManager.singleVisibleMode) {
                        if (e.target.checked) {
                            STATE.routeManager.setRouteVisible(r, true, { exclusive: true });
                        } else {
                            STATE.routeManager.setRouteVisible(r, false, { exclusive: false });
                        }
                        renderRouteListUI();
                        return;
                    }
                    if (!STATE.routeManager.selectedIds) STATE.routeManager.selectedIds = new Set();
                    if (e.target.checked) STATE.routeManager.selectedIds.add(r.id);
                    else STATE.routeManager.selectedIds.delete(r.id);
                    updateBulkButtons();
                };
            }

            if (r.isEditing) {
                div.querySelector('.save').onclick = () => STATE.routeManager.saveEdit(r.id);
                div.querySelector('.cancel').onclick = () => STATE.routeManager.cancelEdit(r.id);
            } else {
                if (div.querySelector('.edit')) div.querySelector('.edit').onclick = () => STATE.routeManager.startEdit(r.id);
                div.querySelector('.exp').onclick = () => STATE.routeManager.exportOne(r.id);
                div.querySelector('.tgl').onclick = () => STATE.routeManager.toggleVisible(r.id);
                div.querySelector('.del').onclick = () => STATE.routeManager.remove(r.id);
            }

            list.appendChild(div);
        });

        updateBulkButtons();
        scheduleRouteMarkerDisplay('route-list-render');
    };

    function parseSvgMetadata(svgText) {
        const match = /<!--\s*game_route_data(?:\s+\[converted="([^"]+)"\])?\s*([\s\S]*?)-->/.exec(svgText);
        if (!match) return null;
        const body = match[2];
        const ext = (pf) => {
            const m = body.match(new RegExp(`${pf}\\s*:\\s*(.*)`, 'i'));
            if (!m) return null;
            const v = (k) => { const r = m[1].match(new RegExp(`${k}="([^"]+)"`)); return r?parseFloat(r[1]):NaN; };
            return { svgX: v('svg_x'), svgY: v('svg_y'), gameX: v('game_x'), gameY: v('game_y') };
        };
        return { p1: ext('start'), p2: ext('end'), converted: match[1] === 'true' };
    }

    function basenameOnly(pathLike) {
        const s = String(pathLike || '');
        const idx = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
        return idx >= 0 ? s.slice(idx + 1) : s;
    }

    function lowerExt(name) {
        const s = String(name || '').toLowerCase();
        const dot = s.lastIndexOf('.');
        return dot >= 0 ? s.slice(dot) : '';
    }

    function formatBytes(bytes) {
        if (!Number.isFinite(bytes)) return String(bytes);
        const units = ['B', 'KB', 'MB', 'GB'];
        let v = bytes;
        let i = 0;
        while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
        return `${v.toFixed(i === 0 ? 0 : 2)} ${units[i]}`;
    }

    function toReason(err) {
        if (!err) return '未知错误';
        if (typeof err === 'string') return err;
        if (err && typeof err.message === 'string') return err.message;
        try { return JSON.stringify(err); } catch { return String(err); }
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[ch]));
    }

    async function readAsText(fileLike) {
        if (fileLike && typeof fileLike.text === 'function') return await fileLike.text();
        return await new Promise((resolve, reject) => {
            const r = new FileReader();
            r.onload = () => resolve(String(r.result || ''));
            r.onerror = () => reject(new Error('读取失败'));
            r.readAsText(fileLike);
        });
    }

    async function readAsArrayBuffer(fileLike) {
        if (fileLike && typeof fileLike.arrayBuffer === 'function') return await fileLike.arrayBuffer();
        return await new Promise((resolve, reject) => {
            const r = new FileReader();
            r.onload = () => resolve(r.result);
            r.onerror = () => reject(new Error('读取失败'));
            r.readAsArrayBuffer(fileLike);
        });
    }

    function withTimeout(promise, ms, message) {
        let t;
        const timeoutPromise = new Promise((_, reject) => {
            t = setTimeout(() => reject(new Error(message || `超时(${ms}ms)`)), ms);
        });
        return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(t));
    }

    function importJsonRouteFromData(data, displayName, options = {}) {
        const graph = normalizeRouteGraph(data, displayName);
        if (!graph.nodes.length) {
            throw new Error('JSON缺少路线点');
        }
        const layer = L.layerGroup();
        drawJsonOnLayer(layer, graph);
        STATE.mainLayerGroup.addLayer(layer);
        STATE.routeManager.add({
            id: Date.now() + Math.random(),
            name: displayName,
            type: 'json',
            layer,
            rawData: graph,
            visible: true
        });
        if (options.focus) {
            const firstNode = graph.nodes[0];
            STATE.mapInstance.panTo(gameToLatLng(firstNode.x, firstNode.y));
        }
    }

    function importSvgRouteFromText(svgText, displayName, options = {}) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(svgText, "image/svg+xml");
        const meta = parseSvgMetadata(svgText);
        if (!meta || !meta.p1 || !meta.p2) throw new Error('SVG缺少元数据');

        let vMinX = 0, vMinY = 0, vW = 0, vH = 0;
        const vb = doc.documentElement.getAttribute('viewBox');
        if (vb) {
            [vMinX, vMinY, vW, vH] = vb.split(/[\s,]+/).map(parseFloat);
        } else {
            vW = parseFloat(doc.documentElement.getAttribute('width'));
            vH = parseFloat(doc.documentElement.getAttribute('height'));
        }
        if (!Number.isFinite(vW) || !Number.isFinite(vH)) throw new Error('SVG缺少尺寸(viewBox/width/height)');

        const { p1, p2 } = meta;
        const dSx = p2.svgX - p1.svgX; const scX = Math.abs(dSx) < 1e-4 ? 1 : (p2.gameX - p1.gameX) / dSx; const offX = p1.gameX - p1.svgX * scX;
        const dSy = p2.svgY - p1.svgY; const scY = Math.abs(dSy) < 1e-4 ? 1 : (p2.gameY - p1.gameY) / dSy; const offY = p1.gameY - p1.svgY * scY;
        const b1 = gameToLatLng(vMinX * scX + offX, vMinY * scY + offY);
        const b2 = gameToLatLng((vMinX + vW) * scX + offX, (vMinY + vH) * scY + offY);
        const bounds = L.latLngBounds(b1, b2);

        const blob = new Blob([svgText], { type: 'image/svg+xml' });
        const url = URL.createObjectURL(blob);
        const layer = L.imageOverlay(url, bounds, { opacity: 0.9, interactive: false });
        STATE.mainLayerGroup.addLayer(layer);
        STATE.routeManager.add({ id: Date.now() + Math.random(), name: displayName, type: 'svg', layer, rawText: svgText, visible: true });

        if (options.focus) STATE.mapInstance.fitBounds(bounds);
    }

    async function importZipRoutes(zipFile) {
        logImport('ZIP selected:', zipFile && zipFile.name, zipFile && zipFile.size, zipFile && zipFile.type);
        setImportStatus(`正在解析ZIP：${zipFile.name} (${formatBytes(zipFile.size)})`);

        if (zipFile.size > IMPORT_LIMITS.zipMaxBytes) {
            setImportStatus(`ZIP超出大小限制：${formatBytes(zipFile.size)} > ${formatBytes(IMPORT_LIMITS.zipMaxBytes)}`, true);
            alert(`ZIP超出大小限制：${formatBytes(zipFile.size)} > ${formatBytes(IMPORT_LIMITS.zipMaxBytes)}`);
            return;
        }
        let JSZipLib;
        try {
            setImportStatus('正在加载ZIP组件(JSZip)...');
            JSZipLib = await ensurePageJSZip();
        } catch (e) {
            setImportStatus(`JSZip加载失败：${toReason(e)}`, true);
            alert(`JSZip加载失败：${toReason(e)}\n\n可能原因：\n- 站点CSP拦截外链 <script> 注入（已尝试绕过/兜底）\n- Tampermonkey 未能下载 @resource(JSZIP) 或网络不可用\n- 脚本管理器未授权/不支持 GM_getResourceText 或 GM_xmlhttpRequest\n\n建议：更新/重新安装脚本以重新拉取资源，或检查脚本管理器的外部资源/跨域请求权限。`);
            return;
        }

        const failures = [];
        const MAX_FAILURE_LIST = 200;
        let extraFailureCount = 0;
        const recordFailure = (name, reason) => {
            if (failures.length < MAX_FAILURE_LIST) failures.push({ name, reason });
            else extraFailureCount += 1;
        };
        let imported = 0;
        let matchedBytes = 0;
        let stopReason = '';
        let focused = false;

        let zip;
        try {
            const ab = await readAsArrayBuffer(zipFile);
            zip = await withTimeout(JSZipLib.loadAsync(ab), 8000, 'ZIP解析超时');
        } catch (e) {
            setImportStatus(`ZIP解析失败：${toReason(e)}`, true);
            alert(`ZIP解析失败：${toReason(e)}`);
            return;
        }

        const fileNamesInOrder = Object.keys(zip.files || {}).sort((a, b) => {
            const an0 = basenameOnly(a);
            const bn0 = basenameOnly(b);
            const an = an0.replace(/\.(json|svg)$/i, '');
            const bn = bn0.replace(/\.(json|svg)$/i, '');
            const byName = an.localeCompare(bn, 'en', { numeric: true, sensitivity: 'base' });
            if (byName) return byName;
            const byFull = an0.localeCompare(bn0, 'en', { numeric: true, sensitivity: 'base' });
            if (byFull) return byFull;
            return String(a).localeCompare(String(b), 'en', { numeric: true, sensitivity: 'base' });
        });
        const totalEntries = fileNamesInOrder.length;
        setImportStatus(`ZIP已打开，正在扫描文件...（共${totalEntries}项）`);
        logImport('ZIP entries:', totalEntries);

        let matchedSeen = 0;
        let matchedKept = 0;
        let scanned = 0;

        for (const entryName of fileNamesInOrder) {
            scanned += 1;
            if (scanned % 300 === 0) {
                setImportStatus(`扫描中... ${scanned}/${totalEntries}（匹配${matchedSeen}，成功${imported}，累计${formatBytes(matchedBytes)}）`);
                await new Promise(r => setTimeout(r, 0));
            }

            const entry = zip.files[entryName];
            if (!entry || entry.dir) continue;
            const ext = lowerExt(entryName);
            if (ext !== '.json' && ext !== '.svg') continue;

            matchedSeen += 1;

            if (stopReason) {
                recordFailure(entryName, stopReason);
                continue;
            }

            if (matchedKept >= IMPORT_LIMITS.unzipMatchedMaxFiles) {
                stopReason = `文件数超限：仅加载前 ${IMPORT_LIMITS.unzipMatchedMaxFiles} 个`;
                recordFailure(entryName, stopReason);
                continue;
            }

            const estimatedSize = entry && entry._data && typeof entry._data.uncompressedSize === 'number'
                ? entry._data.uncompressedSize
                : null;

            if (estimatedSize !== null && matchedBytes + estimatedSize > IMPORT_LIMITS.unzipMatchedMaxBytes) {
                stopReason = `解压后总大小超限：仅加载前 ${formatBytes(IMPORT_LIMITS.unzipMatchedMaxBytes)}`;
                recordFailure(entryName, stopReason);
                continue;
            }

            matchedKept += 1;

            try {
                setImportStatus(`正在导入：${basenameOnly(entryName)}（${matchedKept}/${IMPORT_LIMITS.unzipMatchedMaxFiles}）`);
                const u8 = await withTimeout(entry.async('uint8array'), 5000, '解压超时');
                if (matchedBytes + u8.byteLength > IMPORT_LIMITS.unzipMatchedMaxBytes) {
                    stopReason = `解压后总大小超限：仅加载前 ${formatBytes(IMPORT_LIMITS.unzipMatchedMaxBytes)}`;
                    recordFailure(entryName, stopReason);
                    continue;
                }
                matchedBytes += u8.byteLength;

                let text = new TextDecoder('utf-8').decode(u8);
                if (text && text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
                const displayName = basenameOnly(entryName);
                if (ext === '.json') {
                    const data = JSON.parse(text);
                    importJsonRouteFromData(data, displayName, { focus: !focused });
                } else {
                    importSvgRouteFromText(text, displayName, { focus: !focused });
                }
                focused = true;
                imported += 1;
            } catch (e) {
                recordFailure(entryName, toReason(e));
            }
        }

        setImportStatus(`ZIP导入完成：成功${imported}，失败${failures.length + extraFailureCount}（匹配${matchedSeen}，累计${formatBytes(matchedBytes)}）`, failures.length + extraFailureCount > 0);
        logImport('ZIP done:', { imported, failures: failures.length, extraFailureCount, matchedSeen, matchedBytes });

        if (failures.length || extraFailureCount) {
            const lines = failures.map(f => `${f.name}  ->  ${f.reason}`);
            if (extraFailureCount) lines.push(`... 另有 ${extraFailureCount} 个失败未展示（ZIP条目过多）`);
            alert(`ZIP导入完成：成功 ${imported} 个，失败 ${failures.length + extraFailureCount} 个。\n\n失败列表：\n${lines.join('\n')}`);
        } else if (imported === 0) {
            setImportStatus('ZIP内未找到可导入的 .json / .svg 路线文件', true);
            alert('ZIP内未找到可导入的 .json / .svg 路线文件');
        }
    }

    async function processFiles(files) {
        const failures = [];
        let imported = 0;
        let focused = false;

        const list = Array.from(files || []);
        logImport('processFiles:', list.map(f => ({ name: f && f.name, size: f && f.size, type: f && f.type })));
        if (!list.length) {
            setImportStatus('未接收到文件', true);
            return;
        }
        setImportStatus(`已选择 ${list.length} 个文件，处理中...`);

        for (const f of list) {
            const ext = lowerExt(f.name);
            if (ext === '.zip') {
                await importZipRoutes(f);
                continue;
            }
            if (ext !== '.json' && ext !== '.svg') continue;

            try {
                const content = await readAsText(f);
                const displayName = basenameOnly(f.name);
                if (ext === '.json') {
                    const data = JSON.parse(content);
                    importJsonRouteFromData(data, displayName, { focus: !focused });
                } else {
                    importSvgRouteFromText(content, displayName, { focus: !focused });
                }
                focused = true;
                imported += 1;
            } catch (e) {
                failures.push({ name: f.name, reason: toReason(e) });
            }
        }

        if (failures.length) {
            const lines = failures.map(f => `${f.name}  ->  ${f.reason}`);
            alert(`导入完成：成功 ${imported} 个，失败 ${failures.length} 个。\n\n失败列表：\n${lines.join('\n')}`);
            setImportStatus(`导入完成：成功${imported}，失败${failures.length}`, true);
        } else if (imported > 0) {
            setImportStatus(`导入完成：成功${imported}`);
        }
    }

    function safeJsonParse(text, fallback) {
        try { return JSON.parse(text); } catch (e) { return fallback; }
    }

    function getAkiMapUserInfo() {
        try {
            const raw = localStorage.getItem('AKI_MAP_USER_INFO');
            if (!raw) return null;
            const obj = safeJsonParse(raw, null);
            if (!obj || typeof obj !== 'object') return null;
            const userId = obj.userId ? String(obj.userId) : null;
            const userName = obj.userName ? String(obj.userName) : '';
            return userId ? { userId, userName } : null;
        } catch (e) {
            return null;
        }
    }

    function hasValidAkiToken() {
        const token = localStorage.getItem('AKI_MAP_USER_TOKEN') || '';
        return token && token.length > 20;
    }

    function getAkiMapUserProfile() {
        try {
            const raw = localStorage.getItem('AKI_MAP_USER_PROFILE');
            if (!raw) return null;
            const obj = safeJsonParse(raw, null);
            return (obj && typeof obj === 'object') ? obj : null;
        } catch (e) {
            return null;
        }
    }

    function syncAkiAuthToPython() {
        try {
            if (!window.backend || typeof window.backend.syncAkiAuth !== 'function') return;
            const token = localStorage.getItem('AKI_MAP_USER_TOKEN') || '';
            const userInfo = getAkiMapUserInfo();
            const userProfile = getAkiMapUserProfile();
            if (!token || !userInfo || !userInfo.userId) return;

            const payload = {
                token,
                userInfo,
                userProfile: userProfile || {},
                AKI_MAP_USER_TOKEN: token,
                AKI_MAP_USER_INFO: userInfo,
                AKI_MAP_USER_PROFILE: userProfile || {},
                source: 'userscript_full',
                ts: Date.now(),
            };
            window.backend.syncAkiAuth(JSON.stringify(payload));
        } catch (e) {}
    }

    function gmFetch(url, options = {}) {
        return new Promise((resolve) => {
            GM_xmlhttpRequest({
                method: options.method || 'GET',
                url,
                headers: options.headers || {},
                data: options.body,
                timeout: Number(options.timeout) > 0 ? Number(options.timeout) : 15000,
                onload: (res) => resolve({
                    ok: res.status >= 200 && res.status < 300,
                    status: res.status,
                    text: () => Promise.resolve(String(res.responseText || '')),
                    json: () => Promise.resolve(safeJsonParse(res.responseText || '', []))
                }),
                ontimeout: (res) => resolve({
                    ok: false,
                    status: (res && Number(res.status)) || 0,
                    text: () => Promise.resolve('timeout'),
                    json: () => Promise.resolve([])
                }),
                onerror: (res) => resolve({
                    ok: false,
                    status: (res && Number(res.status)) || 0,
                    text: () => Promise.resolve(String((res && (res.responseText || res.error)) || 'network_error')),
                    json: () => Promise.resolve([])
                })
            });
        });
    }

    function gmFetchArrayBuffer(url, options = {}) {
        return new Promise((resolve) => {
            const xhr = GM_xmlhttpRequest({
                method: options.method || 'GET',
                url,
                headers: options.headers || {},
                data: options.body,
                responseType: 'arraybuffer',
                timeout: Number(options.timeout) > 0 ? Number(options.timeout) : 60000,
                onload: (res) => resolve({
                    ok: res.status >= 200 && res.status < 300,
                    status: res.status,
                    arrayBuffer: () => Promise.resolve(res.response),
                    text: () => Promise.resolve(String(res.responseText || '')),
                }),
                ontimeout: (res) => resolve({
                    ok: false,
                    status: (res && Number(res.status)) || 0,
                    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
                    text: () => Promise.resolve('timeout'),
                }),
                onerror: (res) => resolve({
                    ok: false,
                    status: (res && Number(res.status)) || 0,
                    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
                    text: () => Promise.resolve(String((res && (res.responseText || res.error)) || 'network_error')),
                })
            });
            if (options.onXhr) options.onXhr(xhr);
        });
    }

    function makeFileFromArrayBuffer(arrayBuffer, fileName, mimeType) {
        const name = String(fileName || 'file.bin');
        const type = String(mimeType || 'application/octet-stream');
        try {
            return new File([arrayBuffer], name, { type });
        } catch (e) {
            const blob = new Blob([arrayBuffer], { type });
            blob.name = name;
            return blob;
        }
    }

    async function sha256HexFromArrayBuffer(arrayBuffer) {
        const cryptoObj = (globalScope && globalScope.crypto) ? globalScope.crypto : (typeof crypto !== 'undefined' ? crypto : null);
        if (!cryptoObj || !cryptoObj.subtle || typeof cryptoObj.subtle.digest !== 'function') {
            throw new Error('crypto_subtle_unavailable');
        }
        const hash = await cryptoObj.subtle.digest('SHA-256', arrayBuffer);
        const u8 = new Uint8Array(hash);
        let hex = '';
        for (let i = 0; i < u8.length; i++) hex += u8[i].toString(16).padStart(2, '0');
        return hex;
    }

    const UGC_SERVICE = {
        _lastUserSyncKey: '',
        getViewer() {
            if (!hasValidAkiToken()) return null;
            return getAkiMapUserInfo();
        },
        requireViewer() {
            const v = this.getViewer();
            if (!v || !v.userId) throw new Error('未登录：无法进行此操作');
            return v;
        },
        async syncViewer() {
            const v = this.getViewer();
            if (!v || !v.userId) return;
            const key = `${v.userId}::${v.userName || ''}`;
            if (key === this._lastUserSyncKey) return;
            this._lastUserSyncKey = key;
            await gmFetch(`${CONFIG.api.base}/rpc/upsert_user`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ p_user_id: v.userId, p_user_name: v.userName })
            });
        },
        async get(fp) {
            await this.syncViewer();
            const res = await gmFetch(`${CONFIG.api.base}/tag_details?fingerprint=eq.${fp}`);
            const rows = await res.json();
            const tagMap = {};
            const viewerId = this.getViewer()?.userId || null;
            if (Array.isArray(rows)) rows.forEach(row => {
                if (!row || !row.text) return;
                const key = String(row.text);
                if (!tagMap[key]) {
                    tagMap[key] = {
                        text: key,
                        score: Number(row.score) || 0,
                        myVote: 0,
                        authorUserId: row.author_userid ?? row.author_id ?? row.authorUserId ?? null,
                        authorUserName: row.author_username ?? row.author_name ?? row.authorUserName ?? ''
                    };
                }

                if (typeof row.score === 'number') tagMap[key].score = row.score;
                if (row.my_vote === 1 || row.my_vote === -1) tagMap[key].myVote = row.my_vote;
                if (row.myVote === 1 || row.myVote === -1) tagMap[key].myVote = row.myVote;

                if (!tagMap[key].authorUserId && (row.author_userid || row.author_id || row.authorUserId)) {
                    tagMap[key].authorUserId = row.author_userid ?? row.author_id ?? row.authorUserId;
                }
                if (!tagMap[key].authorUserName && (row.author_username || row.author_name || row.authorUserName)) {
                    tagMap[key].authorUserName = row.author_username ?? row.author_name ?? row.authorUserName ?? '';
                }

                if (viewerId && row.voter_id && String(row.voter_id) === String(viewerId)) {
                    if (row.my_vote === 1 || row.my_vote === -1) tagMap[key].myVote = row.my_vote;
                }
            });
            return { tags: Object.values(tagMap).sort((a,b) => b.score - a.score) };
        },
        async addTag(fp, text) {
            const v = this.requireViewer();
            await this.syncViewer();
            await gmFetch(`${CONFIG.api.base}/rpc/add_tag`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ p_fp: fp, p_text: text, p_user_id: v.userId, p_user_name: v.userName })
            });
            return this.get(fp);
        },
        async voteTag(fp, text, val) {
            const v = this.requireViewer();
            await this.syncViewer();
            await gmFetch(`${CONFIG.api.base}/rpc/vote_tag`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ p_fp: fp, p_text: text, p_user_id: v.userId, p_user_name: v.userName, p_val: val })
            });
            return this.get(fp);
        },
        async deleteTag(fp, text) {
            const v = this.requireViewer();
            await this.syncViewer();
            await gmFetch(`${CONFIG.api.base}/rpc/delete_tag`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ p_fp: fp, p_text: text, p_user_id: v.userId, p_user_name: v.userName })
            });
            return this.get(fp);
        },
        async getHotTags() {
            const res = await gmFetch(`${CONFIG.api.base}/rpc/get_hot_tags`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
            return await res.json();
        },
        async searchTags(query) {
            const q = encodeURIComponent(String(query || ''));
            const res = await gmFetch(`${CONFIG.api.base}/tags?text=ilike.*${q}*&select=fingerprint,text`);
            return await res.json();
        },

        // Routes plaza (zip collections)
        async listRoutes({ tab = 'plaza', q = '', sort = 'downloads', page = 1, pageSize = 20 } = {}) {
            const v = this.getViewer();
            const headers = {};
            if (v && v.userId) headers['X-User-Id'] = String(v.userId);

            const qs = new URLSearchParams();
            qs.set('tab', String(tab || 'plaza'));
            if (q) qs.set('q', String(q));
            qs.set('sort', String(sort || 'downloads'));
            qs.set('page', String(page || 1));
            qs.set('page_size', String(pageSize || 20));

            const res = await gmFetch(`${CONFIG.api.base}/routes?${qs.toString()}`, { headers });
            const data = await res.json();
            if (!res.ok) throw new Error((data && data.detail) ? String(data.detail) : 'routes_failed');
            return data;
        },

        async routesUploadInit({ routeName, routeDesc, sha256, sizeBytes }) {
            const v = this.requireViewer();
            await this.syncViewer();
            const res = await gmFetch(`${CONFIG.api.base}/routes/upload/init`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: v.userId,
                    user_name: v.userName || '',
                    route_name: routeName,
                    route_desc: routeDesc || '',
                    sha256,
                    size_bytes: sizeBytes
                })
            });
            const data = await res.json();
            if (!res.ok) throw new Error((data && data.detail) ? String(data.detail) : 'upload_init_failed');
            return data;
        },

        async routesUploadComplete(uploadId) {
            const v = this.requireViewer();
            await this.syncViewer();
            const res = await gmFetch(`${CONFIG.api.base}/routes/upload/complete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ upload_id: uploadId, user_id: v.userId })
            });
            const data = await res.json();
            if (!res.ok) throw new Error((data && data.detail) ? String(data.detail) : 'upload_complete_failed');
            return data;
        },

        async toggleRouteFavorite(routeId) {
            const v = this.requireViewer();
            await this.syncViewer();
            const res = await gmFetch(`${CONFIG.api.base}/routes/${routeId}/favorite`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: v.userId, user_name: v.userName || '' })
            });
            const data = await res.json();
            if (!res.ok) throw new Error((data && data.detail) ? String(data.detail) : 'favorite_failed');
            return data;
        },

        async toggleRouteLike(routeId) {
            const v = this.requireViewer();
            await this.syncViewer();
            const res = await gmFetch(`${CONFIG.api.base}/routes/${routeId}/like`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: v.userId, user_name: v.userName || '' })
            });
            const data = await res.json();
            if (!res.ok) throw new Error((data && data.detail) ? String(data.detail) : 'like_failed');
            return data;
        },

        async deleteRoute(routeId) {
            const v = this.requireViewer();
            await this.syncViewer();
            const res = await gmFetch(`${CONFIG.api.base}/routes/${routeId}/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: v.userId })
            });
            const data = await res.json();
            if (!res.ok) throw new Error((data && data.detail) ? String(data.detail) : 'delete_failed');
            return data;
        },

        async getRouteDownloadUrl(routeId) {
            const res = await gmFetch(`${CONFIG.api.base}/routes/${routeId}/download`);
            const data = await res.json();
            if (!res.ok) throw new Error((data && data.detail) ? String(data.detail) : 'download_failed');
            return data && data.url ? String(data.url) : '';
        }
    };

    const AUTO_TOKEN = localStorage.getItem('AKI_MAP_USER_TOKEN') || '';
    const isTokenValid = AUTO_TOKEN && AUTO_TOKEN.length > 20;

    function getMapStore() {
        const app = document.querySelector('#app')?.__vue_app__;
        return app?.config?.globalProperties?.$pinia?.state?.value?.useMapStore;
    }

    function injectPiniaState(targetId, targetType, isDone) {
        try {
            const store = getMapStore();
            if (!store) return;
            const targetSet = store.haveDonePositionIds;
            const idStr = String(targetId).trim();

            // 数据层
            if (isDone) {
                if (targetSet instanceof Set) targetSet.add(idStr);
            } else {
                if (targetSet instanceof Set) targetSet.delete(idStr);
            }

            // 视觉层
            const cacheMap = store.markersCache.get(targetType);
            if (cacheMap) {
                const pointController = cacheMap.get(idStr) || cacheMap.get(Number(idStr));
                if (pointController) {
                    const opacityValue = isDone ? 0.4 : 1.0;
                    if (typeof pointController.setOpacity === 'function') {
                        pointController.setOpacity(opacityValue);
                    } else if (pointController.markers && pointController.markers[0]) {
                        pointController.markers[0].setOpacity(opacityValue);
                    }
                }
            }
        } catch (e) {
            console.error('注入异常:', e);
        }
    }

    function rememberSmartMark(target) {
        if (!target) return;
        STATE.smartMarkHistory.push({
            id: String(target.id),
            type: target.type,
            name: target.name || SMART_MARK_TEXT.unnamed
        });
        if (STATE.smartMarkHistory.length > SMART_MARK_HISTORY_LIMIT) {
            STATE.smartMarkHistory.splice(0, STATE.smartMarkHistory.length - SMART_MARK_HISTORY_LIMIT);
        }
    }

    function getMarkerControllerById(targetId, targetType) {
        try {
            const store = getMapStore();
            const cache = store && store.markersCache;
            if (!(cache instanceof Map)) return null;
            const typeStr = String(targetType).trim();
            const cacheMap = cache.get(targetType) || cache.get(typeStr) || cache.get(Number(typeStr));
            if (!cacheMap) return null;
            const idStr = String(targetId).trim();
            return cacheMap.get(idStr) || cacheMap.get(Number(idStr)) || null;
        } catch (e) {
            return null;
        }
    }

    async function changeMarkerStatus(target, isDone) {
        if (!target) throw new Error('missing_target');

        const formData = new URLSearchParams();
        formData.append('id', target.id);
        formData.append('status', isDone ? 1 : 0);
        formData.append('positionType', target.type);

        let changedLocally = false;
        try {
            injectPiniaState(target.id, target.type, isDone);
            changedLocally = true;

            const response = await fetch("https://api.kurobbs.com/map/core/position/changeStatus", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Token": AUTO_TOKEN,
                    "Source": "h5",
                    "Wiki_type": "10",
                    "State_id": "8"
                },
                body: formData
            });

            const data = await response.json();
            if (data.code === 200) return data;
            throw new Error(data.msg || 'change_status_failed');
        } catch (error) {
            if (changedLocally) injectPiniaState(target.id, target.type, !isDone);
            throw error;
        }
    }

    function findNextActionableMarker(wantToMarkDone) {
        const store = getMapStore();
        if (!store) return { error: "无法连接地图数据" };

        const map = STATE.mapInstance; // 直接使用 zhenhe1.js 维护的 map 实例
        if (!map) return { error: "地图未加载" };

        const center = map.getCenter();
        const cache = store.markersCache;
        const doneSet = store.haveDonePositionIds;

        let candidates = [];

        cache.forEach((layerMap, typeKey) => {
            layerMap.forEach((pointObj, pointId) => {
                let latlng = pointObj.getLatLng ? pointObj.getLatLng() :
                             (pointObj._latlng ? pointObj._latlng :
                             (pointObj.markers && pointObj.markers[0] ? pointObj.markers[0].getLatLng() : null));

                if (latlng) {
                    const dist = map.distance(center, latlng);
                    candidates.push({
                        id: String(pointId),
                        type: typeKey,
                        name: pointObj.options?.name || '未命名',
                        dist: dist,
                        obj: pointObj
                    });
                }
            });
        });

        candidates.sort((a, b) => a.dist - b.dist);

        let skippedCount = 0;
        let target = null;

        for (let item of candidates) {
            const isAlreadyDone = doneSet.has(item.id);
            if (wantToMarkDone && isAlreadyDone) { skippedCount++; continue; }
            if (!wantToMarkDone && !isAlreadyDone) { skippedCount++; continue; }
            target = item;
            break;
        }
        return { target, skippedCount };
    }

    async function handleSmartAction(isDone) {
        const statusLog = document.getElementById('sm-auto-log');
        const infoDiv = document.getElementById('sm-auto-info');
        if(!statusLog || !infoDiv) return;

        statusLog.innerHTML = '<span style="color:#dcb268">🤖 正在计算...</span>';

        const result = findNextActionableMarker(isDone);

        if (result.error) {
            statusLog.innerText = `❌ ${result.error}`;
            return;
        }

        const { target, skippedCount } = result;

        if (!target) {
            infoDiv.innerHTML = `范围扫描完毕 (跳过 ${skippedCount})`;
            statusLog.innerHTML = '<span style="color:#4caf50">✅ 附近无目标</span>';
            return;
        }

        infoDiv.innerHTML = `锁定: <b style="color:#fff">${target.name}</b> <span style="color:#666;font-size:10px">(跳过${skippedCount})</span>`;
        statusLog.innerHTML = `<span style="color:#2196F3">⚡ 同步中...</span>`;

        try {
            await changeMarkerStatus(target, isDone);
            if (isDone) rememberSmartMark(target);
            statusLog.innerHTML = `<span style="color:#4CAF50">🎉 成功!</span>`;
        } catch (error) {
            statusLog.innerText = `❌ ${error && error.message ? error.message : SMART_MARK_TEXT.requestFailed}`;
        }
    }

    async function undoLastSmartMark() {
        const statusLog = document.getElementById('sm-auto-log');
        const infoDiv = document.getElementById('sm-auto-info');
        if(!statusLog || !infoDiv) return;

        const target = STATE.smartMarkHistory.pop();
        if (!target) {
            infoDiv.innerHTML = SMART_MARK_TEXT.noUndoTarget;
            statusLog.innerHTML = `<span style="color:#888">${SMART_MARK_TEXT.noHistory}</span>`;
            return;
        }

        const ctrl = getMarkerControllerById(target.id, target.type);
        const undoTarget = {
            id: target.id,
            type: target.type,
            name: target.name || (ctrl && ctrl.options && ctrl.options.name) || SMART_MARK_TEXT.unnamed,
            obj: ctrl
        };

        infoDiv.innerHTML = `${SMART_MARK_TEXT.undoLabel}: <b style="color:#fff">${undoTarget.name}</b>`;
        statusLog.innerHTML = `<span style="color:#2196F3">↩️ ${SMART_MARK_TEXT.undoing}</span>`;

        try {
            await changeMarkerStatus(undoTarget, false);
            statusLog.innerHTML = `<span style="color:#4CAF50">${SMART_MARK_TEXT.undone}</span>`;
        } catch (error) {
            STATE.smartMarkHistory.push(target);
            if (STATE.smartMarkHistory.length > SMART_MARK_HISTORY_LIMIT) {
                STATE.smartMarkHistory.splice(0, STATE.smartMarkHistory.length - SMART_MARK_HISTORY_LIMIT);
            }
            statusLog.innerText = `❌ ${error && error.message ? error.message : SMART_MARK_TEXT.undoFailed}`;
        }
    }


    // ==============================
    // 最近未完成点：打开详情弹窗 / 关闭弹窗
    // ==============================
    // 目标：一键打开距离地图中心最近且“未完成”的点位详情（走站点自身 click -> getDetailOnline -> popup 链路）
    // 关闭：直接调用 Leaflet map.closePopup()
    function openNearestUnfinishedDetailPopup() {
        const statusLog = document.getElementById('sm-auto-log');
        const infoDiv = document.getElementById('sm-auto-info');

        if (statusLog) statusLog.innerHTML = '<span style="color:#dcb268">🧭 正在定位最近未完成...</span>';

        // wantToMarkDone=true => 过滤掉已完成，选最近“未完成”
        const result = findNextActionableMarker(true);
        if (result && result.error) {
            if (statusLog) statusLog.innerText = `❌ ${result.error}`;
            return;
        }

        const target = result ? result.target : null;
        const skippedCount = result ? result.skippedCount : 0;
        if (!target) {
            if (infoDiv) infoDiv.innerHTML = `范围扫描完毕 (跳过 ${skippedCount})`;
            if (statusLog) statusLog.innerHTML = '<span style="color:#4caf50">✅ 附近无未完成目标</span>';
            return;
        }

        try {
            // 记录最后一次打开的点，方便调试/扩展
            STATE.lastOpenedDetail = { id: String(target.id), type: String(target.type), name: String(target.name || '') };
        } catch (e) {}

        if (infoDiv) {
            infoDiv.innerHTML = `锁定: <b style="color:#fff">${target.name}</b> <span style="color:#666;font-size:10px">(跳过${skippedCount})</span>`;
        }

        // 优先走站点原生 click 链路：
        // 1) controller.click()（若存在）
        // 2) marker.fire('click', {latlng})（Leaflet Evented）
        // 3) marker.openPopup()（若已绑定 popup）
        try {
            const ctrl = target.obj;
            if (ctrl && typeof ctrl.click === 'function') {
                ctrl.click();
                if (statusLog) statusLog.innerHTML = '<span style="color:#2196F3">🪟 已请求打开详情</span>';
                return;
            }

            const mk0 = ctrl && ctrl.markers && ctrl.markers[0] ? ctrl.markers[0] : null;
            if (mk0 && typeof mk0.fire === 'function') {
                let latlng = null;
                try { latlng = (typeof mk0.getLatLng === 'function') ? mk0.getLatLng() : (mk0._latlng || null); } catch (e) { latlng = null; }
                mk0.fire('click', latlng ? { latlng } : undefined);
                if (statusLog) statusLog.innerHTML = '<span style="color:#2196F3">🪟 已请求打开详情</span>';
                return;
            }

            if (mk0 && typeof mk0.openPopup === 'function') {
                mk0.openPopup();
                if (statusLog) statusLog.innerHTML = '<span style="color:#2196F3">🪟 已尝试打开弹窗</span>';
                return;
            }

            if (statusLog) statusLog.innerText = '❌ 无法打开：未找到可点击的 marker/controller';
        } catch (e) {
            if (statusLog) statusLog.innerText = `❌ 打开失败: ${toReason(e)}`;
        }
    }

    function closeDetailPopup() {
        const statusLog = document.getElementById('sm-auto-log');
        try {
            if (STATE.mapInstance && typeof STATE.mapInstance.closePopup === 'function') {
                STATE.mapInstance.closePopup();
            }
            if (statusLog) statusLog.innerHTML = '<span style="color:#888">🧹 已关闭弹窗</span>';
        } catch (e) {
            if (statusLog) statusLog.innerText = `❌ 关闭失败: ${toReason(e)}`;
        }
    }

    async function getHotTagTexts() {
        try {
            const rawTags = await UGC_SERVICE.getHotTags();
            return Array.isArray(rawTags) ? rawTags.map(item => item.text).filter(Boolean) : [];
        } catch (e) {
            return [];
        }
    }

    async function ensureHotTagTexts(force = false) {
        try {
            const ttlMs = 5 * 60 * 1000;
            const now = Date.now();
            const items0 = Array.isArray(STATE.searchUI && STATE.searchUI._hotTags) ? STATE.searchUI._hotTags : [];
            const at0 = Number(STATE.searchUI && STATE.searchUI._hotTagsAt) || 0;
            if (!force && items0.length && (now - at0) < ttlMs) return items0;

            const p0 = STATE.searchUI && STATE.searchUI._hotTagsPromise;
            if (!force && p0) return await p0;

            const p = (async () => {
                let raw = [];
                try { raw = await UGC_SERVICE.getHotTags(); } catch (e) { raw = []; }
                const tags = Array.isArray(raw)
                    ? raw
                        .map(item => ({ text: item && item.text ? String(item.text) : '', score: Number(item && item.score) || 0 }))
                        .filter(item => item.text)
                        .sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0))
                    : [];
                try {
                    STATE.searchUI._hotTags = tags;
                    STATE.searchUI._hotTagsAt = Date.now();
                } catch (e) {}
                return tags;
            })();

            try { STATE.searchUI._hotTagsPromise = p; } catch (e) {}
            try { return await p; }
            finally {
                try {
                    if (STATE.searchUI && STATE.searchUI._hotTagsPromise === p) STATE.searchUI._hotTagsPromise = null;
                } catch (e) {}
            }
        } catch (e) {
            return [];
        }
    }

    function bindTagSearchResultInteractions(results, input, tagGroups) {
        if (!results) return;
        const applyActiveStyles = () => {
            results.querySelectorAll('.group').forEach(el => el.classList.toggle('active', STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key === el.dataset.tag));
            results.querySelectorAll('.single').forEach(el => el.classList.toggle('active', STATE.searchUI.tagSelection.kind === 'fp' && STATE.searchUI.tagSelection.key === el.dataset.fp));
        };

        // 若已选中且开启聚焦：在渲染结果后立即重放聚焦（不依赖再次点击）
        try {
            if (STATE.searchUI && STATE.searchUI.tagFocusOnly) {
                if (STATE.searchUI.tagSelection.kind === 'fp' && STATE.searchUI.tagSelection.key) {
                    applyMarkerFocusByFps([STATE.searchUI.tagSelection.key]);
                } else if (STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key) {
                    const fps1 = Array.isArray(STATE.searchUI._selectedFps) ? STATE.searchUI._selectedFps : [];
                    if (fps1.length) applyMarkerFocusByFps(fps1);
                }
            }
        } catch (e) {}

        results.querySelectorAll('.group').forEach(el => {
            el.onclick = () => {
                const tag = el.dataset.tag || '';
                if (STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key === tag) {
                    STATE.searchUI.tagSelection = { kind: '', key: '' };
                    STATE.searchUI._selectedFps = [];
                    clearHighlightPoints();
                    clearMarkerFocus();
                    applyActiveStyles();
                    try { results.style.display = 'block'; } catch (e) {}
                    try { input && input.focus && input.focus(); } catch (e) {}
                    return;
                }
                STATE.searchUI.tagSelection = { kind: 'tag', key: tag };
                const pts = tagGroups[tag] || [];
                if (STATE.searchUI.tagFocusOnly) clearHighlightPoints();
                else highlightPoints(pts);
                const fps = pts.map(p => p && p.fp).filter(Boolean);
                STATE.searchUI._selectedFps = fps;
                if (STATE.searchUI.tagFocusOnly) {
                    if (fps.length) applyMarkerFocusByFps(fps);
                } else {
                    clearMarkerFocus();
                }
                applyActiveStyles();
                try { results.style.display = 'block'; } catch (e) {}
                try { input && input.focus && input.focus(); } catch (e) {}
            };
        });
        results.querySelectorAll('.single').forEach(el => {
            el.onclick = () => {
                const fp = el.dataset.fp || '';
                if (STATE.searchUI.tagSelection.kind === 'fp' && STATE.searchUI.tagSelection.key === fp) {
                    STATE.searchUI.tagSelection = { kind: '', key: '' };
                    STATE.searchUI._selectedFps = [];
                    clearHighlightPoints();
                    clearMarkerFocus();
                    applyActiveStyles();
                    try { results.style.display = 'block'; } catch (e) {}
                    try { input && input.focus && input.focus(); } catch (e) {}
                    return;
                }
                STATE.searchUI.tagSelection = { kind: 'fp', key: fp };
                STATE.searchUI._selectedFps = fp ? [fp] : [];
                const p = STATE.pointCache.get(fp);
                if (STATE.searchUI.tagFocusOnly) clearHighlightPoints();
                else highlightPoints(p ? [p] : []);
                if (STATE.searchUI.tagFocusOnly) applyMarkerFocusByFps([fp]);
                else clearMarkerFocus();
                applyActiveStyles();
                try { results.style.display = 'block'; } catch (e) {}
                try { input && input.focus && input.focus(); } catch (e) {}
            };
        });
    }

    async function ensureHotTagFps(tagText) {
        const key = String(tagText || '');
        if (!key) return [];
        try {
            const cache = STATE.searchUI && STATE.searchUI._hotTagFpCache;
            const ttlMs = 10 * 60 * 1000;
            const now = Date.now();
            if (cache && typeof cache.get === 'function') {
                const hit = cache.get(key);
                if (hit && Array.isArray(hit.fps) && hit.fps.length && (now - (Number(hit.at) || 0)) < ttlMs) return hit.fps;
            }
        } catch (e) {}

        let fps = [];
        try {
            const remote = await UGC_SERVICE.searchTags(key);
            if (Array.isArray(remote)) {
                fps = remote
                    .filter(t => t && String(t.text) === key && t.fingerprint)
                    .map(t => String(t.fingerprint))
                    .filter(Boolean);
            }
        } catch (e) {
            fps = [];
        }

        try {
            const cache = STATE.searchUI && STATE.searchUI._hotTagFpCache;
            if (cache && typeof cache.set === 'function') cache.set(key, { fps, at: Date.now() });
        } catch (e) {}
        return fps;
    }

    async function showTagIdleResults(input, results) {
        if (!results) return;
        results.style.display = 'block';

        const seq = (STATE.searchUI._idleSeq = (Number(STATE.searchUI._idleSeq) || 0) + 1);
        const q = input ? String(input.value || '').trim() : '';
        if (STATE.searchUI && STATE.searchUI.mode !== 'tag') return;
        if (q) return;

        results.innerHTML = '<div style="padding:10px;color:#777;text-align:center;">热门标签加载中...</div>';
        const hot = await ensureHotTagTexts();
        if ((STATE.searchUI && STATE.searchUI._idleSeq) !== seq) return;
        if (STATE.searchUI && STATE.searchUI.mode !== 'tag') return;
        if ((input ? String(input.value || '').trim() : '') !== '') return;

        const totalTags = hot.length;
        const pageSizeTags = Math.max(1, Number(STATE.searchUI.idle && STATE.searchUI.idle.pageSizeTags) || 20);
        const pageSizeSingles = Math.max(0, Number(STATE.searchUI.idle && STATE.searchUI.idle.pageSizeSingles) || 10);
        const totalPages = Math.max(1, Math.ceil(totalTags / pageSizeTags) || 1);

        // 若已选中某 tag：自动跳转到其所在页，保证可见
        try {
            if (STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key) {
                const idx = hot.findIndex(x => x && x.text === STATE.searchUI.tagSelection.key);
                if (idx >= 0) STATE.searchUI.idle.page = Math.floor(idx / pageSizeTags) + 1;
            }
        } catch (e) {}

        const page0 = Math.min(totalPages, Math.max(1, Number(STATE.searchUI.idle && STATE.searchUI.idle.page) || 1));
        STATE.searchUI.idle.page = page0;
        const slice = hot.slice((page0 - 1) * pageSizeTags, page0 * pageSizeTags);

        const renderPagerTop = () => `
            <div class="sm-idle-top">
                <div class="sm-idle-title">热门（按热度）</div>
                <div class="sm-idle-pager">
                    <button class="sm-btn" type="button" data-idle-act="prev" ${page0 <= 1 ? 'disabled' : ''}>上一页</button>
                    <span class="sm-idle-page">${page0}/${totalPages}</span>
                    <button class="sm-btn" type="button" data-idle-act="next" ${page0 >= totalPages ? 'disabled' : ''}>下一页</button>
                </div>
            </div>
        `;

        results.innerHTML = `${renderPagerTop()}<div style="padding:10px;color:#888;">加载中...</div>`;
        results.querySelectorAll('[data-idle-act]').forEach(btn => {
            btn.onclick = () => {
                const act = btn.dataset.idleAct || '';
                if (act === 'prev') STATE.searchUI.idle.page = Math.max(1, (Number(STATE.searchUI.idle.page) || 1) - 1);
                if (act === 'next') STATE.searchUI.idle.page = Math.min(totalPages, (Number(STATE.searchUI.idle.page) || 1) + 1);
                showTagIdleResults(input, results).catch(() => {});
            };
        });

        const tagGroups = {};
        const union = new Map(); // fp -> point
        for (const it of slice) {
            const tag = it && it.text ? String(it.text) : '';
            if (!tag) continue;
            const fps = await ensureHotTagFps(tag);
            if ((STATE.searchUI && STATE.searchUI._idleSeq) !== seq) return;
            const pts = [];
            (fps || []).forEach(fp => {
                const p = STATE.pointCache.get(fp);
                if (!p) return;
                if (!pts.includes(p)) pts.push(p);
                if (p && p.fp && !union.has(p.fp)) union.set(p.fp, p);
            });
            tagGroups[tag] = pts;
        }

        const singles = Array.from(union.values())
            .filter(p => p && p.fp && p.name)
            .sort((a, b) => String(a.name).localeCompare(String(b.name), 'zh-Hans-CN', { numeric: true, sensitivity: 'base' }))
            .slice(0, pageSizeSingles);

        let html = renderPagerTop();
        Object.keys(tagGroups).forEach(tag => {
            const isActive = (STATE.searchUI && STATE.searchUI.tagSelection && STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key === tag);
            html += `
                <div class="sm-result-item group ${isActive ? 'active' : ''}" data-tag="${tag}">
                    <div><span style="color:var(--sm-gold);font-weight:bold">${tag}</span><small style="color:#888;margin-left:5px">(${tagGroups[tag].length})</small></div>
                    <button class="sm-btn" style="width:auto;padding:2px 6px;font-size:10px">定位</button>
                </div>`;
        });
        singles.forEach(p => {
            const isActive = (STATE.searchUI && STATE.searchUI.tagSelection && STATE.searchUI.tagSelection.kind === 'fp' && STATE.searchUI.tagSelection.key === p.fp);
            html += `<div class="sm-result-item single ${isActive ? 'active' : ''}" data-fp="${p.fp}"><div><span style="color:#fff">${p.name}</span></div><small style="color:#666;font-size:10px">点位</small></div>`;
        });
        if (!Object.keys(tagGroups).length && !singles.length) html += '<div style="padding:10px;color:#888;text-align:center">暂无数据</div>';
        results.innerHTML = html;

        results.querySelectorAll('[data-idle-act]').forEach(btn => {
            btn.onclick = () => {
                const act = btn.dataset.idleAct || '';
                if (act === 'prev') STATE.searchUI.idle.page = Math.max(1, (Number(STATE.searchUI.idle.page) || 1) - 1);
                if (act === 'next') STATE.searchUI.idle.page = Math.min(totalPages, (Number(STATE.searchUI.idle.page) || 1) + 1);
                showTagIdleResults(input, results).catch(() => {});
            };
        });

        bindTagSearchResultInteractions(results, input, tagGroups);
    }

    function bindHorizontalScrollNav(scrollArea, btnPrev, btnNext, getAmount) {
        if (!scrollArea || !btnPrev || !btnNext) return;
        const scrollByDir = (dir) => scrollArea.scrollBy({ left: dir * getAmount(), behavior: 'smooth' });
        btnPrev.onclick = (e) => { e.stopPropagation(); scrollByDir(-1); };
        btnNext.onclick = (e) => { e.stopPropagation(); scrollByDir(1); };
    }

    async function renderHotTagsCarousel(container, clickCallback) {
        container.innerHTML = '<span style="color:#666;font-size:10px;padding:4px">加载热门...</span>';
        const tags = await getHotTagTexts();

        if (!tags.length) {
            container.innerHTML = '<span style="color:#666;font-size:10px;padding:4px">暂无热门数据</span>';
            return;
        }

        const chipsHtml = tags.map(t => `<div class="kmp-chip">${t}</div>`).join('');

        container.innerHTML = `
            <div class="kmp-hot-carousel">
                <button class="kmp-carousel-btn prev">&lt;</button>
                <div class="kmp-hot-scroll-area">${chipsHtml}</div>
                <button class="kmp-carousel-btn next">&gt;</button>
            </div>
        `;

        const scrollArea = container.querySelector('.kmp-hot-scroll-area');
        const btnPrev = container.querySelector('.prev');
        const btnNext = container.querySelector('.next');

        container.querySelectorAll('.kmp-chip').forEach(chip => {
            chip.onclick = (e) => clickCallback(e, chip.innerText);
        });

        bindHorizontalScrollNav(scrollArea, btnPrev, btnNext, () => scrollArea.clientWidth * 0.8);
    }

    function createUnifiedUI() {
        if (document.getElementById('sm-sidebar') || document.getElementById('sm-toggle-btn')) {
            return;
        }
        const sidebar = document.createElement('div');
        const cleanUIKeys = Object.keys(STATE.toggles.cleanUI);
        const allCleanUIEnabled = cleanUIKeys.length > 0 && cleanUIKeys.every(key => STATE.toggles.cleanUI[key]);
        const cleanDropdownOpen = localStorage.getItem('SM_CLEAN_UI_DROPDOWN_OPEN') !== 'false';
        const tagFocusOnly = localStorage.getItem('SM_TAG_FOCUS_ONLY') !== 'false';
        STATE.searchUI.tagFocusOnly = tagFocusOnly;
        sidebar.id = 'sm-sidebar';
        sidebar.innerHTML = `
            <div class="sm-header">呜呜地图优化</div>
            <div class="sm-content">
                <div class="sm-section">
                    <div class="sm-section-title sm-clean-title">
                        <span>UI隐藏</span>
                    </div>
                    <div class="sm-ctrl-row sm-clean-master">
                        <button type="button" class="sm-dropdown-toggle ${cleanDropdownOpen ? 'is-open' : ''}" id="sm-clean-dropdown-toggle" aria-label="展开或收起 UI隐藏" aria-expanded="${cleanDropdownOpen ? 'true' : 'false'}">></button>
                        <span class="sm-ctrl-label">全部隐藏</span>
                        <label class="sm-switch">
                            <input type="checkbox" id="sm-clean-all-toggle" ${allCleanUIEnabled ? 'checked' : ''}>
                            <span class="sm-slider"></span>
                        </label>
                    </div>
                    <div class="sm-dropdown-body ${cleanDropdownOpen ? '' : 'is-collapsed'}" id="sm-clean-dropdown-body">
                        ${cleanUIKeys.map(key => `
                            <div class="sm-ctrl-row">
                                <span class="sm-ctrl-label">${keyToLabel(key)}</span>
                                <label class="sm-switch">
                                    <input type="checkbox" data-toggle="${key}" ${STATE.toggles.cleanUI[key] ? 'checked' : ''}>
                                    <span class="sm-slider"></span>
                                </label>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="sm-section">
                    <div class="sm-section-title">
                        自动标记
                        <span style="font-size:10px;font-weight:normal;margin-left:auto;color:${isTokenValid?'#4caf50':'#f44336'}">
                            ${isTokenValid ? '● 就绪' : '● 未登录'}
                        </span>
                    </div>
                    <div id="sm-auto-info" style="font-size:11px;color:#aaa;margin-bottom:6px;min-height:16px;line-height:1.4;">等待指令...</div>
                    <div class="sm-btn-group">
                        <button class="sm-btn" id="btn-mark-smart" style="color:#fff;border-color:#2196F3;background:rgba(33, 150, 243, 0.2)">标记下一个</button>
                        <button class="sm-btn" id="btn-undo-smart" style="color:#fff;border-color:#FF9800;background:rgba(255, 152, 0, 0.2)">撤销</button>
                    </div>
                    <div class="sm-btn-group" style="margin-top:6px;">
                        <button class="sm-btn" id="btn-open-nearest" style="color:#fff;border-color:#9c27b0;background:rgba(156, 39, 176, 0.18)">打开最近未完成</button>
                        <button class="sm-btn" id="btn-close-popup" style="color:#fff;border-color:#607d8b;background:rgba(96, 125, 139, 0.18)">关闭弹窗</button>
                    </div>
                    <div id="sm-auto-log" style="margin-top:4px;font-size:10px;text-align:right;height:14px;color:#666"></div>
                </div>
                <div class="sm-section">
                    <div class="sm-section-title">标记点样式</div>
                    <div class="sm-ctrl-row" id="sm-pause-tracking-popup-row" role="switch" tabindex="0" aria-checked="${STATE.toggles.pauseTrackingWhenPopupOpen ? 'true' : 'false'}">
                        <span class="sm-ctrl-label">弹窗打开时暂停追踪</span>
                        <label class="sm-switch">
                            <input type="checkbox" id="sm-pause-tracking-popup" ${STATE.toggles.pauseTrackingWhenPopupOpen ? 'checked' : ''}>
                            <span class="sm-slider"></span>
                        </label>
                    </div>
                    <div class="sm-ctrl-row">
                        <span class="sm-ctrl-label">去大头针化</span>
                        <label class="sm-switch">
                            <input type="checkbox" id="sm-marker-opt">
                            <span class="sm-slider"></span>
                        </label>
                    </div>
                </div>
                <div class="sm-section">
                    <div class="sm-section-title">路径绘制 <button class="sm-btn" id="sm-create-route-btn" style="margin-left:auto;flex:0 0 auto">新建路线</button></div>
                    <div class="sm-btn-group">
                        <button class="sm-btn" id="sm-import-btn">导入</button>
                        <input type="file" id="sm-file-input" multiple hidden accept=".json,.svg,.zip,application/zip">
                        <button class="sm-btn" id="sm-export-selected" style="border-color:#4caf50;color:#4caf50">批量导出</button>
                        <button class="sm-btn" id="sm-toggle-visible" style="border-color:#2196F3;color:#2196F3">隐藏全部</button>
                        <button class="sm-btn danger" id="sm-clear-route">清空路线</button>
                    </div>
                    <div id="sm-import-status" style="margin-top:6px;font-size:11px;color:#aaa;min-height:14px;"></div>
                    <div style="margin-top:10px">
                        <div class="sm-ctrl-label">线宽: <b id="val-w">${SETTINGS.pathWeight}</b></div>
                        <input type="range" id="rng-w" min="1" max="10" value="${SETTINGS.pathWeight}">
                        <div class="sm-ctrl-label">箭头大小: <b id="val-s">${SETTINGS.arrowSize}</b></div>
                        <input type="range" id="rng-s" min="0.5" max="3" step="0.1" value="${SETTINGS.arrowSize}">
                        <div class="sm-ctrl-label">箭头间距: <b id="val-g">${SETTINGS.arrowGap}</b></div>
                        <input type="range" id="rng-g" min="10" max="500" step="10" value="${SETTINGS.arrowGap}">
                    </div>
                    <div class="sm-route-mode-row">
                        <div class="sm-ctrl-label">仅显示单条路线</div>
                        <label class="sm-switch is-off">
                            <input type="checkbox" id="sm-single-route-toggle">
                            <span class="sm-slider"></span>
                        </label>
                    </div>
                    <div class="sm-route-marker-mode">
                        <div class="sm-ctrl-label">路线关联标记点</div>
                        <div class="sm-seg" id="sm-route-marker-display-mode">
                            <button class="sm-seg-btn" type="button" data-route-marker-mode="none">不处理</button>
                            <button class="sm-seg-btn" type="button" data-route-marker-mode="highlight">突出关联点</button>
                            <button class="sm-seg-btn" type="button" data-route-marker-mode="focus">仅显示关联点</button>
                        </div>
                    </div>
                    <div class="sm-route-nav">
                        <button class="sm-btn" id="sm-prev-route" disabled>上一条路线</button>
                        <button class="sm-btn" id="sm-next-route" disabled>下一条路线</button>
                    </div>
                    <div class="sm-section-title" style="margin-top:10px"><span>已导入列表</span><button class="sm-btn" id="sm-merge-selected" style="margin-left:auto;flex:0 0 auto">${ROUTE_LIST_TEXT.mergeSelected}</button></div>
                    <div id="sm-route-list"></div>
                </div>
                <div class="sm-section">
                    <div class="sm-section-title sm-search-title">
                        搜索
                        <div class="sm-seg" id="sm-search-mode">
                            <button class="sm-seg-btn active" type="button" data-mode="tag">标签</button>
                            <button class="sm-seg-btn" type="button" data-mode="route">路线</button>
                        </div>
                    </div>
                    <input type="text" class="sm-input" id="sm-search-input" placeholder="搜索点位名称 / 标签...">

                    <div id="sm-search-panel-tag">
                        <div class="sm-search-results" id="sm-search-results"></div>
                        <div class="sm-ctrl-row" style="margin-top:8px;">
                            <span class="sm-ctrl-label">屏蔽无关点且强制显示标记点</span>
                            <label class="sm-switch">
                                <input type="checkbox" id="sm-tag-focus-toggle" ${tagFocusOnly ? 'checked' : ''}>
                                <span class="sm-slider"></span>
                            </label>
                        </div>
                    </div>

                    <div id="sm-search-panel-route" style="display:none;">
                        <div class="sm-tabs" id="sm-route-tabs">
                            <button class="sm-tab-btn active" type="button" data-tab="square">广场</button>
                            <button class="sm-tab-btn" type="button" data-tab="fav">收藏</button>
                            <button class="sm-tab-btn" type="button" data-tab="mine">我的</button>
                        </div>
                        <div class="sm-route-square-list" id="sm-route-square-list"></div>
                        <div class="sm-route-footer">
                            <div class="sm-page-ctrl">
                                <button class="sm-page-btn" type="button" id="sm-route-page-prev" title="上一页">&lt;</button>
                                <span class="sm-page-display" id="sm-route-page-display" title="点击输入页码">1</span>
                                <input class="sm-page-input" id="sm-route-page-input" type="number" min="1" step="1" value="1" title="页码" style="display:none;">
                                <span style="color:#666">/</span>
                                <span id="sm-route-page-total" style="color:#888">1</span>
                                <button class="sm-page-btn" type="button" id="sm-route-page-next" title="下一页">&gt;</button>
                            </div>
                            <button class="sm-btn" type="button" id="sm-route-upload-btn" style="width:auto;border-color:var(--sm-gold);color:var(--sm-gold)">上传路线</button>
                            <div class="sm-sort-group" id="sm-route-sort">
                                <button class="sm-sort-btn active" type="button" data-sort="downloads" title="按下载排序" aria-label="按下载排序">
                                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v10m0 0l4-4m-4 4l-4-4M5 19h14" /></svg>
                                </button>
                                <button class="sm-sort-btn" type="button" data-sort="favorites" title="按收藏排序" aria-label="按收藏排序">
                                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l3 7 7 .6-5.3 4.6 1.7 7.2L12 17.8 5.6 21.4l1.7-7.2L2 9.6 9 9z" /></svg>
                                </button>
                                <button class="sm-sort-btn" type="button" data-sort="likes" title="按点赞排序" aria-label="按点赞排序">
                                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-4.6-9.3-8.7C.4 8.3 2.7 5.5 6 5.5c1.8 0 3.1 1 4 2.2.9-1.2 2.2-2.2 4-2.2 3.3 0 5.6 2.8 3.3 6.8C19 16.4 12 21 12 21z" /></svg>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(sidebar);

        injectRouteUploadModal();

        createToggleButton(sidebar);

        bindUIEvents(sidebar);
        try { window.renderRouteListUI && window.renderRouteListUI(); } catch (e) {}
    }

    function createToggleButton(sidebar) {
        const toggleBtn = document.createElement('div');
        toggleBtn.id = 'sm-toggle-btn';
        toggleBtn.innerText = '▶';
        toggleBtn.onclick = () => {
            sidebar.classList.toggle('active');
            toggleBtn.innerText = sidebar.classList.contains('active') ? '◀' : '▶';
        };
        document.body.appendChild(toggleBtn);
        return toggleBtn;
    }

    function injectRouteUploadModal() {
        if (document.getElementById('sm-route-modal-overlay')) return;

        const overlay = document.createElement('div');
        overlay.className = 'sm-modal-overlay';
        overlay.id = 'sm-route-modal-overlay';
        overlay.innerHTML = `
            <div class="sm-modal" role="dialog" aria-modal="true">
                <div class="sm-modal-title">上传路线</div>
                <input type="text" class="sm-input" id="sm-upload-name" placeholder="请输入路线名称（必填，1-40）">
                <textarea class="sm-input" id="sm-upload-desc" placeholder="请输入路线简介（可不填）" style="height:72px;resize:none;"></textarea>
                <button type="button" class="sm-upload-drop" id="sm-upload-file-btn">点击选择 ZIP 文件</button>
                <div class="sm-upload-filehint" id="sm-upload-filehint">未选择文件</div>
                <input type="file" id="sm-upload-zip-input" hidden accept=".zip,application/zip">
                <div id="sm-upload-status" style="margin-top:8px;font-size:11px;color:#aaa;min-height:14px;"></div>
                <div class="sm-modal-actions">
                    <button type="button" class="sm-modal-btn" id="sm-upload-cancel">取消</button>
                    <button type="button" class="sm-modal-btn primary" id="sm-upload-submit">提交</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        let activeUploadXhr = null;
        let submitBusy = false;
        let pickedFile = null;
        let cachedTicket = null; // { sha256, uploadId, ossUrl, ossFields, expireAt }

        const humanizeUploadErr = (raw) => {
            const s = String(raw || '');
            if (!s) return '未知错误';
            if (s.includes('upload_limit')) return '今日上传次数已达上限（10/天）';
            if (s.includes('not_owner')) return '登录状态异常（用户不匹配）';
            if (s.includes('expired')) return '上传票据已过期，请重新提交';
            if (s.includes('object_not_found')) return 'OSS 未找到上传的对象（可重试上传）';
            if (s.includes('oss_forbidden')) return 'OSS 权限不足：后端缺少 GetObject/HeadObject 权限（需要给 RAM 用户补最小读权限）';
            if (s.includes('oss_head_failed')) return 'OSS 校验失败：后端无法访问 OSS（可重试；若持续失败检查网络/权限）';
            if (s.includes('OSS上传失败(网络错误)')) return 'OSS 上传网络错误（可重试；若持续失败请刷新页面）';
            if (s.includes('OSS上传失败(')) return s.replace(/^上传失败：?/, '');
            return s.replace(/^上传失败：?/, '');
        };

        const close = () => {
            try { if (activeUploadXhr && typeof activeUploadXhr.abort === 'function') activeUploadXhr.abort(); } catch (e) {}
            activeUploadXhr = null;
            submitBusy = false;
            STATE.routeUploadModalOpen = false;

            const status = overlay.querySelector('#sm-upload-status');
            if (status) { status.style.color = '#aaa'; status.innerText = ''; }
            const nameEl = overlay.querySelector('#sm-upload-name');
            const descEl = overlay.querySelector('#sm-upload-desc');
            const fileInput2 = overlay.querySelector('#sm-upload-zip-input');
            const fileHint2 = overlay.querySelector('#sm-upload-filehint');
            const submitBtn2 = overlay.querySelector('#sm-upload-submit');

            if (nameEl) nameEl.value = '';
            if (descEl) descEl.value = '';
            if (fileInput2) fileInput2.value = '';
            if (fileHint2) fileHint2.innerText = '未选择文件';
            if (submitBtn2) submitBtn2.disabled = false;
            pickedFile = null;
            cachedTicket = null;
            if (btnPick) btnPick.innerHTML = '点击选择 ZIP 文件';
            overlay.style.display = 'none';
        };

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) close();
        });

        const btnCancel = overlay.querySelector('#sm-upload-cancel');
        if (btnCancel) btnCancel.addEventListener('click', close);

        const btnPick = overlay.querySelector('#sm-upload-file-btn');
        const fileInput = overlay.querySelector('#sm-upload-zip-input');
        const fileHint = overlay.querySelector('#sm-upload-filehint');

        const renderPickedFileUI = (f) => {
            const fileName = f ? String(f.name || '') : '';
            if (btnPick) {
                if (f) {
                    btnPick.innerHTML = `<span style="font-weight:700;color:var(--sm-gold);">当前文件：</span><span style="font-weight:700;color:#ddd;">${escapeHtml(fileName)}</span>`;
                } else {
                    btnPick.innerHTML = '点击选择 ZIP 文件';
                }
            }
            if (fileHint) fileHint.innerText = f ? `已选择 ZIP（${formatBytes(f.size)}，可点击/拖拽替换）` : '未选择文件（支持点击选择或拖拽 ZIP 到上方按钮）';
        };

        if (btnPick && fileInput) {
            btnPick.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', () => {
                const f = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
                pickedFile = f;
                cachedTicket = null;
                renderPickedFileUI(f);
            });

            // Drag & drop ZIP (only inside modal; prevent leaking to page-level drop handler)
            const stop = (e) => {
                try { e.preventDefault(); } catch (err) {}
                try { e.stopPropagation(); } catch (err) {}
            };
            const setOver = (on) => { try { btnPick.classList.toggle('dragover', !!on); } catch (e) {} };
            ['dragenter', 'dragover'].forEach(evt => {
                btnPick.addEventListener(evt, (e) => { stop(e); setOver(true); }, true);
            });
            ['dragleave', 'dragend', 'drop'].forEach(evt => {
                btnPick.addEventListener(evt, (e) => { stop(e); setOver(false); }, true);
            });
            btnPick.addEventListener('drop', (e) => {
                const dt = e && e.dataTransfer ? e.dataTransfer : null;
                const f = dt && dt.files && dt.files[0] ? dt.files[0] : null;
                pickedFile = f;
                cachedTicket = null;
                renderPickedFileUI(f);
            }, true);
        }

        const btnSubmit = overlay.querySelector('#sm-upload-submit');
        if (btnSubmit) {
            btnSubmit.addEventListener('click', async () => {
                if (submitBusy) return;
                const status = overlay.querySelector('#sm-upload-status');
                const nameEl = overlay.querySelector('#sm-upload-name');
                const descEl = overlay.querySelector('#sm-upload-desc');
                const f = pickedFile || (fileInput && fileInput.files && fileInput.files[0] ? fileInput.files[0] : null);

                const v = UGC_SERVICE && typeof UGC_SERVICE.getViewer === 'function' ? UGC_SERVICE.getViewer() : null;
                if (!v || !v.userId) {
                    if (status) { status.style.color = '#f44336'; status.innerText = '未登录：无法上传路线'; }
                    return;
                }

                const name = nameEl ? String(nameEl.value || '').trim() : '';
                if (!name || name.length > 40) {
                    if (status) { status.style.color = '#f44336'; status.innerText = '路线名称必填，且长度需为 1-40'; }
                    return;
                }
                const desc = descEl ? String(descEl.value || '').trim() : '';
                if (desc.length > 400) {
                    if (status) { status.style.color = '#f44336'; status.innerText = '路线简介过长（最多 400 字）'; }
                    return;
                }
                if (!f) {
                    if (status) { status.style.color = '#f44336'; status.innerText = '请选择 ZIP 文件'; }
                    return;
                }
                const ext = lowerExt(f.name);
                if (ext !== '.zip') {
                    if (status) { status.style.color = '#f44336'; status.innerText = '仅支持上传 ZIP 文件'; }
                    return;
                }
                if (f.size > 5 * 1024 * 1024) {
                    if (status) { status.style.color = '#f44336'; status.innerText = `ZIP 超出大小限制：${formatBytes(f.size)} > 5MB`; }
                    return;
                }

                submitBusy = true;
                btnSubmit.disabled = true;

                try {
                    if (status) { status.style.color = '#aaa'; status.innerText = '正在校验ZIP(JSZip)...'; }

                    let JSZipLib;
                    try { JSZipLib = await ensurePageJSZip(); }
                    catch (e) { throw new Error(`JSZip加载失败：${toReason(e)}`); }

                    const ab = await readAsArrayBuffer(f);
                    await withTimeout(JSZipLib.loadAsync(ab), 8000, 'ZIP解析超时');

                    if (status) { status.style.color = '#aaa'; status.innerText = '正在计算SHA256...'; }
                    const sha256 = await sha256HexFromArrayBuffer(ab);

                    let initRes = null;
                    const nowSec = Math.floor(Date.now() / 1000);

                    // Try reuse ticket from global cache first (so closing/reopening modal won't consume new quota).
                    try {
                        const t = STATE.routeUploadTickets && typeof STATE.routeUploadTickets.get === 'function'
                            ? STATE.routeUploadTickets.get(sha256)
                            : null;
                        if (t && t.sha256 === sha256 && t.uploadId && t.ossUrl && t.ossFields) {
                            const ok = (!t.expireAt || nowSec < (Number(t.expireAt) - 2));
                            if (ok) cachedTicket = t;
                        }
                    } catch (e) {}

                    const canReuseTicket = cachedTicket
                        && cachedTicket.sha256 === sha256
                        && cachedTicket.uploadId
                        && cachedTicket.ossUrl
                        && cachedTicket.ossFields
                        && (!cachedTicket.expireAt || nowSec < (cachedTicket.expireAt - 2));

                    if (!canReuseTicket) {
                        if (status) { status.style.color = '#aaa'; status.innerText = '正在向服务器申请上传权限...'; }
                        initRes = await UGC_SERVICE.routesUploadInit({
                            routeName: name,
                            routeDesc: desc,
                            sha256,
                            sizeBytes: f.size
                        });

                        if (initRes && initRes.skip_upload) {
                            cachedTicket = null;
                        } else {
                            const uploadId = initRes && initRes.upload_id ? String(initRes.upload_id) : '';
                            const oss = initRes && initRes.oss ? initRes.oss : null;
                            if (!uploadId || !oss || !oss.url || !oss.fields) throw new Error('bad_upload_ticket');
                            cachedTicket = {
                                sha256,
                                uploadId,
                                ossUrl: String(oss.url),
                                ossFields: oss.fields,
                                expireAt: (oss && oss.expire_at) ? Number(oss.expire_at) : null
                            };
                            try { STATE.routeUploadTickets.set(sha256, cachedTicket); } catch (e) {}
                        }
                    }

                    if (initRes && initRes.skip_upload) {
                        if (status) { status.style.color = '#4caf50'; status.innerText = '已存在相同ZIP：已创建记录（复用同一对象）'; }
                    } else {
                        const uploadId = (cachedTicket && cachedTicket.uploadId) ? String(cachedTicket.uploadId) : '';
                        const ossUrl = (cachedTicket && cachedTicket.ossUrl) ? String(cachedTicket.ossUrl) : '';
                        const ossFields = (cachedTicket && cachedTicket.ossFields) ? cachedTicket.ossFields : null;
                        if (!uploadId || !ossUrl || !ossFields) throw new Error('bad_upload_ticket');

                        if (status) { status.style.color = '#aaa'; status.innerText = '正在上传到OSS...'; }

                        const parseOssXmlErr = (xml) => {
                            const text = String(xml || '');
                            const code = (text.match(/<Code>([^<]+)<\/Code>/) || [])[1] || '';
                            const msg = (text.match(/<Message>([^<]+)<\/Message>/) || [])[1] || '';
                            if (code && msg) return `${code}: ${msg}`;
                            if (code) return code;
                            if (msg) return msg;
                            return '';
                        };

                        const ossUploadOnce = (dataBuilder) => new Promise((resolve, reject) => {
                            let dataObj;
                            try { dataObj = dataBuilder(); } catch (e) { reject(e); return; }

                            const onLoad = (res) => {
                                activeUploadXhr = null;
                                const st = res && Number(res.status);
                                const ok = st >= 200 && st < 300;
                                if (ok) return resolve(true);

                                const body = String((res && res.responseText) || '');
                                const hint = parseOssXmlErr(body) || (body ? body.slice(0, 120) : '');
                                reject(new Error(`OSS上传失败(${st || 0}${hint ? `:${hint}` : ''})`));
                            };

                            const onErr = (res) => {
                                activeUploadXhr = null;
                                const hint = res ? (res.error || res.responseText) : '';
                                reject(new Error(`OSS上传失败(网络错误${hint ? `:${hint}` : ''})`));
                            };

                            try {
                                const xhr = GM_xmlhttpRequest({
                                    method: 'POST',
                                    url: String(ossUrl || ''),
                                    data: dataObj.data,
                                    headers: dataObj.headers || {},
                                    anonymous: true,
                                    timeout: 60000,
                                    onload: onLoad,
                                    ontimeout: () => onErr({ error: 'timeout' }),
                                    onerror: onErr,
                                });
                                activeUploadXhr = xhr;
                                try {
                                    if (xhr && xhr.upload) {
                                        xhr.upload.onprogress = (ev) => {
                                            if (!status) return;
                                            if (!ev || !ev.lengthComputable) return;
                                            const pct = Math.max(0, Math.min(100, Math.round((ev.loaded / ev.total) * 100)));
                                            status.style.color = '#aaa';
                                            status.innerText = `正在上传到OSS... ${pct}%`;
                                        };
                                    }
                                } catch (e) {}
                            } catch (e) {
                                onErr({ error: toReason(e) });
                            }
                        });

                        // Some Tampermonkey environments may fail to POST FormData; fallback to a manual multipart Blob.
                        const buildFormData = () => {
                            const fd = new FormData();
                            Object.keys(ossFields).forEach(k => fd.append(k, String(ossFields[k])));
                            fd.append('file', f, f.name);
                            return { data: fd, headers: {} };
                        };

                        const buildMultipartBlob = () => {
                            const boundary = `----smoss${Math.random().toString(16).slice(2)}`;
                            const safeFilename = String(f.name || 'routes.zip').replace(/["\r\n]/g, '_');
                            const parts = [];
                            Object.keys(ossFields).forEach(k => {
                                parts.push(`--${boundary}\r\n`);
                                parts.push(`Content-Disposition: form-data; name="${String(k).replace(/["\r\n]/g, '_')}"\r\n\r\n`);
                                parts.push(`${String(ossFields[k])}\r\n`);
                            });
                            parts.push(`--${boundary}\r\n`);
                            parts.push(`Content-Disposition: form-data; name="file"; filename="${safeFilename}"\r\n`);
                            parts.push(`Content-Type: application/zip\r\n\r\n`);
                            parts.push(new Blob([ab], { type: 'application/zip' }));
                            parts.push(`\r\n--${boundary}--\r\n`);
                            const blob = new Blob(parts, { type: `multipart/form-data; boundary=${boundary}` });
                            return { data: blob, headers: { 'Content-Type': blob.type } };
                        };

                        try {
                            await ossUploadOnce(buildFormData);
                        } catch (e) {
                            await ossUploadOnce(buildMultipartBlob);
                        }

                        if (status) { status.style.color = '#aaa'; status.innerText = '上传完成，正在确认...'; }
                        await UGC_SERVICE.routesUploadComplete(uploadId);
                        cachedTicket = null;
                        try { STATE.routeUploadTickets.delete(sha256); } catch (e) {}
                        if (status) { status.style.color = '#4caf50'; status.innerText = '上传成功'; }
                    }

                    // 上传成功后：切到“我的”并刷新列表（如果当前在路线模式）
                    try {
                        STATE.searchUI.route.tab = 'mine';
                        const tabs = document.getElementById('sm-route-tabs');
                        if (tabs) {
                            tabs.querySelectorAll('.sm-tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === 'mine'));
                        }
                        STATE.searchUI.route.page = 1;
                    } catch (e) {}
                    try {
                        if (typeof globalScope.__sm_route_square_refresh === 'function') globalScope.__sm_route_square_refresh();
                    } catch (e) {}

                    setTimeout(close, 350);
                } catch (e) {
                    const msg = humanizeUploadErr(toReason(e));
                    if (status) { status.style.color = '#f44336'; status.innerText = `上传失败：${msg}`; }
                } finally {
                    submitBusy = false;
                    btnSubmit.disabled = false;
                }
            });
        }
    }

    function ensureConfirmModal() {
        let overlay = document.getElementById('sm-confirm-overlay');
        if (overlay) return overlay;

        overlay = document.createElement('div');
        overlay.className = 'sm-modal-overlay';
        overlay.id = 'sm-confirm-overlay';
        overlay.style.display = 'none';
        overlay.innerHTML = `
            <div class="sm-modal" role="dialog" aria-modal="true">
                <div class="sm-modal-title" id="sm-confirm-title">确认</div>
                <div id="sm-confirm-message" style="white-space:pre-wrap;color:#ccc;font-size:12px;line-height:1.5;"></div>
                <div class="sm-modal-actions">
                    <button type="button" class="sm-modal-btn" id="sm-confirm-cancel">取消</button>
                    <button type="button" class="sm-modal-btn primary" id="sm-confirm-ok">确认</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        return overlay;
    }

    function showConfirm({ title = '确认', message = '', okText = '确认', danger = false } = {}) {
        const overlay = ensureConfirmModal();
        return new Promise((resolve) => {
            const titleEl = overlay.querySelector('#sm-confirm-title');
            const msgEl = overlay.querySelector('#sm-confirm-message');
            const btnCancel = overlay.querySelector('#sm-confirm-cancel');
            const btnOk = overlay.querySelector('#sm-confirm-ok');

            if (titleEl) titleEl.innerText = String(title || '确认');
            if (msgEl) msgEl.innerText = String(message || '');
            if (btnOk) {
                btnOk.innerText = String(okText || '确认');
                btnOk.classList.toggle('danger', !!danger);
                btnOk.style.borderColor = danger ? '#722' : '';
                btnOk.style.color = danger ? '#ff6b6b' : '';
            }

            const cleanup = () => {
                overlay.style.display = 'none';
                overlay.onclick = null;
                if (btnCancel) btnCancel.onclick = null;
                if (btnOk) btnOk.onclick = null;
                window.removeEventListener('keydown', onKeydown, true);
            };

            const done = (val) => { cleanup(); resolve(!!val); };
            const onKeydown = (e) => {
                if (!e) return;
                if (e.key === 'Escape') { e.preventDefault(); done(false); }
                if (e.key === 'Enter') { e.preventDefault(); done(true); }
            };

            overlay.onclick = (e) => { if (e.target === overlay) done(false); };
            if (btnCancel) btnCancel.onclick = () => done(false);
            if (btnOk) btnOk.onclick = () => done(true);
            window.addEventListener('keydown', onKeydown, true);

            overlay.style.display = 'flex';
        });
    }

    function keyToLabel(key) {
        const map = { switchTools: '开关组', sideMenu: '侧边栏', leftTop: '左上角按钮组', zoomControl: '缩放滑块', mobile: '移动端控件', syncMarker: '位置同步标记' };
        return map[key] || key;
    }

    function getCleanUICssClass(key) {
        return 'hide-' + key.replace(/([A-Z])/g, "-$1").toLowerCase();
    }

    function getCleanUIStoreKey(key) {
        return 'SM_UI_' + key.toUpperCase().replace(/([A-Z])/g, '_$1');
    }

    function applyCleanUIToggle(key, checked) {
        const cssClass = getCleanUICssClass(key);
        STATE.toggles.cleanUI[key] = checked;
        localStorage.setItem(getCleanUIStoreKey(key), checked);
        if (checked) document.body.classList.add(cssClass);
        else document.body.classList.remove(cssClass);
    }

    function setPauseTrackingWhenPopupOpen(checked) {
        const enabled = !!checked;
        STATE.toggles.pauseTrackingWhenPopupOpen = enabled;
        localStorage.setItem('SM_PAUSE_TRACKING_WHEN_POPUP_OPEN', enabled);

        const toggle = document.getElementById('sm-pause-tracking-popup');
        if (toggle) toggle.checked = enabled;

        const row = document.getElementById('sm-pause-tracking-popup-row');
        if (row) row.setAttribute('aria-checked', enabled ? 'true' : 'false');
    }

    function bindUIEvents(dom) {
        const $ = s => dom.querySelector(s);
        const cleanAllToggle = $('#sm-clean-all-toggle');
        const cleanDropdownToggle = $('#sm-clean-dropdown-toggle');
        const cleanDropdownBody = $('#sm-clean-dropdown-body');
        const cleanMasterRow = dom.querySelector('.sm-clean-master');
        const cleanItemToggles = Array.from(dom.querySelectorAll('input[data-toggle]'));

        const syncCleanAllToggle = () => {
            if (!cleanAllToggle) return;
            cleanAllToggle.checked = cleanItemToggles.length > 0 && cleanItemToggles.every(cb => cb.checked);
        };

        if (cleanDropdownToggle && cleanDropdownBody && cleanMasterRow) {
            const toggleCleanDropdown = () => {
                const collapsed = cleanDropdownBody.classList.toggle('is-collapsed');
                cleanDropdownToggle.classList.toggle('is-open', !collapsed);
                cleanDropdownToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
                localStorage.setItem('SM_CLEAN_UI_DROPDOWN_OPEN', collapsed ? 'false' : 'true');
            };
            cleanMasterRow.onclick = (e) => {
                if (e.target && e.target.closest('.sm-switch')) return;
                toggleCleanDropdown();
            };
        }

        cleanItemToggles.forEach(cb => {
            const key = cb.getAttribute('data-toggle');
            applyCleanUIToggle(key, STATE.toggles.cleanUI[key]);
            cb.onchange = (e) => {
                const checked = e.target.checked;
                applyCleanUIToggle(key, checked);
                syncCleanAllToggle();
            };
        });
        syncCleanAllToggle();

        if (cleanAllToggle) {
            cleanAllToggle.onchange = (e) => {
                const checked = e.target.checked;
                cleanItemToggles.forEach(cb => {
                    const key = cb.getAttribute('data-toggle');
                    cb.checked = checked;
                    applyCleanUIToggle(key, checked);
                });
                syncCleanAllToggle();
            };
        }

        $('#sm-marker-opt').checked = STATE.toggles.markerOptimization;
        $('#sm-marker-opt').onchange = (e) => {
            const checked = e.target.checked;
            localStorage.setItem('SM_MARKER_OPT', checked);
            if (confirm('更改"标记点样式"需要刷新页面生效。\n\n是否立即刷新？')) { location.reload(); }
            else { STATE.toggles.markerOptimization = checked; }
        };

        const pauseTrackingToggle = $('#sm-pause-tracking-popup');
        const pauseTrackingRow = $('#sm-pause-tracking-popup-row');
        if (pauseTrackingToggle) {
            pauseTrackingToggle.onchange = (e) => {
                setPauseTrackingWhenPopupOpen(e.target.checked);
            };
        }
        if (pauseTrackingRow && pauseTrackingToggle) {
            pauseTrackingRow.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                setPauseTrackingWhenPopupOpen(!pauseTrackingToggle.checked);
            };
            pauseTrackingRow.onkeydown = (e) => {
                if (e.key !== ' ' && e.key !== 'Enter') return;
                e.preventDefault();
                e.stopPropagation();
                setPauseTrackingWhenPopupOpen(!pauseTrackingToggle.checked);
            };
        }

        $('#sm-import-btn').onclick = () => $('#sm-file-input').click();
        $('#sm-create-route-btn').onclick = () => STATE.routeManager.createNewRoute();
        const pageZipVersion = (globalScope && globalScope.JSZip && globalScope.JSZip.version) ? globalScope.JSZip.version : '';
        setImportStatus(pageZipVersion ? `ZIP支持：JSZip ${pageZipVersion}` : 'ZIP支持：未加载（导入ZIP时自动加载）');

        $('#sm-file-input').onchange = e => {
            const files = e.target && e.target.files ? e.target.files : null;
            if (!files || files.length === 0) {
                setImportStatus('未选择文件', true);
                return;
            }
            processFiles(files).catch(err => {
                setImportStatus(`导入失败：${toReason(err)}`, true);
                alert(`导入失败：${toReason(err)}`);
            });
            e.target.value = '';
        };
        $('#sm-export-selected').onclick = () => {
            STATE.routeManager.exportSelected().catch(err => alert(`批量导出失败：${toReason(err)}`));
        };
        $('#sm-merge-selected').onclick = () => {
            STATE.routeManager.mergeSelected();
        };

        $('#sm-toggle-visible').onclick = () => {
            if (STATE.routeManager.singleVisibleMode) return;
            const routes = STATE.routeManager.routes || [];
            if (!routes.length) return;

            const selected = STATE.routeManager.selectedIds;
            let targets = (selected && selected.size) ? routes.filter(r => selected.has(r.id)) : [];
            if (!targets.length) targets = routes.slice();
            if (!targets.length) return;

            const wantVisible = targets.some(r => !r.visible);
            targets.forEach(r => {
                if (!r || r.isEditing) return;
                if (r.visible === wantVisible) return;
                r.visible = wantVisible;
                if (r.layer && STATE.mainLayerGroup) {
                    wantVisible ? STATE.mainLayerGroup.addLayer(r.layer) : STATE.mainLayerGroup.removeLayer(r.layer);
                }
            });
            renderRouteListUI();
        };

        $('#sm-single-route-toggle').onchange = (e) => {
            try {
                const enabled = !!e.target.checked;
                try { localStorage.setItem('KMP_SINGLE_ROUTE_MODE', enabled ? 'true' : 'false'); } catch (err) {}
                STATE.routeManager.applySingleVisibleMode(enabled);
                syncSingleRouteToggleUI();
            } catch (err) {
                console.error(err);
            }
        };

        const routeMarkerModeWrap = $('#sm-route-marker-display-mode');
        if (routeMarkerModeWrap) {
            routeMarkerModeWrap.querySelectorAll('[data-route-marker-mode]').forEach(button => {
                button.onclick = () => {
                    const mode = button.dataset.routeMarkerMode;
                    if (!['none', 'highlight', 'focus'].includes(mode)) return;
                    STATE.routeManager.markerDisplayMode = mode;
                    try { localStorage.setItem('KMP_ROUTE_MARKER_DISPLAY_MODE', mode); } catch (e) {}
                    syncRouteMarkerDisplayModeUI();
                    scheduleRouteMarkerDisplay('display-mode-change');
                };
            });
            syncRouteMarkerDisplayModeUI();
        }

        $('#sm-prev-route').onclick = () => {
            if (!STATE.routeManager.singleVisibleMode) return;
            STATE.routeManager.shiftVisibleRoute(-1);
        };

        $('#sm-next-route').onclick = () => {
            if (!STATE.routeManager.singleVisibleMode) return;
            STATE.routeManager.shiftVisibleRoute(1);
        };

        $('#sm-clear-route').onclick = () => {
            const routes = STATE.routeManager.routes || [];
            if (!routes.length) return;

            const selected = STATE.routeManager.selectedIds;
            let idsToRemove = (selected && selected.size)
                ? routes.filter(r => selected.has(r.id)).map(r => r.id)
                : [];
            if (!idsToRemove.length) idsToRemove = routes.map(r => r.id);
            if (!idsToRemove.length) return;

            const idSet = new Set(idsToRemove);
            const keep = [];
            (STATE.routeManager.routes || []).forEach(r => {
                if (!idSet.has(r.id)) { keep.push(r); return; }
                if (STATE.routeManager.selectedIds) STATE.routeManager.selectedIds.delete(r.id);

                if (r.isEditing) {
                    closeSpecialMarkerStyleModal(r, false);
                    r.specialMarkerGroupMode = false;
                    r.specialMarkerAddingGroupId = null;
                    r.specialMarkerSelectedGroupId = null;
                    if (typeof STATE.routeManager.disableBoxSelect === 'function') {
                        try { STATE.routeManager.disableBoxSelect(r); } catch (e) {}
                    }
                    try { STATE.mapInstance && r.editorGroup && STATE.mapInstance.removeLayer(r.editorGroup); } catch (e) {}
                }
                try { STATE.mainLayerGroup && r.layer && STATE.mainLayerGroup.removeLayer(r.layer); } catch (e) {}
            });
            STATE.routeManager.routes = keep;
            if (STATE.routeManager.selectedIds) {
                const existing = new Set(keep.map(r => r.id));
                for (const id of Array.from(STATE.routeManager.selectedIds)) {
                    if (!existing.has(id)) STATE.routeManager.selectedIds.delete(id);
                }
            }
            updateSpecialMarkerGroupSidebar(null);
            renderRouteListUI();
        };

        const bindSlider = (id, key, valId) => {
            $(id).oninput = e => { SETTINGS[key] = parseFloat(e.target.value); $(valId).innerText = SETTINGS[key]; };
            $(id).onchange = () => STATE.routeManager.redraw();
        };
        bindSlider('#rng-w', 'pathWeight', '#val-w');
        bindSlider('#rng-s', 'arrowSize', '#val-s');
        bindSlider('#rng-g', 'arrowGap', '#val-g');

        try {
            const enabled = localStorage.getItem('KMP_SINGLE_ROUTE_MODE') === 'true';
            STATE.routeManager.applySingleVisibleMode(enabled, { silent: true });
            syncSingleRouteToggleUI();
        } catch (e) {}

        const input = $('#sm-search-input');
        const results = $('#sm-search-results');
        const modeWrap = $('#sm-search-mode');
        const tagPanel = $('#sm-search-panel-tag');
        const routePanel = $('#sm-search-panel-route');
        const tagFocusToggle = $('#sm-tag-focus-toggle');

        const routeList = $('#sm-route-square-list');
        const routeTabs = $('#sm-route-tabs');
        const routePrev = $('#sm-route-page-prev');
        const routeNext = $('#sm-route-page-next');
        const routePageDisplay = $('#sm-route-page-display');
        const routePageInput = $('#sm-route-page-input');
        const routePageTotal = $('#sm-route-page-total');
        const routeSort = $('#sm-route-sort');
        const routeUploadBtn = $('#sm-route-upload-btn');

        const openUploadModal = () => {
            const ov = document.getElementById('sm-route-modal-overlay');
            if (!ov) {
                try { injectRouteUploadModal(); } catch (e) {}
            }
            const ov2 = document.getElementById('sm-route-modal-overlay');
            if (!ov2) return;
            try {
                STATE.routeUploadModalOpen = true;
                const importOv = document.getElementById('sm-drag-overlay');
                if (importOv) importOv.style.display = 'none';
            } catch (e) {}
            const viewer2 = UGC_SERVICE && typeof UGC_SERVICE.getViewer === 'function' ? UGC_SERVICE.getViewer() : null;
            const canUpload = !!(viewer2 && viewer2.userId);
            const submitBtn = ov2.querySelector('#sm-upload-submit');
            const status = ov2.querySelector('#sm-upload-status');
            if (submitBtn) submitBtn.disabled = !canUpload;
            if (!canUpload && status) {
                status.style.color = '#f44336';
                status.innerText = '未登录：无法上传路线';
            } else if (status) {
                status.style.color = '#aaa';
                status.innerText = '';
            }
            ov2.style.display = 'flex';
        };

        let routeReqSeq = 0;
        const renderRouteSquareUI = async () => {
            if (!routeList) return;

            const humanizeRoutesListErr = (raw) => {
                const s = String(raw || '');
                if (!s) return '未知错误';
                if (s.includes('login_required')) return '未登录：无法查看此列表';
                if (s.includes('upstream_down')) return '后端离线：HK 无法连接 BJ（内网互通/WireGuard 断开）';
                if (s === 'timeout' || s.includes('timeout')) return '请求超时：后端可能离线（可稍后重试）';
                if (s === 'network_error' || s.includes('network_error')) return '网络错误：无法连接 API（可稍后重试）';
                if (s.includes('routes_failed')) return 'API 返回异常（可稍后重试）';
                return s;
            };

            const viewer = UGC_SERVICE && typeof UGC_SERVICE.getViewer === 'function' ? UGC_SERVICE.getViewer() : null;
            if (routeUploadBtn) {
                const canUpload = !!(viewer && viewer.userId);
                routeUploadBtn.classList.toggle('is-disabled', !canUpload);
                routeUploadBtn.setAttribute('aria-disabled', canUpload ? 'false' : 'true');
                routeUploadBtn.title = canUpload ? '上传路线' : '未登录：无法上传路线';
            }

            const uiTab = (STATE.searchUI.route.tab || 'square');
            const apiTab = uiTab === 'fav' ? 'favorites' : (uiTab === 'mine' ? 'mine' : 'plaza');
            const q = input ? String(input.value || '').trim() : '';
            const sort = (STATE.searchUI.route.sort || 'downloads');
            const pageSize = 20;

            const total0 = Math.max(1, Number(STATE.searchUI.route.totalPages) || 1);
            const page0 = Math.min(total0, Math.max(1, Number(STATE.searchUI.route.page) || 1));
            STATE.searchUI.route.page = page0;

            if (routePageTotal) routePageTotal.innerText = String(total0);
            if (routePageDisplay) { routePageDisplay.style.display = ''; routePageDisplay.innerText = String(page0); }
            if (routePageInput) { routePageInput.style.display = 'none'; routePageInput.value = String(page0); }
            if (routePrev) routePrev.disabled = page0 <= 1;
            if (routeNext) routeNext.disabled = page0 >= total0;

            const seq = ++routeReqSeq;
            routeList.innerHTML = `<div style="padding:10px;color:#888;text-align:center;">加载中...</div>`;

            try {
                const data = await UGC_SERVICE.listRoutes({ tab: apiTab, q, sort, page: page0, pageSize });
                if (seq !== routeReqSeq) return;

                const items = Array.isArray(data && data.items) ? data.items : [];
                const totalPages = Math.max(1, Number(data && data.total_pages) || 1);
                STATE.searchUI.route.totalPages = totalPages;
                if (routePageTotal) routePageTotal.innerText = String(totalPages);

                if (page0 > totalPages) {
                    STATE.searchUI.route.page = totalPages;
                    renderRouteSquareUI();
                    return;
                }

                if (routePrev) routePrev.disabled = STATE.searchUI.route.page <= 1;
                if (routeNext) routeNext.disabled = STATE.searchUI.route.page >= totalPages;
                if (routePageDisplay) routePageDisplay.innerText = String(STATE.searchUI.route.page);
                if (routePageInput) routePageInput.value = String(STATE.searchUI.route.page);

                if (!items.length) {
                    const msg = (!viewer || !viewer.userId) && (uiTab === 'fav' || uiTab === 'mine')
                        ? '未登录：无法查看此列表'
                        : (q ? '无结果' : '暂无路线');
                    routeList.innerHTML = `<div style="padding:10px;color:#777;text-align:center;">${msg}</div>`;
                    return;
                }

                const metricSvg = {
                    downloads: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v10m0 0l4-4m-4 4l-4-4M5 19h14" /></svg>`,
                    favorites: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l3 7 7 .6-5.3 4.6 1.7 7.2L12 17.8 5.6 21.4l1.7-7.2L2 9.6 9 9z" /></svg>`,
                    likes: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-4.6-9.3-8.7C.4 8.3 2.7 5.5 6 5.5c1.8 0 3.1 1 4 2.2.9-1.2 2.2-2.2 4-2.2 3.3 0 5.6 2.8 3.3 6.8C19 16.4 12 21 12 21z" /></svg>`,
                    trash: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v7M14 11v7M9 7l1-2h4l1 2M6 7l1 14h10l1-14" /></svg>`
                };

                routeList.innerHTML = items.map(it => {
                    const id = it && (it.id ?? it.route_id ?? '');
                    const name = it && (it.route_name ?? it.name ?? '');
                    const authorName = it && (it.author_user_name ?? it.authorUserName ?? '');
                    const authorId = it && (it.author_user_id ?? it.authorUserId ?? '');
                    const d = Number(it && (it.downloads ?? it.downloads_count ?? 0)) || 0;
                    const f = Number(it && (it.favorites ?? it.favorites_count ?? 0)) || 0;
                    const l = Number(it && (it.likes ?? it.likes_count ?? 0)) || 0;
                    const desc = it && (it.route_desc ?? it.desc ?? '');

                    const favActive = !!(it && it.favorited) || apiTab === 'favorites';
                    const likeActive = !!(it && it.liked);
                    const canDelete = viewer && viewer.userId && String(viewer.userId) === String(authorId);
                    const delBtn = (uiTab === 'mine' || canDelete)
                        ? `<button class="sm-route-metric-btn danger" type="button" data-route-act="delete" title="删除">${metricSvg.trash}</button>`
                        : '';

                    const metrics = `
                        <button class="sm-route-metric-btn" type="button" data-route-act="import" title="加载该路线ZIP">${metricSvg.downloads}<span class="num" data-k="downloads">${d}</span></button>
                        <button class="sm-route-metric-btn ${favActive ? 'active' : ''}" type="button" data-route-act="favorite" title="收藏/取消收藏">${metricSvg.favorites}<span class="num" data-k="favorites">${f}</span></button>
                        <button class="sm-route-metric-btn ${likeActive ? 'active' : ''}" type="button" data-route-act="like" title="点赞/取消点赞">${metricSvg.likes}<span class="num" data-k="likes">${l}</span></button>
                        ${delBtn}
                    `;

                    return `
                        <div class="sm-route-square-item" data-route-id="${escapeHtml(String(id))}" data-route-name="${escapeHtml(String(name || ''))}" data-author-id="${escapeHtml(String(authorId || ''))}" title="${escapeHtml(String(desc || ''))}">
                            <div class="sm-route-title">${escapeHtml(String(name || ''))}</div>
                            <div class="sm-route-metrics">${metrics}</div>
                            <div class="sm-route-sub">${escapeHtml(String(authorName || ''))}</div>
                            <div class="sm-route-uploader-id">${escapeHtml(String(authorId || ''))}</div>
                        </div>
                    `;
                }).join('');
            } catch (e) {
                if (seq !== routeReqSeq) return;
                routeList.innerHTML = `<div style="padding:10px;color:#f44336;text-align:center;">加载失败：${escapeHtml(humanizeRoutesListErr(toReason(e)))}</div>`;
            }
        };

        try { globalScope.__sm_route_square_refresh = renderRouteSquareUI; } catch (e) {}

        const applySearchMode = (mode) => {
            STATE.searchUI.mode = mode === 'route' ? 'route' : 'tag';
            if (STATE.searchUI.mode !== 'tag') {
                // 避免在“路线”模式下遗留聚焦导致地图空白
                try { clearMarkerFocus(); } catch (e) {}
                try { clearHighlightPoints(); } catch (e) {}
                scheduleRouteMarkerDisplay('search-mode-route');
            }

            if (modeWrap) {
                modeWrap.querySelectorAll('.sm-seg-btn').forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.mode === STATE.searchUI.mode);
                });
            }
            if (tagPanel) tagPanel.style.display = STATE.searchUI.mode === 'tag' ? '' : 'none';
            if (routePanel) routePanel.style.display = STATE.searchUI.mode === 'route' ? '' : 'none';

            if (results) {
                const q0 = input ? String(input.value || '').trim() : '';
                if (STATE.searchUI.mode === 'tag' && !q0) {
                    results.style.display = 'block';
                    showTagIdleResults(input, results).catch(() => {});
                } else {
                    results.style.display = 'none';
                }
            }
            if (input) input.dispatchEvent(new Event('input'));
        };

        if (tagFocusToggle) {
            tagFocusToggle.checked = !!STATE.searchUI.tagFocusOnly;
            tagFocusToggle.onchange = (e) => {
                STATE.searchUI.tagFocusOnly = !!(e && e.target && e.target.checked);
                try { localStorage.setItem('SM_TAG_FOCUS_ONLY', STATE.searchUI.tagFocusOnly ? 'true' : 'false'); } catch (err) {}
                tagFocusToggle.checked = !!STATE.searchUI.tagFocusOnly;
                if (!STATE.searchUI.tagFocusOnly) {
                    try { clearMarkerFocus(); } catch (err) {}
                    // 关闭聚焦后：恢复绿色圈圈高亮（如果当前有选中）
                    try {
                        if (STATE.searchUI.tagSelection.kind === 'fp' && STATE.searchUI.tagSelection.key) {
                            const p = STATE.pointCache.get(STATE.searchUI.tagSelection.key);
                            highlightPoints(p ? [p] : []);
                        } else if (STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key) {
                            const fps2 = Array.isArray(STATE.searchUI._selectedFps) ? STATE.searchUI._selectedFps : [];
                            const pts2 = fps2.map(fp => STATE.pointCache.get(fp)).filter(Boolean);
                            highlightPoints(pts2);
                        } else {
                            clearHighlightPoints();
                        }
                    } catch (err) {}
                    return;
                }
                // 若当前已选中则直接应用（优先使用已缓存的 fp 列表；否则触发一次 input 让其重建）
                try {
                    clearHighlightPoints(); // 聚焦开启时不显示绿色圈圈
                    if (STATE.searchUI.tagSelection.kind === 'fp' && STATE.searchUI.tagSelection.key) {
                        STATE.searchUI._selectedFps = [STATE.searchUI.tagSelection.key];
                        applyMarkerFocusByFps([STATE.searchUI.tagSelection.key]);
                    } else if (STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key) {
                        const fps = Array.isArray(STATE.searchUI._selectedFps) ? STATE.searchUI._selectedFps : [];
                        if (fps.length) applyMarkerFocusByFps(fps);
                        else input && input.dispatchEvent(new Event('input'));
                    }
                } catch (err) {}
            };
        }

        if (modeWrap) {
            modeWrap.querySelectorAll('.sm-seg-btn').forEach(btn => {
                btn.addEventListener('click', () => applySearchMode(btn.dataset.mode));
            });
        }

        if (routeTabs) {
            routeTabs.querySelectorAll('.sm-tab-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    STATE.searchUI.route.tab = btn.dataset.tab || 'square';
                    STATE.searchUI.route.page = 1;
                    routeTabs.querySelectorAll('.sm-tab-btn').forEach(b => b.classList.toggle('active', b === btn));
                    renderRouteSquareUI();
                });
            });
        }

        if (routeSort) {
            routeSort.querySelectorAll('.sm-sort-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    STATE.searchUI.route.sort = btn.dataset.sort || 'downloads';
                    STATE.searchUI.route.page = 1;
                    routeSort.querySelectorAll('.sm-sort-btn').forEach(b => b.classList.toggle('active', b === btn));
                    renderRouteSquareUI();
                });
            });
        }

        if (routePrev) {
            routePrev.addEventListener('click', () => {
                STATE.searchUI.route.page = Math.max(1, (Number(STATE.searchUI.route.page) || 1) - 1);
                renderRouteSquareUI();
            });
        }
        if (routeNext) {
            routeNext.addEventListener('click', () => {
                const total = Math.max(1, Number(STATE.searchUI.route.totalPages) || 1);
                STATE.searchUI.route.page = Math.min(total, (Number(STATE.searchUI.route.page) || 1) + 1);
                renderRouteSquareUI();
            });
        }
        if (routePageDisplay && routePageInput) {
            const showEditor = () => {
                routePageDisplay.style.display = 'none';
                routePageInput.style.display = '';
                routePageInput.value = String(STATE.searchUI.route.page || 1);
                routePageInput.focus();
                try { routePageInput.select(); } catch (e) {}
            };
            const hideEditor = () => {
                routePageInput.style.display = 'none';
                routePageDisplay.style.display = '';
            };
            const commit = () => {
                const total = Math.max(1, Number(STATE.searchUI.route.totalPages) || 1);
                const p = Math.min(total, Math.max(1, Number(routePageInput.value) || 1));
                STATE.searchUI.route.page = p;
                hideEditor();
                renderRouteSquareUI();
            };

            routePageDisplay.addEventListener('click', showEditor);
            routePageInput.addEventListener('blur', hideEditor);
            routePageInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); commit(); }
                if (e.key === 'Escape') { e.preventDefault(); hideEditor(); }
            });
        }

        if (routeUploadBtn) {
            routeUploadBtn.addEventListener('click', () => openUploadModal());
        }

        let routeImportBusy = false;
        if (routeList) {
            routeList.addEventListener('click', async (ev) => {
                const itemEl = ev && ev.target && ev.target.closest ? ev.target.closest('.sm-route-square-item') : null;
                if (!itemEl) return;

                const actEl = ev && ev.target && ev.target.closest ? ev.target.closest('[data-route-act]') : null;
                if (actEl) {
                    try { ev.preventDefault(); } catch (e) {}
                    try { ev.stopPropagation(); } catch (e) {}
                }

                const routeId = itemEl.dataset ? itemEl.dataset.routeId : '';
                const routeName = itemEl.dataset ? itemEl.dataset.routeName : '';
                const authorId = itemEl.dataset ? itemEl.dataset.authorId : '';
                if (!routeId) return;

                const act = actEl && actEl.dataset ? String(actEl.dataset.routeAct || '') : '';

                const refreshList = () => {
                    try { typeof globalScope.__sm_route_square_refresh === 'function' && globalScope.__sm_route_square_refresh(); } catch (e) {}
                };

                const doImport = async () => {
                    if (routeImportBusy) return;
                    routeImportBusy = true;
                    try {
                        setImportStatus('正在获取下载链接...');
                        const url = await UGC_SERVICE.getRouteDownloadUrl(routeId);
                        if (!url) throw new Error('download_url_empty');

                        setImportStatus('正在下载ZIP...');
                        const res = await gmFetchArrayBuffer(url);
                        if (!res.ok) throw new Error(`下载失败(${res.status})`);
                        const ab = await res.arrayBuffer();
                        if (!ab || !(ab.byteLength > 0)) throw new Error('download_empty');

                        // 清空当前已加载路线，再导入
                        try { STATE.routeManager && STATE.routeManager.selectedIds && STATE.routeManager.selectedIds.clear(); } catch (e) {}
                        try { document.getElementById('sm-clear-route')?.click(); } catch (e) {}

                        const fn = ensureExt(sanitizeFileName(routeName || `route-${routeId}`, `route-${routeId}`), '.zip');
                        const file = makeFileFromArrayBuffer(ab, fn, 'application/zip');
                        await importZipRoutes(file);
                        refreshList(); // 下载数+1
                    } catch (e) {
                        setImportStatus(`导入失败：${toReason(e)}`, true);
                        alert(`导入失败：${toReason(e)}`);
                    } finally {
                        routeImportBusy = false;
                    }
                };

                if (!act) {
                    await doImport();
                    return;
                }

                if (act === 'import') {
                    await doImport();
                    return;
                }

                if (act === 'favorite' || act === 'like' || act === 'delete') {
                    const v = UGC_SERVICE && typeof UGC_SERVICE.getViewer === 'function' ? UGC_SERVICE.getViewer() : null;
                    if (!v || !v.userId) {
                        alert('未登录：无法进行此操作');
                        return;
                    }
                }

                if (act === 'favorite') {
                    if (routeImportBusy) return;
                    routeImportBusy = true;
                    try {
                        const data = await UGC_SERVICE.toggleRouteFavorite(routeId);
                        const num = actEl.querySelector('.num[data-k="favorites"]');
                        if (num && typeof data.favorites !== 'undefined') num.innerText = String(data.favorites);
                        actEl.classList.toggle('active', !!data.favorited);
                        if (!data.favorited && (STATE.searchUI.route.tab === 'fav')) refreshList();
                    } catch (e) {
                        alert(`操作失败：${toReason(e)}`);
                    } finally {
                        routeImportBusy = false;
                    }
                    return;
                }

                if (act === 'like') {
                    if (routeImportBusy) return;
                    routeImportBusy = true;
                    try {
                        const data = await UGC_SERVICE.toggleRouteLike(routeId);
                        const num = actEl.querySelector('.num[data-k="likes"]');
                        if (num && typeof data.likes !== 'undefined') num.innerText = String(data.likes);
                        actEl.classList.toggle('active', !!data.liked);
                    } catch (e) {
                        alert(`操作失败：${toReason(e)}`);
                    } finally {
                        routeImportBusy = false;
                    }
                    return;
                }

                if (act === 'delete') {
                    const v = UGC_SERVICE && typeof UGC_SERVICE.getViewer === 'function' ? UGC_SERVICE.getViewer() : null;
                    if (!v || !v.userId) return;
                    if (String(v.userId) !== String(authorId) && STATE.searchUI.route.tab !== 'mine') {
                        alert('仅上传者可删除');
                        return;
                    }

                    const ok = await showConfirm({
                        title: '删除路线',
                        message: `确认删除“${routeName || routeId}”？\n此操作不可撤销。`,
                        okText: '删除',
                        danger: true
                    });
                    if (!ok) return;

                    if (routeImportBusy) return;
                    routeImportBusy = true;
                    try {
                        await UGC_SERVICE.deleteRoute(routeId);
                        refreshList();
                    } catch (e) {
                        alert(`删除失败：${toReason(e)}`);
                    } finally {
                        routeImportBusy = false;
                    }
                    return;
                }
            });
        }

        let debounce;
        let routeDebounce;
        input.oninput = (e) => {
            if (STATE.searchUI.mode === 'route') {
                clearTimeout(routeDebounce);
                routeDebounce = setTimeout(() => {
                    STATE.searchUI.route.page = 1;
                    renderRouteSquareUI();
                }, 250);
                return;
            }

            clearTimeout(debounce);
            debounce = setTimeout(async () => {
                const q = e.target.value.trim().toLowerCase();
                if (!q) {
                    showTagIdleResults(input, results).catch(() => {});
                    return;
                }
                results.style.display = 'block';
                results.innerHTML = '<div style="padding:10px;color:#888;">搜索中...</div>';
                const points = Array.from(STATE.pointCache.values());
                const nameMatches = points.filter(p => p.name && p.name.toLowerCase().includes(q)).slice(0, 10);
                const tagGroups = {};
                try {
                    const remoteTags = await UGC_SERVICE.searchTags(q);
                    if (Array.isArray(remoteTags)) {
                        remoteTags.forEach(t => {
                            const p = STATE.pointCache.get(t.fingerprint);
                            if (p) {
                                if (!tagGroups[t.text]) tagGroups[t.text] = [];
                                if (!tagGroups[t.text].includes(p)) tagGroups[t.text].push(p);
                            }
                        });
                    }
                } catch(e){}
                // 若当前已选中某个 tag 且开启聚焦：尝试用本次搜索结果还原 fp 列表（方便开关切换时直接重放）
                try {
                    if (STATE.searchUI && STATE.searchUI.tagSelection && STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key) {
                        const pts0 = tagGroups[STATE.searchUI.tagSelection.key] || [];
                        const fps0 = Array.isArray(pts0) ? pts0.map(p => p && p.fp).filter(Boolean) : [];
                        if (fps0.length) STATE.searchUI._selectedFps = fps0;
                    }
                } catch (e) {}
                let html = '';
                Object.keys(tagGroups).forEach(tag => {
                    const isActive = (STATE.searchUI && STATE.searchUI.tagSelection && STATE.searchUI.tagSelection.kind === 'tag' && STATE.searchUI.tagSelection.key === tag);
                    html += `
                        <div class="sm-result-item group ${isActive ? 'active' : ''}" data-tag="${tag}">
                            <div><span style="color:var(--sm-gold);font-weight:bold">${tag}</span><small style="color:#888;margin-left:5px">(${tagGroups[tag].length})</small></div>
                            <button class="sm-btn" style="width:auto;padding:2px 6px;font-size:10px">定位</button>
                        </div>`;
                });
                nameMatches.forEach(p => {
                    const isActive = (STATE.searchUI && STATE.searchUI.tagSelection && STATE.searchUI.tagSelection.kind === 'fp' && STATE.searchUI.tagSelection.key === p.fp);
                    html += `<div class="sm-result-item single ${isActive ? 'active' : ''}" data-fp="${p.fp}"><div><span style="color:#fff">${p.name}</span></div><small style="color:#666;font-size:10px">单点</small></div>`;
                });
                if(!html) html = '<div style="padding:10px;color:#888;text-align:center">无结果</div>';
                results.innerHTML = html;
                bindTagSearchResultInteractions(results, input, tagGroups);
            }, 300);
        };

        applySearchMode(STATE.searchUI.mode);

        const btnMark = $('#btn-mark-smart');
        const btnUndo = $('#btn-undo-smart');
        if (btnMark && btnUndo) {
            btnMark.onclick = () => handleSmartAction(true);
            btnUndo.onclick = () => undoLastSmartMark();
        }

        const btnOpenNearest = $('#btn-open-nearest');
        const btnClosePopup = $('#btn-close-popup');
        if (btnOpenNearest) btnOpenNearest.onclick = () => openNearestUnfinishedDetailPopup();
        if (btnClosePopup) btnClosePopup.onclick = () => closeDetailPopup();

        // 空关键词时默认展示“热门（热度）”列表（含分页）
        try { showTagIdleResults(input, results).catch(() => {}); } catch (e) {}
    }

    function highlightPoints(points) {
        if (!STATE.highlightLayer) STATE.highlightLayer = L.layerGroup().addTo(STATE.mapInstance);
        STATE.highlightLayer.clearLayers();
        points.forEach(p => {
            const x = coerceJsonCoord(p.x);
            const y = coerceJsonCoord(p.y);
            if (!Number.isFinite(x) || !Number.isFinite(y)) return;
            const [lat, lng] = jsonIntToLatLng(x, y);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
            L.circleMarker({ lat, lng }, {
                radius: 12, color: '#00ff00', weight: 3, fill: false, opacity: 0.9, pane: 'kmp_highlight_pane'
            }).addTo(STATE.highlightLayer);
        });
    }

    function clearHighlightPoints() {
        if (STATE.highlightLayer) STATE.highlightLayer.clearLayers();
    }

    function getPiniaRoot() {
        try { return document.querySelector('#app')?.__vue_app__?.config?.globalProperties?.$pinia; } catch (e) { return null; }
    }

    function getPiniaStoreInstance(storeId) {
        try {
            const p = getPiniaRoot();
            return (p && p._s && typeof p._s.get === 'function') ? p._s.get(storeId) : null;
        } catch (e) {
            return null;
        }
    }

    function mkFocusKey(typeId, id) {
        return `${String(typeId)}::${String(id)}`;
    }

    function readControllerOpacity(ctrl) {
        try {
            const mk0 = ctrl && ctrl.markers && ctrl.markers[0] ? ctrl.markers[0] : null;
            const v = mk0 && mk0.options ? mk0.options.opacity : null;
            const n = Number(v);
            return Number.isFinite(n) ? n : 1;
        } catch (e) {
            return 1;
        }
    }

    function setControllerOpacity(ctrl, opacity) {
        if (!ctrl) return false;
        try {
            if (typeof ctrl.setOpacity === 'function') { ctrl.setOpacity(opacity); return true; }
        } catch (e) {}
        try {
            const mk0 = ctrl.markers && ctrl.markers[0] ? ctrl.markers[0] : null;
            if (mk0 && typeof mk0.setOpacity === 'function') { mk0.setOpacity(opacity); return true; }
        } catch (e) {}
        return false;
    }

    function ensureMapStoreActionHook() {
        if (STATE.markerFocus._mapStoreUnsub) return;
        const store = getPiniaStoreInstance('useMapStore');
        if (!store || typeof store.$onAction !== 'function') return;
        try {
            STATE.markerFocus._mapStoreUnsub = store.$onAction(({ name, after }) => {
                const needsReapply =
                    name === 'smartResetPointOpacity' ||
                    name === 'initOpacityValue' ||
                    name === 'waitForRenderComplete' ||
                    name === 'selectPointGroup' ||
                    name === 'getSideMenuData' ||
                    name === 'combinationSideMenuPointGroup';
                if (!needsReapply) return;
                after(() => {
                    if (STATE.markerFocus.active) scheduleApplyMarkerFocus('mapStoreAction:' + name);
                    scheduleRouteMarkerDisplay('mapStoreAction:' + name);
                });
            });
        } catch (e) {}
    }

    function scheduleApplyMarkerFocus(reason) {
        if (STATE.markerFocus._busy) return;
        if (STATE.markerFocus._applyTimer) return;
        STATE.markerFocus._applyTimer = setTimeout(() => {
            STATE.markerFocus._applyTimer = null;
            applyMarkerFocusNow(reason).catch(() => {});
        }, 60);
    }

    async function applyMarkerFocusNow(reason) {
        if (!STATE.markerFocus.active) return;
        if (STATE.markerFocus._busy) return;
        const store = getMapStore();
        const cache = store && store.markersCache;
        if (!(cache instanceof Map)) return;
        if (!STATE.markerFocus.keepKeys) return;
        if (STATE.markerFocus.keepKeys.size === 0 && STATE.markerFocus.owner !== 'route') return;

        STATE.markerFocus._busy = true;
        try {
            const keep = STATE.markerFocus.keepKeys;
            const restore = STATE.markerFocus.restoreOpacity;
            let changed = 0;
            let total = 0;
            let t0 = (globalScope && globalScope.performance && typeof globalScope.performance.now === 'function') ? globalScope.performance.now() : Date.now();

            for (const [typeId, inner] of cache.entries()) {
                if (!(inner instanceof Map)) continue;
                for (const [id, ctrl] of inner.entries()) {
                    const key = mkFocusKey(typeId, id);
                    const want = keep.has(key) ? 1 : 0;
                    const cur = readControllerOpacity(ctrl);
                    if (!restore.has(key)) restore.set(key, cur);
                    total++;
                    if (Math.abs(cur - want) > 1e-6) {
                        if (setControllerOpacity(ctrl, want)) changed++;
                    }
                    const now = (globalScope && globalScope.performance && typeof globalScope.performance.now === 'function') ? globalScope.performance.now() : Date.now();
                    if (now - t0 > 10) { await new Promise(r => setTimeout(r, 0)); t0 = now; }
                }
            }

            const logKey = `${reason || ''}:${keep.size}:${changed}:${total}`;
            if (STATE.markerFocus._lastLog !== logKey) {
                STATE.markerFocus._lastLog = logKey;
                try { console.info('[KMP Focus] apply', { reason, keep: keep.size, changed, total }); } catch (e) {}
            }
        } finally {
            STATE.markerFocus._busy = false;
        }
    }

    function applyMarkerFocusByKeys(keepKeys, owner = null, reason = 'applyMarkerFocusByKeys') {
        const keys = keepKeys instanceof Set ? new Set(keepKeys) : new Set(Array.from(keepKeys || []));
        if (!keys.size && owner !== 'route') {
            clearMarkerFocus(owner);
            return;
        }
        if (STATE.markerFocus._restoreTimer) {
            clearTimeout(STATE.markerFocus._restoreTimer);
            STATE.markerFocus._restoreTimer = null;
        }
        if (Array.isArray(STATE.markerFocus._pendingRestoreEntries)) {
            STATE.markerFocus._pendingRestoreEntries.forEach(([key, opacity]) => {
                if (!STATE.markerFocus.restoreOpacity.has(key)) STATE.markerFocus.restoreOpacity.set(key, opacity);
            });
            STATE.markerFocus._pendingRestoreEntries = null;
        }
        STATE.markerFocus.active = true;
        STATE.markerFocus.owner = owner;
        STATE.markerFocus.keepKeys = keys;
        ensureMapStoreActionHook();
        scheduleApplyMarkerFocus(reason);
    }

    function applyMarkerFocusByFps(fps) {
        try {
            const list = Array.isArray(fps) ? fps.map(String).filter(Boolean) : [];
            if (!list.length) return;
            const keepKeys = new Set();
            list.forEach(fp => {
                const m = STATE.fpIdIndex && typeof STATE.fpIdIndex.get === 'function' ? STATE.fpIdIndex.get(fp) : null;
                if (!(m instanceof Map)) return;
                for (const [id, typeId] of m.entries()) {
                    if (!typeId) continue;
                    keepKeys.add(mkFocusKey(typeId, id));
                }
            });

            if (!keepKeys.size) {
                // 没有 fp->(type,id) 映射：退化为只高亮（不做聚焦）
                try { console.warn('[KMP Focus] no fpIdIndex hits, skip focus'); } catch (e) {}
                try { clearMarkerFocus(); } catch (e) {}
                return;
            }

            applyMarkerFocusByKeys(keepKeys, 'tag', 'applyMarkerFocusByFps');
        } catch (e) {}
    }

    function clearMarkerFocus(owner = null) {
        if (owner && STATE.markerFocus.owner && STATE.markerFocus.owner !== owner) return;
        STATE.markerFocus.owner = null;
        if (!STATE.markerFocus.active && (!STATE.markerFocus.restoreOpacity || STATE.markerFocus.restoreOpacity.size === 0)) return;
        STATE.markerFocus.active = false;
        if (STATE.markerFocus.keepKeys) STATE.markerFocus.keepKeys.clear();
        if (STATE.markerFocus._applyTimer) { clearTimeout(STATE.markerFocus._applyTimer); STATE.markerFocus._applyTimer = null; }
        if (STATE.markerFocus._restoreTimer) { clearTimeout(STATE.markerFocus._restoreTimer); STATE.markerFocus._restoreTimer = null; }

        const restore = STATE.markerFocus.restoreOpacity;
        if (!(restore instanceof Map) || restore.size === 0) return;

        const entries = Array.from(restore.entries());
        restore.clear();
        STATE.markerFocus._pendingRestoreEntries = entries;

        const doRestore = async () => {
            if (STATE.markerFocus._busy) return;
            STATE.markerFocus._busy = true;
            try {
                const store = getMapStore();
                const cache = store && store.markersCache;
                if (!(cache instanceof Map)) return;

                let changed = 0;
                let t0 = (globalScope && globalScope.performance && typeof globalScope.performance.now === 'function') ? globalScope.performance.now() : Date.now();

                for (const [key, opacity] of entries) {
                    const sep = key.indexOf('::');
                    if (sep <= 0) continue;
                    const typeId = key.slice(0, sep);
                    const idStr = key.slice(sep + 2);
                    const inner = cache.get(typeId) || cache.get(Number(typeId));
                    if (!(inner instanceof Map)) continue;
                    const ctrl = inner.get(idStr) ?? inner.get(Number(idStr));
                    if (!ctrl) continue;
                    const cur = readControllerOpacity(ctrl);
                    if (Math.abs(cur - opacity) > 1e-6) {
                        if (setControllerOpacity(ctrl, opacity)) changed++;
                    }
                    const now = (globalScope && globalScope.performance && typeof globalScope.performance.now === 'function') ? globalScope.performance.now() : Date.now();
                    if (now - t0 > 10) { await new Promise(r => setTimeout(r, 0)); t0 = now; }
                }
                try { console.info('[KMP Focus] restore', { changed, total: entries.length }); } catch (e) {}
            } finally {
                STATE.markerFocus._busy = false;
                STATE.markerFocus._pendingRestoreEntries = null;
            }
        };

        // 延后一点，避免与站点自身的重绘/重置打架
        STATE.markerFocus._restoreTimer = setTimeout(() => {
            STATE.markerFocus._restoreTimer = null;
            doRestore().catch(() => {});
        }, 80);
    }

    
    function setupDragAndDrop() {
        if (STATE.dragDropBound) return;
        STATE.dragDropBound = true;

        const ov = document.createElement('div');
        ov.id = 'sm-drag-overlay'; ov.innerText = "释放文件以导入"; document.body.appendChild(ov);
        let c = 0;

        const resetOverlay = () => { c = 0; ov.style.display = 'none'; };
        const onDragEnter = (e) => {
            e.preventDefault();
            if (STATE.routeUploadModalOpen) return resetOverlay();
            c++; ov.style.display = 'flex'; setImportStatus('拖拽导入：释放以导入');
        };
        const onDragLeave = (e) => {
            e.preventDefault();
            if (STATE.routeUploadModalOpen) return resetOverlay();
            c--; if (c <= 0) { c = 0; ov.style.display = 'none'; }
        };
        const onDragOver = (e) => {
            e.preventDefault();
            if (STATE.routeUploadModalOpen) return resetOverlay();
        };
        const onDrop = (e) => {
            e.preventDefault();
            if (STATE.routeUploadModalOpen) return resetOverlay();
            c = 0;
            ov.style.display = 'none';
            const files = e.dataTransfer && e.dataTransfer.files ? e.dataTransfer.files : null;
            if (files && files.length) processFiles(files).catch(err => alert(`导入失败：${toReason(err)}`));
        };

        // Use capture listeners so site scripts won't easily override drag/drop handlers.
        document.addEventListener('dragenter', onDragEnter, true);
        document.addEventListener('dragleave', onDragLeave, true);
        document.addEventListener('dragover', onDragOver, true);
        document.addEventListener('drop', onDrop, true);
    }

    function handlePopupOpen(e) {
        const container = e.popup.getElement();
        if (!container) return;
        attachPopupSidecar(container);
    }

    function handlePopupClose(e) {
        const el = e.popup.getElement();
        if (!el) return;
        cleanupInjectedPopupUi(el);

        if (STATE._popupObservedEl === el) {
            if (STATE.observer) { STATE.observer.disconnect(); STATE.observer = null; }
            STATE._popupObservedEl = null;
        }
    }

    function cleanupInjectedPopupUi(container) {
        try {
            const sidecar = container.querySelector('#kmp-sidecar');
            if (sidecar) { sidecar.style.opacity = '0'; sidecar.remove(); }
        } catch (e) {}
        try {
            const bar = container.querySelector('#kmp-bottom-bar');
            if (bar) bar.remove();
        } catch (e) {}
    }

    function attachPopupSidecar(container) {
        if (!container) return;
        if (container.classList && container.classList.contains('popup-point-type-name')) return;

        // 已绑定到同一个 popup：只做“确保注入”，避免反复重建 observer
        if (STATE._popupObservedEl === container && STATE.observer) {
            injectSidecar(container);
            return;
        }

        if (STATE.observer) { try { STATE.observer.disconnect(); } catch (e) {} STATE.observer = null; }
        STATE._popupObservedEl = container;

        scheduleAutoCalibrate('popupopen');
        injectSidecar(container);

        STATE.observer = new MutationObserver(() => {
            resourceProbeCount('popup.observer');
            // Vue 可能会重绘/替换 popup 内部 DOM（inner 会短暂消失）
            const inner = container.querySelector('.mc-popup-inner');
            if (!inner) {
                cleanupInjectedPopupUi(container);
                return;
            }
            injectSidecar(container);
        });
        STATE.observer.observe(container, { childList: true, subtree: true });
    }

    function setupPopupDomWatcher() {
        if (STATE.popupDomObserver) return;

        const scheduleSync = () => {
            if (STATE._popupSyncScheduled) return;
            STATE._popupSyncScheduled = true;
            setTimeout(() => {
                resourceProbeCount('popup_dom.sync');
                STATE._popupSyncScheduled = false;
                try { syncPopupFromDom(); } catch (e) {}
            }, 0);
        };

        const start = () => {
            if (STATE.popupDomObserver) return;
            try {
                STATE.popupDomObserver = new MutationObserver(scheduleSync);
                STATE.popupDomObserver.observe(document.body, { childList: true, subtree: true });
            } catch (e) {}
            scheduleSync();
        };

        if (document.body) start();
        else {
            const mo = new MutationObserver(() => {
                if (!document.body) return;
                try { mo.disconnect(); } catch (e) {}
                start();
            });
            try { mo.observe(document.documentElement, { childList: true, subtree: true }); } catch (e) {}
        }
    }

    function findActivePointPopup() {
        try {
            const list = Array.from(document.querySelectorAll('.leaflet-popup.mc-leaflet-popup'));
            if (!list.length) return null;
            const visible = list.filter(p => {
                try {
                    if (!p.isConnected) return false;
                    const s = getComputedStyle(p);
                    if (s.display === 'none' || s.visibility === 'hidden') return false;
                    const r = p.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                } catch (e) {
                    return false;
                }
            });
            return visible[visible.length - 1] || list[list.length - 1] || null;
        } catch (e) {
            return null;
        }
    }

    function syncPopupFromDom() {
        const popup = findActivePointPopup();
        const prev = STATE._activePopupEl;
        if (!popup) {
            if (prev && prev.isConnected) cleanupInjectedPopupUi(prev);
            STATE._activePopupEl = null;
            if (STATE._popupObservedEl) {
                if (STATE.observer) { try { STATE.observer.disconnect(); } catch (e) {} STATE.observer = null; }
                STATE._popupObservedEl = null;
            }
            return;
        }

        // 如果 active popup 变了：切换 observer 目标
        if (prev !== popup) {
            try { if (prev && prev.isConnected) cleanupInjectedPopupUi(prev); } catch (e) {}
            STATE._activePopupEl = popup;
            attachPopupSidecar(popup);
            return;
        }

        // 同一个 popup：确保 sidecar 存在（处理 popupopen 事件未触发的情况）
        attachPopupSidecar(popup);
    }

    function stopPropagationFor(el, events) {
        if (!el) return;
        events.forEach(evt => el.addEventListener(evt, e => e.stopPropagation()));
    }

    function injectSidecar(container) {
        if (container.querySelector('#kmp-sidecar')) return;
        if (!container.querySelector('.mc-popup-inner')) return;

        const sidecar = document.createElement('div');
        sidecar.id = 'kmp-sidecar';
        sidecar.innerHTML = `<div class="kmp-header">呜呜标签</div><div class="kmp-body" style="color:#888;text-align:center;padding-top:40px;">Wait...</div>`;
        container.appendChild(sidecar);

        // 底部“热门”栏：不要捕获旧 sidecar 引用（Vue 重绘后 sidecar 会被替换导致点击失效）
        let bar = container.querySelector('#kmp-bottom-bar');
        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'kmp-bottom-bar';
            container.appendChild(bar);
        }
        if (!bar.querySelector('#kmp-bottom-hot-container')) {
            bar.innerHTML = `
                <div style="font-size:10px;color:#dcb268;margin-right:8px;white-space:nowrap;font-weight:bold">🔥 热门:</div>
                <div id="kmp-bottom-hot-container" style="flex:1; overflow:hidden;"></div>
            `;
        }
        const hotContainer = bar.querySelector('#kmp-bottom-hot-container');
        if (hotContainer) {
            renderHotTagsCarousel(hotContainer, (e, text) => {
                e.stopPropagation();
                const sidecarNow = container.querySelector('#kmp-sidecar') || document.getElementById('kmp-sidecar');
                const btnAdd = sidecarNow ? sidecarNow.querySelector('#btn-add-mode') : null;
                if (btnAdd) btnAdd.click();
                setTimeout(() => {
                    const input = sidecarNow ? sidecarNow.querySelector('input.kmp-input') : null;
                    if (input) { input.value = text; input.focus(); }
                }, 50);
            });
        }
        stopPropagationFor(bar, ['click', 'mousedown', 'touchstart', 'wheel']);

        if (STATE.currentDetail) {
            renderSidecar(sidecar, STATE.currentDetail);
        }

        stopPropagationFor(sidecar, ['click', 'mousedown', 'wheel', 'touchstart']);
    }

    function bindSidecarPagination(dom, fp, data, currentPage) {
        const btnPrev = dom.querySelector('#btn-prev');
        const btnNext = dom.querySelector('#btn-next');
        if (btnPrev) btnPrev.onclick = (e) => { e.stopPropagation(); STATE.pageState.set(fp, currentPage - 1); renderSidecar(dom, data); };
        if (btnNext) btnNext.onclick = (e) => { e.stopPropagation(); STATE.pageState.set(fp, currentPage + 1); renderSidecar(dom, data); };
    }

    function bindSidecarVoteButtons(dom, fp, data) {
        const canInteract = !!UGC_SERVICE.getViewer()?.userId;
        dom.querySelectorAll('.kmp-icon-btn').forEach(btn => {
            if (!canInteract) btn.disabled = true;
            btn.onclick = async (e) => {
                e.stopPropagation();
                if (!UGC_SERVICE.getViewer()?.userId) return;
                const act = btn.dataset.act;
                if (act === 'delete') await UGC_SERVICE.deleteTag(fp, btn.dataset.tag);
                else await UGC_SERVICE.voteTag(fp, btn.dataset.tag, act === 'up' ? 1 : -1);
                renderSidecar(dom, data);
            };
        });
    }

    function bindSidecarAddTag(dom, fp, data) {
        const btnAdd = dom.querySelector('#btn-add-mode');
        const inputArea = dom.querySelector('#kmp-input-area');
        if (!btnAdd || !inputArea) return;

        const canInteract = !!UGC_SERVICE.getViewer()?.userId;
        if (!canInteract) {
            btnAdd.disabled = true;
            btnAdd.style.opacity = '0.5';
            btnAdd.title = '登录后可添加标签';
        }
        btnAdd.onclick = (e) => {
            e.stopPropagation();
            if (!UGC_SERVICE.getViewer()?.userId) return;
            inputArea.innerHTML = `<input type="text" class="kmp-input" placeholder="输入标签名..." autoFocus>`;
            const input = inputArea.querySelector('input');
            if (!input) return;
            input.focus();
            const submit = async () => {
                const val = input.value.trim();
                if (val) {
                    input.disabled = true;
                    input.style.opacity = '0.5';
                    await UGC_SERVICE.addTag(fp, val);
                }
                renderSidecar(dom, data);
            };
            input.onkeydown = (ev) => { if (ev.key === 'Enter') { ev.stopPropagation(); submit(); } };
            input.onclick = (ev) => ev.stopPropagation();
        };
    }

    async function renderSidecar(dom, data) {
        if (!dom || !data) return;

        const fp = generateGlobalFP(data.x || data.xposition, data.y || data.yposition, data.mapLevel || data.level);
        if (!fp) { dom.innerHTML = `<div class="kmp-body">坐标数据异常</div>`; return; }

        const officialContent = dom.parentElement.querySelector('.mc-popup-inner');
        if (officialContent) {
            const h = officialContent.getBoundingClientRect().height;
            if (h > 150) dom.style.height = `${h}px`;
        }

        dom.innerHTML = `
            <div class="kmp-header">
                <span>${data.name || '未知'}</span>
                <span style="font-size:10px;background:#2196f3;padding:2px 4px;border-radius:2px;color:#fff">Cloud</span>
            </div>
            <div class="kmp-body" style="display:flex;flex-direction:column;height:100%;">
                <div style="flex:1;display:flex;align-items:center;justify-content:center;color:#666">
                    <span class="kmp-loading-spinner">↻</span> 加载社区数据...
                </div>
            </div>
        `;

        const ugcData = await UGC_SERVICE.get(fp);
        const viewer = UGC_SERVICE.getViewer();
        const viewerId = viewer?.userId ? String(viewer.userId) : null;
        const canInteract = !!viewerId;

        const ITEMS_PER_PAGE = 10;
        let currentPage = STATE.pageState.get(fp) || 0;
        const totalPages = Math.ceil(ugcData.tags.length / ITEMS_PER_PAGE) || 1;
        if (currentPage >= totalPages) currentPage = totalPages - 1;
        if (currentPage < 0) currentPage = 0;

        const visibleTags = ugcData.tags.slice(currentPage * ITEMS_PER_PAGE, (currentPage + 1) * ITEMS_PER_PAGE);

        let listHtml = '';
        if (visibleTags.length === 0) {
            listHtml = `<div style="text-align:center;color:#666;padding:20px;font-size:12px;display:flex;flex-direction:column;justify-content:center;height:100%"><span>暂无标签</span><span style="font-size:10px">快来抢沙发</span></div>`;
        } else {
            listHtml = visibleTags.map(tag => {
                const upClass = tag.myVote === 1 ? 'active' : '';
                const isMine = viewerId && tag.authorUserId && String(tag.authorUserId) === viewerId;
                const downAct = isMine ? 'delete' : 'down';
                const downClass = isMine ? 'active' : (tag.myVote === -1 ? 'active' : '');
                const scoreColor = tag.score > 0 ? '#4caf50' : (tag.score < 0 ? '#f44336' : '#888');
                const safeText = escapeHtml(tag.text);
                const authorName = tag.authorUserName ? escapeHtml(tag.authorUserName) : '';
                const authorLine = authorName ? `by ${authorName}` : '';
                return `
                <div class="kmp-tag-row">
                    <div class="kmp-tag-text" title="${safeText}">
                        <div class="kmp-tag-title">${safeText}</div>
                        <div class="kmp-tag-author">${authorLine}</div>
                    </div>
                    <div class="kmp-tag-acts">
                        <button class="kmp-icon-btn ${downClass}" data-act="${downAct}" data-tag="${safeText}" ${canInteract ? '' : 'disabled'}>${isMine ? '删' : '👎'}</button>
                        <span style="color:${scoreColor};width:20px;text-align:center;font-size:11px">${tag.score}</span>
                        <button class="kmp-icon-btn ${upClass}" data-act="up" data-tag="${safeText}" ${canInteract ? '' : 'disabled'}>👍</button>
                    </div>
                </div>`;
            }).join('');
        }

        dom.querySelector('.kmp-body').innerHTML = `
            <div style="flex:1; overflow-y:auto; padding-bottom:5px;">${listHtml}</div>
            <div style="border-top:1px solid #333; padding-top:8px; margin-top:auto;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; ${totalPages<=1 ? 'display:none!important':''}">
                    <button class="kmp-page-btn" id="btn-prev" ${currentPage===0?'disabled':''}>&lt;</button>
                    <span style="font-size:10px;color:#666">${currentPage+1} / ${totalPages}</span>
                    <button class="kmp-page-btn" id="btn-next" ${currentPage>=totalPages-1?'disabled':''}>&gt;</button>
                </div>
                <div id="kmp-input-area">
                    <button id="btn-add-mode" class="kmp-btn-full" ${canInteract ? '' : 'disabled'}>${canInteract ? '添加新标签' : '登录后可添加/投票'}</button>
                </div>
            </div>
        `;

        bindSidecarPagination(dom, fp, data, currentPage);
        bindSidecarVoteButtons(dom, fp, data);
        bindSidecarAddTag(dom, fp, data);
    }


    hookNetwork();
    installMapControlApi();
    interceptMap();
    setupPopupDomWatcher();
    // hotfix isolate: temporarily disable AKI auth sync to avoid impacting map boot
    // try {
    //     syncAkiAuthToPython();
    //     setInterval(syncAkiAuthToPython, 15000);
    // } catch (e) {}

})();

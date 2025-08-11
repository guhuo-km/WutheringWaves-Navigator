#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立地图窗口
专门用于显示地图，支持在线和本地地图
"""

import sys
import os
import json
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from PySide6.QtCore import QUrl, Slot, QTimer, Qt, QObject, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebChannel import QWebChannel

# 导入覆盖层管理器
try:
    from transparent_overlay import OverlayManager
    OVERLAY_AVAILABLE = True
except ImportError as e:
    print(f"透明覆盖层模块导入失败: {e}")
    OVERLAY_AVAILABLE = False

# 地图URL配置
MAP_URLS = {
    "官方地图": "https://www.kurobbs.com/mc/map",
    "光环助手": "https://www.ghzs666.com/wutheringwaves-map#/?map=default"
}

# qwebchannel.js 内容（从main_app.py复制）
QWEBCHANNEL_JS_CONTENT = """
(function(exports) {
    "use strict";
    var QWebChannelMessageTypes = {
        signal: 1,
        propertyUpdate: 2,
        init: 3,
        idle: 4,
        debug: 5,
        invokeMethod: 6,
        connectToSignal: 7,
        disconnectFromSignal: 8,
        setProperty: 9,
        response: 10
    };
    var QWebChannel = function(transport, initCallback) {
        if (typeof transport !== "object" || typeof transport.send !== "function") {
            console.error("The QWebChannel transport object is missing a send function.");
            return;
        }
        this.transport = transport;
        this.send = function(data) { this.transport.send(JSON.stringify(data)); };
        this.messages = [];
        this.isReady = false;
        var that = this;
        this.transport.onmessage = function(message) {
            var data = JSON.parse(message.data);
            var type = data.type;
            switch (type) {
                case QWebChannelMessageTypes.signal: that._handleSignal(data); break;
                case QWebChannelMessageTypes.response: that._handleResponse(data); break;
                case QWebChannelMessageTypes.propertyUpdate: that._handlePropertyUpdate(data); break;
                default: console.error("invalid message received:", message.data); break;
            }
        };
        this.execCallbacks = {};
        this.execId = 0;
        this.objects = {};
        this.send({ type: QWebChannelMessageTypes.init });
        if (initCallback) {
            this.exec({ type: QWebChannelMessageTypes.init }, function(data) {
                for (var objectName in data) {
                    var object = new QObject(objectName, data[objectName], that);
                    that.objects[objectName] = object;
                    if (that.objects.hasOwnProperty(objectName)) {
                        that[objectName] = object;
                    }
                }
                that.isReady = true;
                if (initCallback) {
                    initCallback(that);
                }
            });
        }
    };
    QWebChannel.prototype.exec = function(data, callback) {
        if (!this.transport) {
            console.error("Cannot exec message: No transport selected!");
            return;
        }
        var execId = ++this.execId;
        this.execCallbacks[execId] = callback;
        data.id = execId;
        this.send(data);
    };
    QWebChannel.prototype._handleSignal = function(message) {
        var object = this.objects[message.object];
        if (object) {
            object.signalEmitted(message.signal, message.args);
        }
    };
    QWebChannel.prototype._handleResponse = function(message) {
        if (!message.id || !this.execCallbacks[message.id]) {
            console.error("Invalid response message received: ", message);
            return;
        }
        this.execCallbacks[message.id](message.data);
        delete this.execCallbacks[message.id];
    };
    QWebChannel.prototype._handlePropertyUpdate = function(message) {
        for (var i in message.data) {
            var data = message.data[i];
            var object = this.objects[data.object];
            if (object) {
                object.propertyUpdate(data.signals, data.properties);
            }
        }
    };
    var QObject = function(name, data, webChannel) {
        this.__id__ = name;
        this.webChannel = webChannel;
        this.__objectSignals__ = {};
        this.__propertyCache__ = {};
        var that = this;
        for (var i in data.methods) {
            var method = data.methods[i];
            that[method[0]] = (function(methodData) {
                return function() {
                    var args = [];
                    for (var i = 0; i < arguments.length; ++i) {
                        args.push(arguments[i]);
                    }
                    var Ctor = methodData[1];
                    var cb;
                    if (args.length > 0 && typeof args[args.length - 1] === "function") {
                        if (Ctor === "QJSValue" || Ctor === "QVariant") {
                            var newArgs = [];
                            for (var i = 0; i < args.length-1; ++i) {
                                newArgs.push(args[i]);
                            }
                            args = newArgs;
                        }
                        cb = args.pop();
                    }
                    that.webChannel.exec({
                        type: QWebChannelMessageTypes.invokeMethod,
                        object: that.__id__,
                        method: methodData[0],
                        args: args
                    }, cb);
                };
            })(method);
        }
        for (var i in data.properties) {
            var property = data.properties[i];
            this.__propertyCache__[property[0]] = property[1];
            this.propertyUpdate([property[0]], [property[1]]);
        }
        for (var i in data.signals) {
            var signal = data.signals[i];
            if (that[signal[0]]) {
                console.error("Cannot connect to signal " + signal[0] + ", because it already exists in this QObject.");
                continue;
            }
            that[signal[0]] = (function(signalData) {
                return {
                    connect: function(callback) {
                        if (typeof callback !== "function") {
                            console.error("Cannot connect to signal " + signalData[0] + ": callback is not a function.");
                            return;
                        }
                        var id = that.webChannel.exec({
                            type: QWebChannelMessageTypes.connectToSignal,
                            object: that.__id__,
                            signal: signalData[0]
                        }, function(res) {
                            if (res) {
                                that.__objectSignals__[signalData[0]] = that.__objectSignals__[signalData[0]] || [];
                                that.__objectSignals__[signalData[0]].push(callback);
                            } else {
                                console.error("Cannot connect to signal " + signalData[0] + ": already connected.");
                            }
                        });
                    },
                    disconnect: function(callback) {
                        if (typeof callback !== "function") {
                            console.error("Cannot disconnect from signal " + signalData[0] + ": callback is not a function.");
                            return;
                        }
                        var id = that.webChannel.exec({
                            type: QWebChannelMessageTypes.disconnectFromSignal,
                            object: that.__id__,
                            signal: signalData[0]
                        }, function(res) {
                            if (res) {
                                var i = that.__objectSignals__[signalData[0]].indexOf(callback);
                                if (i !== -1) {
                                    that.__objectSignals__[signalData[0]].splice(i, 1);
                                }
                            } else {
                                console.error("Cannot disconnect from signal " + signalData[0] + ": was not connected.");
                            }
                        });
                    }
                };
            })(signal);
        }
    };
    QObject.prototype.propertyUpdate = function(signals, propertyMap) {
        for (var propertyName in propertyMap) {
            this.__propertyCache__[propertyName] = propertyMap[propertyName];
        }
        for (var i in signals) {
            var signalName = signals[i];
            var signal = this[signalName + "Changed"];
            if (signal) {
                signal.signalEmitted([this.__propertyCache__[signalName]]);
            }
        }
    };
    QObject.prototype.signalEmitted = function(signalName, signalArgs) {
        var signal = this.__objectSignals__[signalName];
        if (signal) {
            signal.forEach(function(callback) {
                callback.apply(callback, signalArgs);
            });
        }
    };
    exports.QWebChannel = QWebChannel;
})((function() {
    return this;
}()));
"""

# 混合拦截器JS代码（从main_app.py复制）
JS_HYBRID_INTERCEPTOR = """
(function() {
    // 如果已捕获，直接返回成功信号
    if (window.discoveredMap && typeof window.discoveredMap.panTo === 'function') {
        return true;
    }

    // --- A计划: 构造函数拦截 (巡航导弹) ---
    if (typeof L === 'object' && L.Map && L.Map.prototype.initialize && !L.Map.prototype.initialize._isPatched) {
        console.log("部署A计划: 拦截构造函数...");
        const originalInitialize = L.Map.prototype.initialize;
        L.Map.prototype.initialize = function(...args) {
            console.log("%cA计划命中！地图实例在诞生瞬间被捕获！", 'color: #00ff00; font-size: 14px; font-weight: bold;');
            window.discoveredMap = this;
            return originalInitialize.apply(this, args);
        };
        L.Map.prototype.initialize._isPatched = true;
    }

    // --- B计划: 交互函数拦截 (地雷阵) ---
    if (typeof L === 'object' && L.Map && L.Map.prototype) {
        let deployedB = false;
        const functionsToPatch = ['setView', 'panTo', 'flyTo', 'fitBounds', 'scrollWheelZoom', 'touchZoom'];
        for (const funcName of functionsToPatch) {
            if (L.Map.prototype[funcName] && !L.Map.prototype[funcName]._isPatchedB) {
                if (!deployedB) console.log("部署B计划: 在交互函数上布设地雷阵...");
                deployedB = true;

                const originalFunction = L.Map.prototype[funcName];
                L.Map.prototype[funcName] = function(...args) {
                    if (!window.discoveredMap) {
                         console.log(`%cB计划命中！通过 '${funcName}' 捕获地图实例！`, 'color: #FFA500; font-size: 14px; font-weight: bold;');
                         window.discoveredMap = this;
                    }
                    return originalFunction.apply(this, args);
                };
                L.Map.prototype[funcName]._isPatchedB = true;
            }
        }
    }
    
    return false; // 部署脚本本身不代表成功，需等待触发
})();
"""


class MapBackend(QObject):
    """地图后端通信类"""
    statusUpdated = Signal(float, float, int)

    def __init__(self, parent=None):
        super().__init__(parent)

    @Slot(float, float, int)
    def updateStatus(self, lat, lng, zoom):
        self.statusUpdated.emit(lat, lng, zoom)


class MapWindow(QWidget):
    """独立的地图显示窗口"""
    
    # 信号定义
    map_status_updated = Signal(float, float, int)  # lat, lng, zoom
    map_ready = Signal()
    map_error = Signal(str)
    coordinates_jumped = Signal(float, float)  # 坐标跳转完成
    
    def __init__(self, server_manager=None, parent=None):
        super().__init__(parent)
        
        self.server_manager = server_manager
        self.current_map_mode = "online"  # online 或 local
        self.current_map_provider = "官方地图"
        self.current_local_map = None
        self.current_lat = 0.0
        self.current_lng = 0.0
        self.current_zoom = 1
        
        # 设置窗口属性
        self.setWindowTitle("鸣潮地图导航 - 地图视窗")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建WebProfile用于保持登录状态
        self.setup_web_profile()
        
        # 设置UI
        self.setup_ui()
        
        # 设置Web通信
        self.setup_web_channel()
        
        # 覆盖层管理器
        self.overlay_manager = None
        if OVERLAY_AVAILABLE:
            self.setup_overlay()
        
        # 定时器用于检查地图捕获状态
        self.map_capture_timer = QTimer()
        self.map_capture_timer.timeout.connect(self.check_map_capture)
        
        print("地图窗口初始化完成")
    
    def setup_web_profile(self):
        """设置WebProfile用于保持登录状态"""
        try:
            import os
            script_dir = os.path.dirname(os.path.abspath(__file__))
            profile_path = os.path.join(script_dir, "web_profile")
            
            # 确保目录存在
            os.makedirs(profile_path, exist_ok=True)
            
            # 创建持久化的WebProfile
            self.web_profile = QWebEngineProfile("MapProfile", self)
            self.web_profile.setPersistentStoragePath(profile_path)
            self.web_profile.setCachePath(os.path.join(profile_path, "cache"))
            
            print(f"WebProfile设置完成: {profile_path}")
            
        except Exception as e:
            print(f"WebProfile设置失败: {e}")
            self.web_profile = QWebEngineProfile.defaultProfile()
    
    def setup_ui(self):
        """设置用户界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 顶部工具栏（简化版）
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(5, 5, 5, 5)
        
        # 地图模式标签
        self.mode_label = QLabel("在线地图 - 官方地图")
        self.mode_label.setStyleSheet("""
            QLabel {
                background-color: #0078d7;
                color: white;
                padding: 5px 10px;
                border-radius: 3px;
                font-weight: bold;
            }
        """)
        toolbar_layout.addWidget(self.mode_label)
        
        # 状态标签
        self.status_label = QLabel("地图加载中...")
        self.status_label.setStyleSheet("color: #666; font-size: 12px;")
        toolbar_layout.addWidget(self.status_label)
        
        toolbar_layout.addStretch()
        
        # 刷新按钮
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.setToolTip("重新加载地图")
        self.refresh_btn.clicked.connect(self.refresh_map)
        toolbar_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(toolbar_layout)
        
        # 地图WebView
        self.web_view = QWebEngineView()
        
        # 使用自定义的WebProfile
        web_page = QWebEnginePage(self.web_profile, self)
        self.web_view.setPage(web_page)
        
        layout.addWidget(self.web_view)
        
        # 连接页面加载信号
        self.web_view.loadFinished.connect(self.on_page_load_finished)
    
    def setup_web_channel(self):
        """设置Web通信通道"""
        try:
            # 创建后端对象
            self.backend = MapBackend(self)
            self.backend.statusUpdated.connect(self.on_map_status_updated)
            
            # 设置WebChannel
            self.channel = QWebChannel()
            self.web_view.page().setWebChannel(self.channel)
            self.channel.registerObject("backend", self.backend)
            
            print("WebChannel设置完成")
            
        except Exception as e:
            print(f"WebChannel设置失败: {e}")
            self.map_error.emit(f"WebChannel设置失败: {e}")
    
    def setup_overlay(self):
        """设置透明覆盖层"""
        try:
            self.overlay_manager = OverlayManager(self.web_view)
            print("透明覆盖层设置完成")
        except Exception as e:
            print(f"透明覆盖层设置失败: {e}")
    
    def load_online_map(self, provider="官方地图"):
        """加载在线地图"""
        try:
            self.current_map_mode = "online"
            self.current_map_provider = provider
            
            if provider in MAP_URLS:
                url = MAP_URLS[provider]
                self.web_view.setUrl(QUrl(url))
                self.mode_label.setText(f"在线地图 - {provider}")
                self.status_label.setText("正在加载在线地图...")
                print(f"加载在线地图: {provider} - {url}")
            else:
                raise ValueError(f"未知的地图提供商: {provider}")
                
        except Exception as e:
            error_msg = f"加载在线地图失败: {e}"
            print(error_msg)
            self.map_error.emit(error_msg)
    
    def load_local_map(self, map_name):
        """加载本地地图"""
        try:
            self.current_map_mode = "local"
            self.current_local_map = map_name
            
            # 构建本地地图URL
            if self.server_manager and self.server_manager.is_running():
                local_url = f"http://localhost:8000/index.html?map={map_name}"
                self.web_view.setUrl(QUrl(local_url))
                self.mode_label.setText(f"本地地图 - {map_name}")
                self.status_label.setText("正在加载本地地图...")
                print(f"加载本地地图: {map_name}")
            else:
                raise ValueError("本地服务器未运行")
                
        except Exception as e:
            error_msg = f"加载本地地图失败: {e}"
            print(error_msg)
            self.map_error.emit(error_msg)
    
    def refresh_map(self):
        """刷新地图"""
        self.status_label.setText("正在刷新地图...")
        self.web_view.reload()
    
    def on_page_load_finished(self, success):
        """页面加载完成"""
        if success:
            self.status_label.setText("地图加载完成")
            self.inject_webchannel_script()
            self.inject_map_interceptor()
            self.start_map_capture_check()
            self.map_ready.emit()
        else:
            self.status_label.setText("地图加载失败")
            self.map_error.emit("页面加载失败")
    
    def inject_webchannel_script(self):
        """注入WebChannel脚本"""
        try:
            # 注入qwebchannel.js
            self.web_view.page().runJavaScript(QWEBCHANNEL_JS_CONTENT)
            
            # 设置WebChannel通信
            webchannel_setup = """
            if (typeof QWebChannel !== 'undefined') {
                new QWebChannel(qt.webChannelTransport, function(channel) {
                    window.backend = channel.objects.backend;
                    console.log('WebChannel通信已建立');
                });
            }
            """
            self.web_view.page().runJavaScript(webchannel_setup)
            
        except Exception as e:
            print(f"注入WebChannel脚本失败: {e}")
    
    def inject_map_interceptor(self):
        """注入地图拦截器"""
        try:
            self.web_view.page().runJavaScript(JS_HYBRID_INTERCEPTOR)
        except Exception as e:
            print(f"注入地图拦截器失败: {e}")
    
    def start_map_capture_check(self):
        """开始检查地图捕获状态"""
        self.map_capture_timer.start(1000)  # 每秒检查一次
    
    def check_map_capture(self):
        """检查地图是否已被捕获"""
        check_script = """
        (function() {
            if (window.discoveredMap && typeof window.discoveredMap.panTo === 'function') {
                return true;
            }
            return false;
        })();
        """
        
        def on_capture_result(result):
            if result:
                self.status_label.setText("地图已就绪 ✓")
                self.map_capture_timer.stop()
                print("地图实例已捕获")
        
        try:
            self.web_view.page().runJavaScript(check_script, on_capture_result)
        except Exception as e:
            print(f"检查地图捕获状态失败: {e}")
    
    def jump_to_coordinates(self, lat, lng, zoom=None):
        """跳转到指定坐标"""
        try:
            zoom_str = f", {zoom}" if zoom is not None else ""
            
            jump_script = f"""
            (function() {{
                if (window.discoveredMap && typeof window.discoveredMap.panTo === 'function') {{
                    window.discoveredMap.setView([{lat}, {lng}]{zoom_str});
                    console.log('跳转到坐标: ({lat}, {lng})');
                    return true;
                }}
                return false;
            }})();
            """
            
            def on_jump_result(result):
                if result:
                    self.coordinates_jumped.emit(lat, lng)
                    self.status_label.setText(f"已跳转到: ({lat:.6f}, {lng:.6f})")
                    print(f"坐标跳转成功: ({lat}, {lng})")
                else:
                    self.map_error.emit("地图实例未就绪，无法跳转")
            
            self.web_view.page().runJavaScript(jump_script, on_jump_result)
            
        except Exception as e:
            error_msg = f"坐标跳转失败: {e}"
            print(error_msg)
            self.map_error.emit(error_msg)
    
    def pan_by(self, x, y):
        """平移地图"""
        try:
            pan_script = f"""
            (function() {{
                if (window.discoveredMap && typeof window.discoveredMap.panBy === 'function') {{
                    window.discoveredMap.panBy([{x}, {y}]);
                    return true;
                }}
                return false;
            }})();
            """
            self.web_view.page().runJavaScript(pan_script)
        except Exception as e:
            print(f"地图平移失败: {e}")
    
    def zoom_in(self):
        """放大地图"""
        try:
            zoom_script = """
            (function() {
                if (window.discoveredMap && typeof window.discoveredMap.zoomIn === 'function') {
                    window.discoveredMap.zoomIn();
                    return true;
                }
                return false;
            })();
            """
            self.web_view.page().runJavaScript(zoom_script)
        except Exception as e:
            print(f"地图放大失败: {e}")
    
    def zoom_out(self):
        """缩小地图"""
        try:
            zoom_script = """
            (function() {
                if (window.discoveredMap && typeof window.discoveredMap.zoomOut === 'function') {
                    window.discoveredMap.zoomOut();
                    return true;
                }
                return false;
            })();
            """
            self.web_view.page().runJavaScript(zoom_script)
        except Exception as e:
            print(f"地图缩小失败: {e}")
    
    @Slot(float, float, int)
    def on_map_status_updated(self, lat, lng, zoom):
        """地图状态更新"""
        self.current_lat = lat
        self.current_lng = lng
        self.current_zoom = zoom
        self.map_status_updated.emit(lat, lng, zoom)
    
    def set_overlay_visible(self, visible):
        """设置覆盖层可见性"""
        if self.overlay_manager:
            if visible:
                self.overlay_manager.show_overlay()
            else:
                self.overlay_manager.hide_overlay()
    
    def set_overlay_radius(self, radius):
        """设置覆盖层圆点半径"""
        if self.overlay_manager:
            self.overlay_manager.set_circle_radius(radius)
    
    def set_overlay_z_mapping(self, enabled):
        """设置Z轴颜色映射"""
        if self.overlay_manager:
            self.overlay_manager.set_z_color_mapping(enabled)
    
    def update_overlay_z_value(self, z_value):
        """更新覆盖层Z值"""
        if self.overlay_manager:
            self.overlay_manager.set_z_value(z_value)
    
    def get_current_position(self):
        """获取当前地图位置"""
        return self.current_lat, self.current_lng, self.current_zoom
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            # 停止定时器
            if self.map_capture_timer.isActive():
                self.map_capture_timer.stop()
            
            # 清理覆盖层
            if self.overlay_manager:
                self.overlay_manager.cleanup()
            
            print("地图窗口已关闭")
            event.accept()
            
        except Exception as e:
            print(f"关闭地图窗口时出错: {e}")
            event.accept()
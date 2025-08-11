#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的独立地图窗口
专门用于显示地图，最小依赖版本
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

# 地图URL配置
MAP_URLS = {
    "官方地图": "https://www.kurobbs.com/mc/map",
    "光环助手": "https://www.ghzs666.com/wutheringwaves-map#/?map=default"
}

# qwebchannel.js 内容（简化版）
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
    exports.QWebChannel = QWebChannel;
})((function() {
    return this;
}()));
"""

# 地图拦截器JS代码（简化版）
JS_HYBRID_INTERCEPTOR = """
(function() {
    if (window.discoveredMap && typeof window.discoveredMap.panTo === 'function') {
        return true;
    }

    if (typeof L === 'object' && L.Map && L.Map.prototype.initialize && !L.Map.prototype.initialize._isPatched) {
        console.log("拦截地图构造函数...");
        const originalInitialize = L.Map.prototype.initialize;
        L.Map.prototype.initialize = function(...args) {
            console.log("地图实例已捕获！");
            window.discoveredMap = this;
            return originalInitialize.apply(this, args);
        };
        L.Map.prototype.initialize._isPatched = true;
    }

    if (typeof L === 'object' && L.Map && L.Map.prototype) {
        let deployedB = false;
        const functionsToPatch = ['setView', 'panTo', 'flyTo', 'fitBounds'];
        for (const funcName of functionsToPatch) {
            if (L.Map.prototype[funcName] && !L.Map.prototype[funcName]._isPatchedB) {
                if (!deployedB) console.log("部署地图函数拦截...");
                deployedB = true;

                const originalFunction = L.Map.prototype[funcName];
                L.Map.prototype[funcName] = function(...args) {
                    if (!window.discoveredMap) {
                         console.log(`通过 '${funcName}' 捕获地图实例！`);
                         window.discoveredMap = this;
                    }
                    return originalFunction.apply(this, args);
                };
                L.Map.prototype[funcName]._isPatchedB = true;
            }
        }
    }
    
    return false;
})();
"""


class SimpleMapBackend(QObject):
    """简化的地图后端通信类"""
    statusUpdated = Signal(float, float, int)

    def __init__(self, parent=None):
        super().__init__(parent)

    @Slot(float, float, int)
    def updateStatus(self, lat, lng, zoom):
        self.statusUpdated.emit(lat, lng, zoom)


class SimpleMapWindow(QWidget):
    """简化的独立地图显示窗口"""
    
    # 信号定义
    map_status_updated = Signal(float, float, int)  # lat, lng, zoom
    map_ready = Signal()
    map_error = Signal(str)
    coordinates_jumped = Signal(float, float)  # 坐标跳转完成
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.current_map_mode = "online"  # online 或 local
        self.current_map_provider = "官方地图"
        self.current_local_map = None
        self.current_lat = 0.0
        self.current_lng = 0.0
        self.current_zoom = 1
        
        # 设置窗口属性
        self.setWindowTitle("鸣潮地图导航 - 地图视窗")
        self.setGeometry(800, 100, 1000, 700)
        
        # 创建WebProfile用于保持登录状态
        self.setup_web_profile()
        
        # 设置UI
        self.setup_ui()
        
        # 设置Web通信
        self.setup_web_channel()
        
        # 定时器用于检查地图捕获状态
        self.map_capture_timer = QTimer()
        self.map_capture_timer.timeout.connect(self.check_map_capture)
        
        print("简化地图窗口初始化完成")
    
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
            self.backend = SimpleMapBackend(self)
            self.backend.statusUpdated.connect(self.on_map_status_updated)
            
            # 设置WebChannel
            self.channel = QWebChannel()
            self.web_view.page().setWebChannel(self.channel)
            self.channel.registerObject("backend", self.backend)
            
            print("WebChannel设置完成")
            
        except Exception as e:
            print(f"WebChannel设置失败: {e}")
            self.map_error.emit(f"WebChannel设置失败: {e}")
    
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
            local_url = f"http://localhost:8000/index.html?map={map_name}"
            self.web_view.setUrl(QUrl(local_url))
            self.mode_label.setText(f"本地地图 - {map_name}")
            self.status_label.setText("正在加载本地地图...")
            print(f"加载本地地图: {map_name}")
                
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
    
    def get_current_position(self):
        """获取当前地图位置"""
        return self.current_lat, self.current_lng, self.current_zoom
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            # 停止定时器
            if self.map_capture_timer.isActive():
                self.map_capture_timer.stop()
            
            print("简化地图窗口已关闭")
            event.accept()
            
        except Exception as e:
            print(f"关闭地图窗口时出错: {e}")
            event.accept()
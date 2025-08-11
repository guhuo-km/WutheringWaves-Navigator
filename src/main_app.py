import sys
import os
import numpy as np
import json
import threading
import time
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from werkzeug.serving import make_server
from PySide6.QtCore import QUrl, Slot, QTimer, Qt, QObject, Signal, QThread, QDateTime
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, 
                               QPushButton, QLabel, QRadioButton, QButtonGroup, QTextEdit,
                               QLineEdit, QDialog, QTableWidget, QTableWidgetItem, 
                               QGridLayout, QGroupBox, QHeaderView, QMessageBox, QComboBox,
                               QFileDialog, QProgressDialog, QSpinBox, QCheckBox, QSlider)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebChannel import QWebChannel

# 多语言管理器导入
try:
    from language_manager import get_language_manager, tr
    LANGUAGE_AVAILABLE = True
except ImportError as e:
    print(f"Language module import failed: {e}")
    LANGUAGE_AVAILABLE = False
    # 创建备用翻译函数
    def tr(key, default=None, **kwargs):
        return default if default is not None else key

# OCR模块导入
try:
    from ocr_manager import OCRManager
    OCR_AVAILABLE = True
except ImportError as e:
    print(f"OCR module import failed: {e}")
    OCR_AVAILABLE = False

# 透明覆盖层模块导入
try:
    from transparent_overlay import OverlayManager
    OVERLAY_AVAILABLE = True
except ImportError as e:
    print(f"Transparent overlay module import failed: {e}")
    OVERLAY_AVAILABLE = False

# 路线录制模块导入
try:
    from route_recorder import RouteRecorder
    from route_list_dialog import RouteListDialog
    ROUTE_RECORDER_AVAILABLE = True
except ImportError as e:
    print(f"Route recorder module import failed: {e}")
    ROUTE_RECORDER_AVAILABLE = False

# 分离地图窗口模块导入
try:
    from separated_map_window import SeparatedMapWindow
    SEPARATED_MAP_AVAILABLE = True
except ImportError as e:
    print(f"Separated map window module import failed: {e}")
    SEPARATED_MAP_AVAILABLE = False


# --- 配置区 ---
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

# qwebchannel.js 内容
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

# 地图URL映射 - 根据语言动态选择URL
def get_map_urls(current_language="zh_CN"):
    """根据当前语言返回地图URL映射"""
    # 中文使用旧域名，其他语言使用新域名
    if current_language == "zh_CN":
        aura_url = "https://static-web.ghzs.com/cspage_pro/mingchao-map.html#/?map=default"
    else:
        aura_url = "https://www.ghzs666.com/wutheringwaves-map#/?map=default"
    
    return {
        "official_map": "https://www.kurobbs.com/mc/map",
        "aura_helper": aura_url
    }

# 按钮到URL键的映射
BUTTON_TO_URL_KEY = {
    "radio_online_official": "official_map",
    "radio_online_aura": "aura_helper"
}

# 混合拦截器JS代码
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

# --- 免责声明对话框 ---
class DisclaimerDialog(QDialog):
    """首次使用免责声明对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("呜呜大地图 - 使用条款")
        self.setFixedSize(600, 500)
        self.setModal(True)
        
        # 设置窗口图标和样式
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.CustomizeWindowHint)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title_label = QLabel("欢迎使用《呜呜大地图》！")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #2C3E50;
                margin-bottom: 10px;
            }
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 免责声明内容
        content_text = """本软件由B站UP主 'uid:1876277780' 免费开发并发布。如果您是付费购买的，请立即退款并举报商家。

<b>重要风险提示：</b>

本软件通过"屏幕截图"和"全局快捷键"来获取游戏坐标和提供便利操作。尽管这些技术本身不涉及修改游戏文件或内存，属于辅助工具范畴，但我们无法100%保证其行为完全兼容《鸣潮》未来所有版本更新或其反作弊系统的检测逻辑。

因使用本软件而可能导致的任何游戏账号异常（如警告、暂时限制等）的极低概率风险，需由您本人了解并承担。

点击"确定"即表示您已阅读、理解并同意以上条款。"""
        
        content_label = QLabel(content_text)
        content_label.setWordWrap(True)
        content_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                line-height: 1.6;
                color: #34495E;
                background-color: #F8F9FA;
                border: 1px solid #E9ECEF;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        content_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(content_label)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(80, 35)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #95A5A6;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7F8C8D;
            }
            QPushButton:pressed {
                background-color: #6C7B7D;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        # 确定按钮
        accept_btn = QPushButton("确定")
        accept_btn.setFixedSize(80, 35)
        accept_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498DB;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
            QPushButton:pressed {
                background-color: #21618C;
            }
        """)
        accept_btn.clicked.connect(self.accept)
        
        button_layout.addWidget(cancel_btn)
        button_layout.addSpacing(10)
        button_layout.addWidget(accept_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)

# --- 服务器管理模块 ---
class ServerThread(threading.Thread):
    """一个可以被停止的服务器线程"""
    def __init__(self, server):
        super().__init__()
        self.server = server
        self.daemon = True
        self._stop_requested = False

    def run(self):
        try:
            self.server.serve_forever()
        except Exception as e:
            if not self._stop_requested:
                print(f"Server thread exception: {e}")

    def stop(self):
        """请求停止服务器"""
        self._stop_requested = True
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception as e:
            print(f"Error stopping server: {e}")
    
    def force_stop(self):
        """强制停止线程"""
        self._stop_requested = True
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass

class LocalServerManager:
    """在后台线程中启动和管理本地服务器"""
    def __init__(self):
        self.flask_server_thread = None
        self.http_server_thread = None
        self.flask_app = None
        self.sock = None
        self._is_shutting_down = False  # 添加关闭标志

    def start_servers(self):
        if self.is_running():
            print("Server is already running.")
            return True
        
        try:
            # 确保在正确的目录中导入和启动服务器
            import os
            import sys
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            
            # 启动 Flask + WebSocket 服务器
            from server import app as flask_app, sock
            self.flask_app = flask_app
            self.sock = sock
            
            # 使用 werkzeug 创建服务器，因为它有 shutdown 方法
            flask_server = make_server('127.0.0.1', 8080, self.flask_app)
            self.flask_server_thread = ServerThread(flask_server)
            self.flask_server_thread.start()
            print("Flask + WebSocket backend server started in thread (http://127.0.0.1:8080)")

            # 启动简单HTTP文件服务器
            import os
            from http.server import SimpleHTTPRequestHandler
            from socketserver import ThreadingTCPServer
            
            # 获取脚本所在目录作为文件服务器的根目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 确保在正确的目录中启动文件服务器
            class LocalFileHandler(SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=script_dir, **kwargs)
                
                def log_message(self, format, *args):
                    pass  # 禁用日志输出
            
            # 使用ThreadingTCPServer而不是TCPServer，支持并发且更易停止
            http_server = ThreadingTCPServer(("", 8000), LocalFileHandler)
            http_server.daemon_threads = True  # 设置为守护线程，程序退出时自动结束
            self.http_server_thread = ServerThread(http_server)
            self.http_server_thread.start()
            print("Local file server started in thread (http://localhost:8000)")
            
            return True
        except Exception as e:
            print(f"Failed to start server: {e}")
            self.stop_servers()
            return False

    def stop_servers(self):
        """安全停止所有服务器"""
        if self._is_shutting_down:
            return  # 防止重复调用
            
        self._is_shutting_down = True
        
        # 使用多线程方式异步停止服务器，避免阻塞主线程
        import threading
        
        def stop_flask_server():
            if self.flask_server_thread and self.flask_server_thread.is_alive():
                print("Stopping Flask server...")
                try:
                    self.flask_server_thread.stop()
                    if not self.flask_server_thread.join(timeout=0.5):
                        print("Flask server timeout, force termination")
                    print("Flask server stopped")
                except Exception as e:
                    print(f"Error stopping Flask server: {e}")
                finally:
                    self.flask_server_thread = None
        
        def stop_http_server():
            if self.http_server_thread and self.http_server_thread.is_alive():
                print("Stopping file server...")
                try:
                    self.http_server_thread.stop()
                    if not self.http_server_thread.join(timeout=0.5):
                        print("File server timeout, force termination")
                    print("File server stopped")
                except Exception as e:
                    print(f"Error stopping file server: {e}")
                finally:
                    self.http_server_thread = None
        
        # 并行停止两个服务器
        flask_stopper = threading.Thread(target=stop_flask_server, daemon=True)
        http_stopper = threading.Thread(target=stop_http_server, daemon=True)
        
        flask_stopper.start()
        http_stopper.start()
        
        # 等待停止完成，但设置总超时时间
        flask_stopper.join(timeout=1)
        http_stopper.join(timeout=1)
        
        # 强制清理
        if flask_stopper.is_alive():
            print("Flask stop thread timeout, force cleanup")
            self.flask_server_thread = None
            
        if http_stopper.is_alive():
            print("HTTP stop thread timeout, force cleanup") 
            self.http_server_thread = None
                
        self._is_shutting_down = False
        print("All servers stopped")
            
    def is_running(self):
        """检查服务器是否正在运行"""
        try:
            return (not self._is_shutting_down and 
                    self.flask_server_thread is not None and 
                    self.flask_server_thread.is_alive())
        except Exception:
            return False

    def get_local_maps(self):
        """从 maps.json 读取本地地图列表"""
        try:
            import os
            script_dir = os.path.dirname(os.path.abspath(__file__))
            maps_json_path = os.path.join(script_dir, 'maps.json')
            with open(maps_json_path, 'r', encoding='utf-8') as f:
                return [item['name'] for item in json.load(f)]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def broadcast_command(self, command):
        """通过 WebSocket 向本地地图客户端广播指令"""
        if not self.is_running():
            print("Error: Server not running, cannot broadcast command.")
            return False
            
        try:
            import os
            import sys
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
                
            from server import broadcast
            broadcast(command)
            print(f"Broadcasted command: {command}")
            return True
        except Exception as e:
            print(f"Failed to broadcast command: {e}")
            return False

# --- 地图生成工作线程 ---
class MapGeneratorWorker(QThread):
    """地图生成工作线程，防止UI卡死"""
    progress_updated = Signal(int)  # 进度更新信号
    status_updated = Signal(str)    # 状态更新信号
    finished = Signal(bool, str)    # 完成信号 (成功/失败, 消息)
    
    def __init__(self, image_paths):
        super().__init__()
        self.image_paths = image_paths
        
    def run(self):
        """在后台线程中执行地图生成"""
        try:
            import os
            # 切换到正确的工作目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            original_cwd = os.getcwd()
            os.chdir(script_dir)
            
            try:
                # 检查是否存在tile_generator模块
                try:
                    from tile_generator import process_image, get_image_info
                except ImportError:
                    # 如果没有tile_generator模块，则只处理直接复制的情况
                    self.error_occurred.emit(tr('tile_generator_missing', 'tile_generator模块不存在，只能处理直接复制到maps目录的地图文件'))
                    return
                
                total_files = len(self.image_paths)
                
                for i, image_path in enumerate(self.image_paths):
                    self.status_updated.emit(tr('processing_file', '正在处理: {filename}', filename=os.path.basename(image_path)))
                    
                    # 检查文件信息
                    file_size_mb, width, height = get_image_info(image_path)
                    if not file_size_mb:
                        continue
                        
                    # 处理图片
                    map_name = os.path.splitext(os.path.basename(image_path))[0]
                    try:
                        process_image(image_path)
                    except Exception as e:
                        self.finished.emit(False, tr('processing_failed', '处理 {map_name} 失败: {error}', map_name=map_name, error=str(e)))
                        return
                        
                    # 更新进度
                    progress = int((i + 1) / total_files * 100)
                    self.progress_updated.emit(progress)
                    
                self.finished.emit(True, tr('processing_complete', '成功处理了 {count} 个地图文件', count=total_files))
                
            finally:
                # 恢复原来的工作目录
                os.chdir(original_cwd)
            
        except Exception as e:
            self.finished.emit(False, tr('processing_error', '处理过程中出现错误: {error}', error=str(e)))

# --- 校准数据管理类 ---
class CalibrationDataManager:
    """管理校准矩阵数据的持久化存储"""
    
    def __init__(self):
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.calibration_file = os.path.join(script_dir, "calibration_data.json")
        
    def get_map_key(self, mode, provider_or_map_name, area_id=None):
        """生成地图的唯一标识键"""
        if mode == 'online':
            return f"online_{provider_or_map_name}_{area_id or 'default'}"
        else:
            return f"local_{provider_or_map_name}"
    
    def save_calibration(self, mode, provider_or_map_name, transform_matrix, area_id=None):
        """保存校准数据"""
        try:
            print(f"[DEBUG] Starting to save calibration data: mode={mode}, provider={provider_or_map_name}, area_id={area_id}")
            
            # 读取现有数据
            data = self.load_all_calibrations()
            print(f"[DEBUG] Current calibration data count: {len(data)}")
            
            # 生成地图键
            map_key = self.get_map_key(mode, provider_or_map_name, area_id)
            print(f"[DEBUG] Generated map key: {map_key}")
            
            # 保存校准数据
            calibration_data = {
                "mode": mode,
                "provider_or_map_name": provider_or_map_name,
                "area_id": area_id,
                "matrix": {
                    "a": transform_matrix.a,
                    "b": transform_matrix.b,
                    "c": transform_matrix.c,
                    "d": transform_matrix.d,
                    "e": transform_matrix.e,
                    "f": transform_matrix.f
                },
                "timestamp": datetime.now().isoformat()
            }
            
            data[map_key] = calibration_data
            print(f"[DEBUG] Calibration data added to memory, now has {len(data)} entries")
            
            # 写入文件
            with open(self.calibration_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            print(f"✅ Calibration data saved: {map_key}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to save calibration data: {e}")
            import traceback
            print(f"Error details: {traceback.format_exc()}")
            return False
    
    def load_calibration(self, mode, provider_or_map_name, area_id=None):
        """加载特定地图的校准数据"""
        try:
            data = self.load_all_calibrations()
            map_key = self.get_map_key(mode, provider_or_map_name, area_id)
            
            if map_key in data:
                calibration_data = data[map_key]
                matrix_data = calibration_data["matrix"]
                
                # 重建变换矩阵
                transform_matrix = TransformMatrix(
                    matrix_data["a"], matrix_data["b"], matrix_data["c"],
                    matrix_data["d"], matrix_data["e"], matrix_data["f"]
                )
                
                print(f"Loaded calibration data: {map_key}")
                return transform_matrix
            
            return None
            
        except Exception as e:
            print(f"Failed to load calibration data: {e}")
            return None
    
    def load_all_calibrations(self):
        """加载所有校准数据"""
        try:
            if os.path.exists(self.calibration_file):
                with open(self.calibration_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception:
            return {}
    
    def has_calibration(self, mode, provider_or_map_name, area_id=None):
        """检查是否存在校准数据"""
        data = self.load_all_calibrations()
        map_key = self.get_map_key(mode, provider_or_map_name, area_id)
        return map_key in data
    
    def delete_calibration(self, mode, provider_or_map_name, area_id=None):
        """删除校准数据"""
        try:
            data = self.load_all_calibrations()
            map_key = self.get_map_key(mode, provider_or_map_name, area_id)
            
            if map_key in data:
                del data[map_key]
                with open(self.calibration_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print(f"Deleted calibration data: {map_key}")
                return True
            return False
            
        except Exception as e:
            print(f"Failed to delete calibration data: {e}")
            return False

# --- 核心转换逻辑类 ---
class CalibrationPoint:
    """校准点数据结构"""
    def __init__(self, x, y, lat, lon):
        self.x = x
        self.y = y
        self.lat = lat
        self.lon = lon

class TransformMatrix:
    """变换矩阵"""
    def __init__(self, a=0, b=0, c=0, d=0, e=0, f=0):
        self.a = a  # lat = a*x + b*y + c
        self.b = b
        self.c = c
        self.d = d  # lon = d*x + e*y + f
        self.e = e
        self.f = f

class CalibrationSystem:
    """地图校准系统核心逻辑"""
    
    @staticmethod
    def calculate_transform_matrix(points):
        """基于校准点计算仿射变换矩阵"""
        if len(points) < 2:
            raise ValueError(tr('calibration_min_points', '至少需要2个校准点'))
        
        # 构建线性方程组 Ax = b
        n = len(points)
        A = np.zeros((2*n, 6))
        b = np.zeros(2*n)
        
        for i, point in enumerate(points):
            # lat = a*x + b*y + c
            A[2*i] = [point.x, point.y, 1, 0, 0, 0]
            b[2*i] = point.lat
            
            # lon = d*x + e*y + f
            A[2*i+1] = [0, 0, 0, point.x, point.y, 1]
            b[2*i+1] = point.lon
        
        # 使用最小二乘法求解
        try:
            x = np.linalg.lstsq(A, b, rcond=None)[0]
            return TransformMatrix(x[0], x[1], x[2], x[3], x[4], x[5])
        except np.linalg.LinAlgError:
            raise ValueError(tr('transform_matrix_error', '无法计算变换矩阵，请检查校准点数据'))
    
    @staticmethod
    def transform(x, y, matrix):
        """使用变换矩阵将游戏坐标转换为地理坐标"""
        if matrix is None:
            raise ValueError(tr('matrix_not_initialized', '变换矩阵未初始化'))
        
        lat = matrix.a * x + matrix.b * y + matrix.c
        lon = matrix.d * x + matrix.e * y + matrix.f
        return lat, lon


# --- 后端通信类 ---
class MapBackend(QObject):
    statusUpdated = Signal(float, float, int)

    def __init__(self, parent=None):
        super().__init__(parent)

    @Slot(float, float, int)
    def updateStatus(self, lat, lng, zoom):
        self.statusUpdated.emit(lat, lng, zoom)

# --- 校准窗口 ---
class CalibrationWindow(QDialog):
    calibrationFinished = Signal(object)  # 传递变换矩阵

    def __init__(self, parent=None, current_map_provider="官方地图", current_map_url=None):
        super().__init__(parent)
        self.setWindowTitle(tr('map_calibration', '地图校准'))
        self.setGeometry(200, 200, 1200, 800)
        self.setModal(True)
        
        self.calibration_points = []
        self.transform_matrix = None
        self.current_lat = 0.0
        self.current_lng = 0.0
        self.current_zoom = 1
        self.current_map_provider = current_map_provider  # 记录当前地图提供商
        self.current_map_url = current_map_url  # 记录当前具体URL（包含副本信息）
        
        self.setup_ui()
        self.setup_web_channel()
        self.load_map()

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        
        # 左侧: 地图视图
        map_layout = QVBoxLayout()
        
        # 十字准星标签
        self.crosshair_label = QLabel("+")
        self.crosshair_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crosshair_label.setStyleSheet("""
            QLabel { 
                color: red; 
                font-size: 24px; 
                font-weight: bold; 
                background: transparent; 
                border: none;
            }
        """)
        self.crosshair_label.setFixedSize(32, 32)
        
        # 地图视图 - 使用主窗口的WebProfile创建独立页面（避免页面共享冲突）
        try:
            parent_window = self.parent()
            if (parent_window and 
                hasattr(parent_window, 'web_profile') and 
                parent_window.web_profile):
                # 使用主窗口的profile创建新页面，保持session和cookie一致
                from PySide6.QtWebEngineCore import QWebEnginePage
                web_page = QWebEnginePage(parent_window.web_profile, self)
                self.web_view = QWebEngineView()
                self.web_view.setPage(web_page)
                self.shared_profile = True  # 标记使用共享profile
                self.log("Calibration window using main window's WebProfile to create independent page")
            else:
                # 降级方案：创建完全独立的页面
                self.web_view = QWebEngineView()
                self.shared_profile = False
                self.log("Calibration window using default web view")
        except Exception as e:
            self.web_view = QWebEngineView()
            self.shared_profile = False
            self.log(f"Calibration window web view setup failed, using default: {e}")
        
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        
        # 创建叠加布局，将十字准星放在地图中心
        map_container = QWidget()
        overlay_layout = QVBoxLayout(map_container)
        overlay_layout.addWidget(self.web_view)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        
        # 使用grid layout将十字准星定位到中心
        grid_layout = QGridLayout()
        grid_layout.addWidget(map_container, 0, 0, 3, 3)
        grid_layout.addWidget(self.crosshair_label, 1, 1, Qt.AlignmentFlag.AlignCenter)
        
        map_widget = QWidget()
        map_widget.setLayout(grid_layout)
        map_layout.addWidget(map_widget)
        
        # 右侧: 控制面板
        control_layout = QVBoxLayout()
        control_widget = QWidget()
        control_widget.setFixedWidth(350)
        control_widget.setLayout(control_layout)
        
        # 状态信息组
        status_group = QGroupBox(tr('map_status', '地图状态'))
        status_layout = QVBoxLayout(status_group)
        
        self.capture_status_label = QLabel(tr('capture_status_capturing', '捕获状态: 正在捕获...'))
        self.lat_lng_label = QLabel(tr('lat_lng_waiting', '经纬度: 等待数据...'))
        self.zoom_label = QLabel(tr('zoom_level_waiting', '缩放等级: 等待数据...'))
        
        status_layout.addWidget(self.capture_status_label)
        status_layout.addWidget(self.lat_lng_label)
        status_layout.addWidget(self.zoom_label)
        
        # 坐标输入组
        input_group = QGroupBox(tr('game_coordinate_input', '游戏坐标输入'))
        input_layout = QGridLayout(input_group)
        
        input_layout.addWidget(QLabel(tr('x_coordinate', 'X坐标:')), 0, 0)
        self.x_input = QLineEdit()
        input_layout.addWidget(self.x_input, 0, 1)
        
        input_layout.addWidget(QLabel(tr('y_coordinate', 'Y坐标:')), 1, 0)
        self.y_input = QLineEdit()
        input_layout.addWidget(self.y_input, 1, 1)
        
        # 校准操作组
        calib_group = QGroupBox(tr('calibration_operations', '校准操作'))
        calib_layout = QVBoxLayout(calib_group)
        
        self.calib_btn1 = QPushButton(tr('set_calibration_point_1', '设定校准点 1'))
        self.calib_btn2 = QPushButton(tr('set_calibration_point_2', '设定校准点 2'))
        self.calib_btn3 = QPushButton(tr('set_calibration_point_3', '设定校准点 3'))
        self.finish_btn = QPushButton(tr('calculate_and_finish_calibration', '计算并完成校准'))
        self.finish_btn.setEnabled(False)
        
        calib_layout.addWidget(self.calib_btn1)
        calib_layout.addWidget(self.calib_btn2)
        calib_layout.addWidget(self.calib_btn3)
        calib_layout.addWidget(self.finish_btn)
        
        # 校准数据表格
        table_group = QGroupBox(tr('calibration_data', '校准数据'))
        table_layout = QVBoxLayout(table_group)
        
        self.data_table = QTableWidget(0, 5)
        self.data_table.setHorizontalHeaderLabels([tr('number', '序号'), tr('game_x', '游戏X'), tr('game_y', '游戏Y'), tr('latitude', '纬度(Lat)'), tr('longitude', '经度(Lon)')])
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table_layout.addWidget(self.data_table)
        
        # 组装右侧布局
        control_layout.addWidget(status_group)
        control_layout.addWidget(input_group)
        control_layout.addWidget(calib_group)
        control_layout.addWidget(table_group)
        control_layout.addStretch()
        
        # 组装主布局
        main_layout.addWidget(map_widget, stretch=3)
        main_layout.addWidget(control_widget, stretch=1)
        
        # 连接信号
        self.calib_btn1.clicked.connect(lambda: self.add_calibration_point(1))
        self.calib_btn2.clicked.connect(lambda: self.add_calibration_point(2))
        self.calib_btn3.clicked.connect(lambda: self.add_calibration_point(3))
        self.finish_btn.clicked.connect(self.finish_calibration)

    def setup_web_channel(self):
        # 为校准窗口创建独立的WebChannel和MapBackend
        self.backend = MapBackend(self)
        self.channel = QWebChannel(self.web_view.page())
        self.web_view.page().setWebChannel(self.channel)
        self.channel.registerObject("backend", self.backend)
        self.backend.statusUpdated.connect(self.on_map_status_updated)
        self.log("Calibration window created independent WebChannel")

    def load_map(self):
        # 校准窗口需要加载与主窗口相同的地图
        if self.current_map_url:
            map_url = self.current_map_url
            self.log(f"Calibration window loading current URL: {map_url}")
        else:
            if self.current_map_provider == tr('local_map', '本地地图'):
                map_url = "http://localhost:8000/index.html"
                self.log(f"Calibration window loading local map: {map_url}")
            elif self.current_map_provider in get_map_urls(self.language_manager.get_current_language() if hasattr(self, 'language_manager') else "zh_CN"):
                map_urls = get_map_urls(self.language_manager.get_current_language() if hasattr(self, 'language_manager') else "zh_CN")
                map_url = map_urls[self.current_map_provider]
                self.log(f"Calibration window loading default map: {self.current_map_provider} -> {map_url}")
            else:
                self.log(f"Error: Unknown map provider '{self.current_map_provider}'")
                return
        
        self.web_view.setUrl(QUrl(map_url))
        self.web_view.loadFinished.connect(self.on_load_finished)

    @Slot(bool)
    def on_load_finished(self, ok):
        if ok:
            self.log("Calibration map loaded, starting capture...")
            self.web_view.page().runJavaScript(QWEBCHANNEL_JS_CONTENT)
            QTimer.singleShot(500, self.start_capture)

    def start_capture(self):
        self.capture_timer = QTimer(self)
        self.capture_timer.timeout.connect(self.run_capture)
        self.capture_timer.start(100)
        self.capture_attempts = 0

    def run_capture(self):
        self.capture_attempts += 1
        
        if self.capture_attempts > 100:  # 10秒超时
            self.capture_status_label.setText(tr('capture_status_timeout', '捕获状态: 捕获超时!'))
            self.capture_timer.stop()
            return
            
        self.web_view.page().runJavaScript(JS_HYBRID_INTERCEPTOR)
        self.web_view.page().runJavaScript("!!window.discoveredMap", self.on_capture_result)

    @Slot(object)
    def on_capture_result(self, success):
        if success:
            self.capture_status_label.setText("捕获状态: 捕获成功!")
            self.capture_timer.stop()
            self.deploy_listeners()

    def deploy_listeners(self):
        js_listener_script = """
        new QWebChannel(qt.webChannelTransport, function(channel) {
            var py_backend = channel.objects.backend;

            function send_status_to_python() {
                try {
                    const center = window.discoveredMap.getCenter();
                    const zoom = window.discoveredMap.getZoom();
                    py_backend.updateStatus(center.lat, center.lng, zoom);
                } catch (error) {
                    console.error('发送状态到Python时出错:', error);
                }
            }

            window.discoveredMap.on('moveend zoomend', send_status_to_python);
            console.log('校准窗口事件监听器部署完毕');
            send_status_to_python();
        });
        """
        self.web_view.page().runJavaScript(js_listener_script)

    @Slot(float, float, int)
    def on_map_status_updated(self, lat, lng, zoom):
        self.current_lat = lat
        self.current_lng = lng
        self.current_zoom = zoom
        self.lat_lng_label.setText(f"经纬度: {lat:.6f}, {lng:.6f}")
        self.zoom_label.setText(f"缩放等级: {zoom}")

    def add_calibration_point(self, point_num):
        try:
            x = float(self.x_input.text())
            y = float(self.y_input.text())
        except ValueError:
            QMessageBox.warning(self, "输入错误", "请输入有效的数值坐标!")
            return

        if self.current_lat == 0 and self.current_lng == 0:
            QMessageBox.warning(self, "地图未就绪", "请等待地图加载完成!")
            return

        # 创建校准点
        point = CalibrationPoint(x, y, self.current_lat, self.current_lng)
        self.calibration_points.append(point)

        # 添加到表格
        row = self.data_table.rowCount()
        self.data_table.insertRow(row)
        self.data_table.setItem(row, 0, QTableWidgetItem(str(point_num)))
        self.data_table.setItem(row, 1, QTableWidgetItem(f"{x:.2f}"))
        self.data_table.setItem(row, 2, QTableWidgetItem(f"{y:.2f}"))
        self.data_table.setItem(row, 3, QTableWidgetItem(f"{self.current_lat:.6f}"))
        self.data_table.setItem(row, 4, QTableWidgetItem(f"{self.current_lng:.6f}"))

        # 清空输入框
        self.x_input.clear()
        self.y_input.clear()

        # 禁用当前按钮
        if point_num == 1:
            self.calib_btn1.setEnabled(False)
        elif point_num == 2:
            self.calib_btn2.setEnabled(False)
        elif point_num == 3:
            self.calib_btn3.setEnabled(False)

        # 检查是否可以完成校准
        if len(self.calibration_points) >= 2:
            self.finish_btn.setEnabled(True)

        self.log(f"已添加校准点 {point_num}: ({x}, {y}) -> ({self.current_lat:.6f}, {self.current_lng:.6f})")

    def finish_calibration(self):
        try:
            self.transform_matrix = CalibrationSystem.calculate_transform_matrix(self.calibration_points)
            
            # 发射校准完成信号
            self.calibrationFinished.emit(self.transform_matrix)
            
            QMessageBox.information(self, "校准完成", 
                f"校准成功完成!\n使用了 {len(self.calibration_points)} 个校准点")
            
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "校准失败", f"校准计算失败: {str(e)}")

    def closeEvent(self, event):
        """重写关闭事件，正确清理资源"""
        try:
            # 停止捕获定时器
            if hasattr(self, 'capture_timer') and self.capture_timer:
                self.capture_timer.stop()
            
            # 清理独立页面资源
            if hasattr(self, 'web_view') and self.web_view:
                self.web_view.close()
            
            self.log("校准窗口关闭，清理资源完成")
        except Exception as e:
            self.log(f"关闭校准窗口时出错: {e}")
        
        super().closeEvent(event)

    def log(self, message):
        print(f"[校准窗口] {message}")


# --- 主窗口 (增强版) ---
class MapCalibrationMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 初始化多语言管理器
        if LANGUAGE_AVAILABLE:
            self.language_manager = get_language_manager()
            self.language_manager.language_changed.connect(self.on_language_changed)
        
        self.setWindowTitle(tr("app_title", "呜呜大地图 - 混合模式 V4"))
        self.setGeometry(100, 100, 1010, 770)
        
        # 初始化关闭标志
        self._is_closing = False
        
        self.current_area_id = None
        self.transform_matrix = None  # 存储校准完成后的变换矩阵
        
        # --- 新增状态 ---
        self.current_mode = "online"  # 'online' 或 'local'
        self.server_manager = LocalServerManager()
        self.local_maps = []
        self.calibration_manager = CalibrationDataManager()
        self._is_closing = False  # 关闭标志
        
        # --- 设置文件路径 ---
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.settings_file = os.path.join(script_dir, "app_settings.json")
        
        # --- OCR功能初始化 ---
        if OCR_AVAILABLE:
            self.ocr_manager = OCRManager(self)
            self.ocr_manager.coordinates_detected.connect(self.on_ocr_coordinates_detected)
            self.ocr_manager.state_changed.connect(self.on_ocr_state_changed)
            self.ocr_manager.error_occurred.connect(self.on_ocr_error)
            # 设置OCR自动跳转回调
            self.ocr_manager.set_jump_callback(self.ocr_auto_jump)
        else:
            self.ocr_manager = None
        
        # --- 透明覆盖层初始化 ---
        self.overlay_manager = None
        
        # --- 路线录制初始化 ---
        if ROUTE_RECORDER_AVAILABLE:
            self.route_recorder = RouteRecorder(self)
            self.route_recorder.recording_started.connect(self.on_recording_started)
            self.route_recorder.recording_stopped.connect(self.on_recording_stopped)
            self.route_recorder.point_recorded.connect(self.on_point_recorded)
            self.route_recorder.error_occurred.connect(self.on_recording_error)
        else:
            self.route_recorder = None
        
        # --- 分离地图窗口初始化（稍后创建，在UI设置完成后） ---
        self.separated_map_window = None  # 稍后创建
        
        # --- 地图追踪功能初始化（默认开启）---
        self.tracking_active = True
        self.tracking_timer = QTimer()
        self.tracking_timer.timeout.connect(self.update_tracking_position)
        self.current_lat = None
        self.current_lng = None
        self.current_zoom = None
        self.tracking_history = []  # 存储追踪历史
        
        try:
            # 首先检查免责声明（在UI初始化之前）
            # 注意：由于需要在UI初始化后才能显示对话框，我们需要延迟检查
            self.setup_ui()
            self.setup_web_channel()
            self.connect_signals()
            
            # 在UI完全初始化后检查免责声明
            QTimer.singleShot(100, self.check_disclaimer_on_startup)
            
            # 启动本地服务器（始终运行）
            self.start_local_servers()
            
            print("Initialization complete")
        except Exception as e:
            print(f"Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            # 初始化失败时显示错误信息
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(None, tr('initialization_error', '初始化错误'), 
                                   tr('initialization_failed_msg', '程序初始化失败：\n{error}\n\n请检查控制台输出获取详细信息。', error=str(e)))
            except Exception:
                pass  # 如果连消息框都无法显示，就放弃

    # =============== 分离地图窗口相关方法 ===============
    
    def auto_separate_map_window(self):
        """启动时自动分离地图窗口"""
        try:
            print("Auto separating map window on startup...")
            self.separate_map_window()
        except Exception as e:
            print(f"Auto separate map window failed: {e}")
    
    def start_default_tracking(self):
        """启动时默认开启地图追踪"""
        try:
            if self.tracking_active:
                self.tracking_timer.start(1000)  # 每秒更新一次
                self.log("🎯 Map tracking enabled by default")
                print("Map tracking enabled by default")
        except Exception as e:
            print(f"Failed to start default tracking: {e}")
    
    def separate_map_window(self):
        """分离地图到独立窗口"""
        try:
            if not SEPARATED_MAP_AVAILABLE:
                self.log("❌ Separated map window module not available")
                return
            
            if self.separated_map_window is not None:
                self.log("⚠️ Map already separated to independent window")
                return
            
            # 创建分离的地图窗口，传入WebView和主窗口引用
            self.separated_map_window = SeparatedMapWindow(self.web_view, self)
            
            # 连接关闭信号
            self.separated_map_window.window_closed.connect(self.on_separated_map_closed)
            
            # 在主窗口右侧显示分离窗口
            self.separated_map_window.show_at_position(self.geometry())
            
            # 无需更新UI状态，已移除相关显示组件
            
            self.log("🗺️ Map separated to independent window")
            print("Map WebView moved to independent window")
            
        except Exception as e:
            error_msg = f"Failed to separate map window: {e}"
            self.log(f"❌ {error_msg}")
            print(error_msg)
    
    def merge_map_window(self):
        """合并地图回主窗口（现在主窗口是纯控制台，不支持合并）"""
        try:
            self.log("⚠️ Current version does not support merge function, main window is pure console interface")
            print("Merge function not supported - main window is pure console interface")
            
        except Exception as e:
            error_msg = f"Merge operation failed: {e}"
            self.log(f"❌ {error_msg}")
            print(error_msg)
    
    def on_separated_map_closed(self):
        """分离地图窗口被关闭时的处理"""
        try:
            # 用户关闭了分离窗口
            self.separated_map_window = None
            
            self.log("⚠️ Map window closed by user")
            print("Separated map window closed")
            
        except Exception as e:
            print(f"处理分离地图窗口关闭事件失败: {e}")

    def closeEvent(self, event):
        """优雅关闭应用程序的所有功能"""
        print("主窗口关闭事件触发")
        
        # 立即设置关闭标志，确保其他清理方法能检测到
        self._is_closing = True
        print(f"设置关闭标志: {self._is_closing}")
        
        # 第一步：找到并强制关闭地图窗口
        print("搜索并强制关闭地图窗口...")
        map_window_closed = False
        
        # 方法1：通过成员变量关闭
        if hasattr(self, 'separated_map_window') and self.separated_map_window:
            print(f"找到地图窗口引用: {self.separated_map_window}")
            try:
                # 断开信号连接，防止循环调用
                self.separated_map_window.window_closed.disconnect()
                self.separated_map_window._is_closing = True
                self.separated_map_window.hide()
                self.separated_map_window.close()
                self.separated_map_window.deleteLater()
                print("通过引用强制关闭地图窗口成功")
                map_window_closed = True
            except Exception as e:
                print(f"通过引用关闭地图窗口失败: {e}")
        
        # 方法2：通过查找所有窗口来关闭
        if not map_window_closed:
            try:
                from PySide6.QtWidgets import QApplication
                for widget in QApplication.topLevelWidgets():
                    if hasattr(widget, 'windowTitle') and "地图窗口" in widget.windowTitle():
                        print(f"找到地图窗口: {widget.windowTitle()}")
                        widget.hide()
                        widget.close()
                        widget.deleteLater()
                        print("通过搜索强制关闭地图窗口成功")
                        map_window_closed = True
                        break
            except Exception as e:
                print(f"通过搜索关闭地图窗口失败: {e}")
        
        # 清空引用
        self.separated_map_window = None
        
        if map_window_closed:
            print("地图窗口已强制关闭")
        else:
            print("未找到需要关闭的地图窗口")
        
        # 第二步：强制终止整个进程
        print("现在强制终止整个程序进程...")
        try:
            from PySide6.QtWidgets import QApplication
            import os
            import sys
            
            # 先尝试正常退出
            QApplication.quit()
            print("Qt应用退出指令已发送")
            
            # 强制终止进程，确保程序完全退出
            print("强制终止进程...")
            os._exit(0)  # 立即终止进程，不执行任何清理
            
        except Exception as e:
            print(f"退出程序时出错: {e}")
            # 最后的保障
            import os
            os._exit(1)
        
        # 程序应该已经在 os._exit(0) 处终止了
    
    def _stop_all_timers(self):
        """停止所有定时器"""
        try:
            # 停止主定时器
            if hasattr(self, 'timer') and self.timer:
                self.timer.stop()
                self.timer.deleteLater()
                self.timer = None
            
            # 停止其他可能的定时器
            for attr_name in dir(self):
                attr = getattr(self, attr_name, None)
                if isinstance(attr, QTimer) and attr.isActive():
                    attr.stop()
                    attr.deleteLater()
            
            print("所有定时器已停止")
        except Exception as e:
            print(f"停止定时器时出错: {e}")
    
    def _stop_worker_threads(self):
        """快速停止工作线程"""
        try:
            if hasattr(self, 'map_worker') and self.map_worker and self.map_worker.isRunning():
                print("正在停止地图生成工作线程...")
                # 直接terminate，不等待
                self.map_worker.terminate()
                # 只等待很短时间
                if not self.map_worker.wait(500):
                    print("工作线程已强制终止")
                self.map_worker = None
            print("工作线程已停止")
        except Exception as e:
            print(f"停止工作线程时出错: {e}")
    
    def _close_dialogs(self):
        """关闭所有对话框"""
        try:
            if hasattr(self, 'progress_dialog') and self.progress_dialog:
                self.progress_dialog.close()
                self.progress_dialog = None
            print("对话框已关闭")
        except Exception as e:
            print(f"关闭对话框时出错: {e}")
    
    def _cleanup_webview(self):
        """清理WebView资源"""
        try:
            if hasattr(self, 'web_view') and self.web_view:
                # 先停止加载
                self.web_view.stop()
                # 设置空白页面，避免卡在某个页面
                self.web_view.setUrl(QUrl("about:blank"))
                # 立即关闭，不等待
                self.web_view.close()
                print("WebView已清理")
        except Exception as e:
            print(f"WebView清理时出错: {e}")
    
    def _stop_backend_servers(self):
        """停止后台服务器"""
        try:
            print("正在停止后台服务器...")
            
            # 更新状态显示
            if hasattr(self, 'server_status_label'):
                self.server_status_label.setText("服务器状态: 关闭中...")
                self.server_status_label.setStyleSheet("color: orange;")
            
            # 停止服务器（使用优化后的逻辑）
            self.server_manager.stop_servers()
            
            # 更新状态显示
            if hasattr(self, 'server_status_label'):
                self.server_status_label.setText("服务器状态: 已关闭")
                self.server_status_label.setStyleSheet("color: gray;")
            
            print("后台服务器已停止")
            
        except Exception as e:
            print(f"Error stopping server: {e}")
            if hasattr(self, 'server_status_label'):
                self.server_status_label.setText("服务器状态: 停止错误")
                self.server_status_label.setStyleSheet("color: red;")

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # --- 全新顶部布局 ---
        top_layout = QHBoxLayout()
        
        # 语言选择
        language_group = QGroupBox(tr("language", "语言"))
        language_layout = QHBoxLayout(language_group)
        self.language_combo = QComboBox()
        if LANGUAGE_AVAILABLE:
            supported_langs = self.language_manager.get_supported_languages()
            for code, name in supported_langs.items():
                self.language_combo.addItem(name, code)
            # 设置当前语言
            current_lang = self.language_manager.get_current_language()
            for i in range(self.language_combo.count()):
                if self.language_combo.itemData(i) == current_lang:
                    self.language_combo.setCurrentIndex(i)
                    break
            self.language_combo.currentTextChanged.connect(self.on_language_combo_changed)
        language_layout.addWidget(self.language_combo)
        
        # 模式选择
        mode_group = QGroupBox(tr("group_map_provider", "模式选择"))
        mode_layout = QHBoxLayout(mode_group)
        self.radio_online = QRadioButton(tr("online", "在线地图"))
        self.radio_local = QRadioButton(tr("local", "本地地图"))
        self.radio_mode_group = QButtonGroup(self)
        self.radio_mode_group.addButton(self.radio_online)
        self.radio_mode_group.addButton(self.radio_local)
        self.radio_online.setChecked(True)
        mode_layout.addWidget(self.radio_online)
        mode_layout.addWidget(self.radio_local)
        
        # 在线地图源选择
        self.online_map_group = QGroupBox(tr("group_map_provider", "在线地图源"))
        online_map_layout = QHBoxLayout(self.online_map_group)
        self.radio_kuro = QRadioButton(tr("radio_online_official", "官方地图"))
        self.radio_ghzs = QRadioButton(tr("radio_online_aura", "光环助手"))
        self.radio_online_map_group = QButtonGroup(self)
        self.radio_online_map_group.addButton(self.radio_kuro)
        self.radio_online_map_group.addButton(self.radio_ghzs)
        self.radio_kuro.setChecked(True)
        online_map_layout.addWidget(self.radio_kuro)
        online_map_layout.addWidget(self.radio_ghzs)
        
        # 本地地图选择
        self.local_map_group = QGroupBox(tr("radio_local_map", "本地地图"))
        local_map_layout = QHBoxLayout(self.local_map_group)
        self.local_map_combo = QComboBox()
        self.add_map_btn = QPushButton(tr("button_add_map", "添加地图"))
        self.add_map_btn.setToolTip(tr("tooltip_add_map", "选择图片文件生成地图"))
        self.delete_map_btn = QPushButton(tr("delete", "删除地图"))
        self.delete_map_btn.setToolTip(tr("tooltip_delete_map", "删除当前选择的本地地图"))
        self.delete_map_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; }")
        local_map_layout.addWidget(self.local_map_combo)
        local_map_layout.addWidget(self.add_map_btn)
        local_map_layout.addWidget(self.delete_map_btn)
        self.local_map_group.setVisible(False)  # 默认隐藏
        
        top_layout.addWidget(language_group)
        top_layout.addWidget(mode_group)
        top_layout.addWidget(self.online_map_group)
        top_layout.addWidget(self.local_map_group)
        top_layout.addStretch()
        
        # 状态信息区
        status_layout = QHBoxLayout()
        self.status_label = QLabel(tr('status_initializing', '状态: 正在初始化...'))
        self.url_status_label = QLabel(tr('current_map_area', '当前地图/区域: N/A'))  # 标签文本改一下
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.url_status_label)
        
        # 实时地图状态
        self.map_status_label = QLabel(tr('realtime_status_waiting', '实时状态: 等待捕获...'))
        
        # 服务器状态指示器
        self.server_status_label = QLabel(tr('server_status_starting', '服务器状态: 启动中...'))
        self.server_status_label.setStyleSheet("color: orange;")
        
        # 控制面板
        control_layout = QHBoxLayout()
        
        # 左侧: 地图控制
        map_control_group = QGroupBox(tr('map_control', '地图控制'))
        map_control_layout = QGridLayout(map_control_group)
        
        # 方向控制按钮
        self.up_btn = QPushButton(tr('direction_north', '↑ 向北'))
        self.down_btn = QPushButton(tr('direction_south', '↓ 向南')) 
        self.left_btn = QPushButton(tr('direction_west', '← 向西'))
        self.right_btn = QPushButton(tr('direction_east', '→ 向东'))
        
        # 缩放控制
        self.zoom_in_btn = QPushButton(tr('zoom_in', '放大 (+)'))
        self.zoom_out_btn = QPushButton(tr('zoom_out', '缩小 (-)'))
        
        # 其他控制
        self.recapture_btn = QPushButton(tr('force_recapture', '强制重捕获'))
        
        # 布局方向控制按钮
        map_control_layout.addWidget(self.up_btn, 0, 1)
        map_control_layout.addWidget(self.left_btn, 1, 0)
        map_control_layout.addWidget(self.right_btn, 1, 2)
        map_control_layout.addWidget(self.down_btn, 2, 1)
        map_control_layout.addWidget(self.zoom_in_btn, 0, 3)
        map_control_layout.addWidget(self.zoom_out_btn, 1, 3)
        map_control_layout.addWidget(self.recapture_btn, 2, 3)
        
        # 中间: 坐标定位
        coord_group = QGroupBox(tr('coordinate_location', '坐标定位'))
        coord_layout = QGridLayout(coord_group)
        
        coord_layout.addWidget(QLabel(tr('game_x_coordinate', '游戏X坐标:')), 0, 0)
        self.x_coord_input = QLineEdit()
        coord_layout.addWidget(self.x_coord_input, 0, 1)
        
        coord_layout.addWidget(QLabel(tr('game_y_coordinate', '游戏Y坐标:')), 1, 0)
        self.y_coord_input = QLineEdit()
        coord_layout.addWidget(self.y_coord_input, 1, 1)
        
        self.jump_btn = QPushButton(tr('jump_to_coordinate', '跳转到坐标'))
        coord_layout.addWidget(self.jump_btn, 2, 0, 1, 2)
        
        # SVG路线控制已移到独立区域，这里不再重复创建
        
        # 右侧: 校准功能
        calib_group = QGroupBox(tr('calibration_function', '校准功能'))
        calib_layout = QVBoxLayout(calib_group)
        
        self.calibration_btn = QPushButton(tr('start_map_calibration', '启动地图校准'))
        self.calibration_status_label = QLabel(tr('calibration_status_not_calibrated', '校准状态: 未校准'))
        
        # 地图追踪功能（隐藏UI但保留功能，默认开启）
        # self.tracking_btn = QPushButton("开始地图追踪")
        # self.tracking_btn.clicked.connect(self.toggle_map_tracking)
        # self.tracking_btn.setStyleSheet("QPushButton { background-color: #28a745; color: white; } QPushButton:checked { background-color: #dc3545; }")
        # self.tracking_btn.setCheckable(True)
        
        # self.tracking_status_label = QLabel("追踪状态: 未启动")
        # self.tracking_status_label.setStyleSheet("font-size: 11px; color: #666;")
        
        # 当前位置显示
        self.current_position_label = QLabel(tr('current_position_unknown', '当前位置: 未知'))
        self.current_position_label.setStyleSheet("font-size: 10px; color: #555; background-color: #f8f9fa; padding: 2px; border: 1px solid #dee2e6;")
        
        # OCR坐标识别功能
        if OCR_AVAILABLE:
            self.ocr_control_btn = QPushButton(tr('ocr_coordinate_recognition', 'OCR坐标识别'))
            self.ocr_control_btn.clicked.connect(self.show_ocr_control_panel)
            calib_layout.addWidget(self.ocr_control_btn)
            
            # OCR开始/停止识别按钮
            ocr_btn_layout = QHBoxLayout()
            
            self.ocr_start_btn = QPushButton(tr('start_recognition', '开始识别'))
            self.ocr_start_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 12px;
                    font-weight: bold;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:disabled {
                    background-color: #cccccc;
                    color: #666666;
                }
            """)
            self.ocr_start_btn.clicked.connect(self.start_ocr_recognition)
            ocr_btn_layout.addWidget(self.ocr_start_btn)
            
            self.ocr_stop_btn = QPushButton(tr('stop_recognition', '停止识别'))
            self.ocr_stop_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 12px;
                    font-weight: bold;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #da190b;
                }
                QPushButton:disabled {
                    background-color: #cccccc;
                    color: #666666;
                }
            """)
            self.ocr_stop_btn.clicked.connect(self.stop_ocr_recognition)
            self.ocr_stop_btn.setEnabled(False)
            ocr_btn_layout.addWidget(self.ocr_stop_btn)
            
            calib_layout.addLayout(ocr_btn_layout)
            
            # OCR区域校准按钮
            self.ocr_region_btn = QPushButton(tr('calibrate_ocr_region', '校准OCR区域'))
            self.ocr_region_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 12px;
                    font-weight: bold;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #1976D2;
                }
                QPushButton:disabled {
                    background-color: #cccccc;
                    color: #666666;
                }
            """)
            self.ocr_region_btn.clicked.connect(self.setup_ocr_region)
            calib_layout.addWidget(self.ocr_region_btn)
            
            self.ocr_status_label = QLabel(tr('ocr_status_not_started', 'OCR状态: 未启动'))
            self.ocr_status_label.setStyleSheet("font-size: 11px; color: #666;")
            calib_layout.addWidget(self.ocr_status_label)
            
            # 覆盖层控制组
            overlay_group = QGroupBox(tr('center_point_settings', '中心圆点设置'))
            overlay_layout = QGridLayout(overlay_group)
            
            # 圆点大小调整
            overlay_layout.addWidget(QLabel(tr('circle_size', '圆点大小:')), 0, 0)
            self.circle_size_spinbox = QSpinBox()
            self.circle_size_spinbox.setRange(1, 50)
            self.circle_size_spinbox.setValue(5)
            self.circle_size_spinbox.setSuffix(" px")
            self.circle_size_spinbox.valueChanged.connect(self.on_circle_size_changed)
            overlay_layout.addWidget(self.circle_size_spinbox, 0, 1)
            
            # Z轴颜色映射开关（隐藏UI但保留功能，默认开启）
            self.z_color_mapping_checkbox = QCheckBox(tr('enable_z_axis_color_mapping', '启用Z轴颜色映射'))
            self.z_color_mapping_checkbox.setChecked(True)
            self.z_color_mapping_checkbox.toggled.connect(self.on_z_color_mapping_toggled)
            # overlay_layout.addWidget(self.z_color_mapping_checkbox, 1, 0, 1, 2)  # 隐藏UI
            
            # 覆盖层显示开关（隐藏UI但保留功能，默认开启）
            self.overlay_visible_checkbox = QCheckBox(tr('show_center_point', '显示中心圆点'))
            self.overlay_visible_checkbox.setChecked(True)
            self.overlay_visible_checkbox.toggled.connect(self.on_overlay_visibility_toggled)
            # overlay_layout.addWidget(self.overlay_visible_checkbox, 2, 0, 1, 2)  # 隐藏UI
            
            calib_layout.addWidget(overlay_group)
            
            # 路线录制控制组
            if ROUTE_RECORDER_AVAILABLE:
                recording_group = QGroupBox(tr('route_recording', '路线录制'))
                recording_layout = QGridLayout(recording_group)
                
                # 路线名称输入
                recording_layout.addWidget(QLabel(tr('route_name', '路线名称:')), 0, 0)
                self.route_name_input = QLineEdit()
                self.route_name_input.setPlaceholderText(tr('auto_generate_name_placeholder', '留空将自动生成名称'))
                recording_layout.addWidget(self.route_name_input, 0, 1, 1, 2)
                
                # 录制控制按钮
                self.start_recording_btn = QPushButton(tr('start_recording', '开始录制'))
                self.start_recording_btn.clicked.connect(self.start_route_recording)
                self.start_recording_btn.setStyleSheet("QPushButton { background-color: #28a745; color: white; }")
                recording_layout.addWidget(self.start_recording_btn, 1, 0)
                
                self.stop_recording_btn = QPushButton(tr('stop_recording', '停止录制'))
                self.stop_recording_btn.clicked.connect(self.stop_route_recording)
                self.stop_recording_btn.setEnabled(False)
                self.stop_recording_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; }")
                recording_layout.addWidget(self.stop_recording_btn, 1, 1)
                
                self.view_routes_btn = QPushButton(tr('view_routes', '查看路线'))
                self.view_routes_btn.clicked.connect(self.show_recorded_routes)
                recording_layout.addWidget(self.view_routes_btn, 1, 2)
                
                # 录制状态显示
                self.recording_status_label = QLabel(tr('recording_status_not_recording', '录制状态: 未录制'))
                self.recording_status_label.setStyleSheet("font-size: 11px; color: #666;")
                recording_layout.addWidget(self.recording_status_label, 2, 0, 1, 3)
                
                calib_layout.addWidget(recording_group)
        
        # 登录状态信息按钮
        self.login_status_btn = QPushButton(tr('view_login_status', '查看登录状态'))
        self.login_status_btn.clicked.connect(self.show_login_status)
        
        calib_layout.addWidget(self.calibration_btn)
        calib_layout.addWidget(self.calibration_status_label)
        # calib_layout.addWidget(self.tracking_btn)       # 隐藏追踪按钮
        # calib_layout.addWidget(self.tracking_status_label)  # 隐藏追踪状态
        calib_layout.addWidget(self.current_position_label)
        calib_layout.addWidget(self.login_status_btn)
        
        # SVG路线控制区域（从坐标定位组中独立出来）
        svg_group = QGroupBox(tr('svg_route_control', 'SVG路线控制'))
        svg_layout = QGridLayout(svg_group)
        
        # SVG路线导入按钮
        self.import_svg_btn = QPushButton(tr('import_svg_route', '导入SVG路线'))
        self.import_svg_btn.setStyleSheet("QPushButton { background-color: #17a2b8; color: white; }")
        svg_layout.addWidget(self.import_svg_btn, 0, 0, 1, 2)
        
        # 清除路线按钮
        self.clear_svg_btn = QPushButton(tr('clear_current_route', '清除当前路线'))
        self.clear_svg_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; }")
        self.clear_svg_btn.setEnabled(False)  # 初始状态禁用
        svg_layout.addWidget(self.clear_svg_btn, 1, 0, 1, 2)
        
        # 当前路线名称显示
        svg_layout.addWidget(QLabel(tr('current_route', '当前路线:')), 2, 0)
        self.current_route_label = QLabel(tr('none', '无'))
        self.current_route_label.setStyleSheet("QLabel { color: #666; background-color: #f8f9fa; padding: 2px 4px; border: 1px solid #dee2e6; border-radius: 3px; max-height: 20px; }")
        svg_layout.addWidget(self.current_route_label, 2, 1)
        
        # 强制重捕获按钮添加到SVG路线控制组下方
        self.recapture_btn = QPushButton(tr('force_recapture', '强制重捕获'))
        self.recapture_btn.setStyleSheet("QPushButton { background-color: #ffc107; color: #212529; font-weight: bold; }")
        svg_layout.addWidget(self.recapture_btn, 3, 0, 1, 2)
        
        # 窗口控制选项（4个勾选框横向排列）
        checkbox_layout = QHBoxLayout()
        
        self.map_topmost_checkbox = QCheckBox(tr('map_topmost', '地图顶置'))
        self.map_topmost_checkbox.toggled.connect(self.toggle_map_topmost)
        checkbox_layout.addWidget(self.map_topmost_checkbox)
        
        self.map_passthrough_checkbox = QCheckBox(tr('mouse_passthrough', '鼠标穿透'))
        self.map_passthrough_checkbox.toggled.connect(self.toggle_map_passthrough)
        checkbox_layout.addWidget(self.map_passthrough_checkbox)
        
        self.map_frameless_checkbox = QCheckBox(tr('frameless_mode', '无边框模式'))
        self.map_frameless_checkbox.toggled.connect(self.toggle_map_frameless)
        checkbox_layout.addWidget(self.map_frameless_checkbox)
        
        self.main_topmost_checkbox = QCheckBox(tr('main_interface_topmost', '主界面顶置'))
        self.main_topmost_checkbox.toggled.connect(self.toggle_main_topmost)
        checkbox_layout.addWidget(self.main_topmost_checkbox)
        
        svg_layout.addLayout(checkbox_layout, 4, 0, 1, 2)
        
        # 透明度控制（滑块和百分比紧挨着）
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel(tr('opacity', '透明度:')))
        
        self.map_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.map_opacity_slider.setRange(10, 100)  # 10%-100%
        self.map_opacity_slider.setValue(100)
        self.map_opacity_slider.valueChanged.connect(self.on_map_opacity_changed)
        opacity_layout.addWidget(self.map_opacity_slider)
        
        self.map_opacity_label = QLabel("100%")
        opacity_layout.addWidget(self.map_opacity_label)
        
        svg_layout.addLayout(opacity_layout, 5, 0, 1, 2)
        
        # 组装控制面板 - 只保留SVG路线控制和校准功能
        control_layout.addWidget(svg_group)           # SVG路线控制（包含所有功能）
        control_layout.addWidget(calib_group)
        
        # 日志区域 - 先创建，因为持久化系统需要使用
        log_layout = QVBoxLayout()
        log_layout.addWidget(QLabel(tr('capture_and_event_log', '捕获与事件日志:')))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_area.setMaximumHeight(200)
        log_layout.addWidget(self.log_area)
        
        # 地图视图 - 设置持久化存储 (在log_area创建后)
        self.setup_persistent_login_system()
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        
        # 组装主布局（纯控制台界面，不显示WebView）
        main_layout.addLayout(top_layout)
        main_layout.addLayout(status_layout)
        main_layout.addWidget(self.map_status_label)
        main_layout.addWidget(self.server_status_label)
        main_layout.addLayout(control_layout)
        # WebView不在主窗口显示，仅在独立窗口中显示
        main_layout.addLayout(log_layout)
        
        # 初始化透明覆盖层
        self.setup_overlay_manager()

    def setup_persistent_login_system(self):
        """设置完整的登录状态持久化系统 - 三种方法结合确保100%保存"""
        import os
        
        # 1. QWebEngineProfile 持久化存储
        script_dir = os.path.dirname(os.path.abspath(__file__))
        profile_dir = os.path.join(script_dir, "web_profile")
        
        # 确保目录存在
        os.makedirs(profile_dir, exist_ok=True)
        os.makedirs(os.path.join(profile_dir, "cache"), exist_ok=True)
        
        # 创建持久化配置文件
        self.web_profile = QWebEngineProfile("WutheringWavesNavigator", self)
        self.web_profile.setPersistentStoragePath(profile_dir)
        self.web_profile.setCachePath(os.path.join(profile_dir, "cache"))
        
        # 启用持久化存储选项
        self.web_profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.web_profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        
        # 创建使用持久化配置的页面
        self.web_page = QWebEnginePage(self.web_profile, self)
        
        # 创建web view并设置页面
        self.web_view = QWebEngineView()
        self.web_view.setPage(self.web_page)
        
        # 2. 浏览器历史URL记录管理
        self.setup_url_history_manager()
        
        # 3. Cookie和本地存储增强
        self.setup_enhanced_storage()
        
        self.safe_log("✓ 登录状态持久化系统已启用 (Profile + History + Enhanced Storage)")

    def safe_log(self, message):
        """安全的日志记录方法，如果log_area未初始化则使用print"""
        try:
            if hasattr(self, 'log_area') and self.log_area:
                self.log(message)
            else:
                print(f"[INIT] {message}")
        except Exception as e:
            print(f"[LOG ERROR] {message} (Error: {e})")

    def setup_url_history_manager(self):
        """设置URL历史记录管理器"""
        import os
        import json
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.history_file = os.path.join(script_dir, "login_history.json")
        
        # 加载历史记录
        self.login_history = self.load_login_history()
        
        # 监听URL变化
        self.web_view.urlChanged.connect(self.on_url_changed_for_history)
        
        self.safe_log("✓ URL历史记录管理器已初始化")

    def setup_enhanced_storage(self):
        """设置增强的Cookie和本地存储管理"""
        # 注入JavaScript来增强本地存储
        storage_script = """
        // 增强本地存储管理
        (function() {
            // 扩展sessionStorage为localStorage
            const originalSetItem = sessionStorage.setItem;
            sessionStorage.setItem = function(key, value) {
                localStorage.setItem(key, value);
                return originalSetItem.call(this, key, value);
            };
            
            // 保存所有表单数据
            function saveFormData() {
                const forms = document.querySelectorAll('form');
                forms.forEach((form, index) => {
                    const formData = {};
                    const inputs = form.querySelectorAll('input, select, textarea');
                    inputs.forEach(input => {
                        if (input.type !== 'password' && input.value) {
                            formData[input.name || input.id || index] = input.value;
                        }
                    });
                    if (Object.keys(formData).length > 0) {
                        localStorage.setItem(`form_${index}_${location.hostname}`, JSON.stringify(formData));
                    }
                });
            }
            
            // 恢复表单数据
            function restoreFormData() {
                const forms = document.querySelectorAll('form');
                forms.forEach((form, index) => {
                    const savedData = localStorage.getItem(`form_${index}_${location.hostname}`);
                    if (savedData) {
                        try {
                            const formData = JSON.parse(savedData);
                            Object.keys(formData).forEach(key => {
                                const input = form.querySelector(`[name="${key}"], [id="${key}"]`);
                                if (input && input.type !== 'password') {
                                    input.value = formData[key];
                                }
                            });
                        } catch(e) {}
                    }
                });
            }
            
            // 监听页面加载和表单变化
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', restoreFormData);
            } else {
                restoreFormData();
            }
            
            // 定期保存表单数据
            setInterval(saveFormData, 5000);
            
            // 在页面卸载前保存
            window.addEventListener('beforeunload', saveFormData);
            
            console.log('Enhanced storage system activated');
        })();
        """
        
        # 页面加载完成后注入脚本
        self.web_page.loadFinished.connect(lambda: self.web_page.runJavaScript(storage_script))
        
        self.safe_log("✓ 增强存储系统已配置")

    def load_login_history(self):
        """加载登录历史记录"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.safe_log(f"加载历史记录失败: {e}")
        return {"visited_urls": [], "login_domains": [], "last_login_time": {}}

    def save_login_history(self):
        """保存登录历史记录"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.login_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.safe_log(f"保存历史记录失败: {e}")

    def on_url_changed_for_history(self, url):
        """URL变化时更新历史记录"""
        url_str = url.toString()
        
        # 记录访问的URL
        if url_str not in self.login_history["visited_urls"]:
            self.login_history["visited_urls"].append(url_str)
            # 只保留最近50个URL
            if len(self.login_history["visited_urls"]) > 50:
                self.login_history["visited_urls"] = self.login_history["visited_urls"][-50:]
        
        # 检测可能的登录页面
        login_indicators = ["login", "signin", "auth", "passport", "account"]
        if any(indicator in url_str.lower() for indicator in login_indicators):
            domain = url.host()
            if domain and domain not in self.login_history["login_domains"]:
                self.login_history["login_domains"].append(domain)
                self.login_history["last_login_time"][domain] = QDateTime.currentDateTime().toString()
                self.safe_log(f"✓ 检测到登录页面: {domain}")
        
        # 保存历史记录
        self.save_login_history()

    def restore_last_session(self):
        """恢复上次会话 - 修改为强制使用官方地图"""
        # 不再恢复上次会话，始终使用官方地图
        self.safe_log("✓ 跳过会话恢复，使用默认官方地图")
        return False

    def safe_load_calibration(self):
        """安全加载校准数据"""
        try:
            self.load_calibration_for_current_map()
        except Exception as e:
            self.log(f"安全加载校准数据失败: {e}")
    
    def safe_restore_session(self):
        """安全恢复会话"""
        try:
            self.restore_last_session()
        except Exception as e:
            self.log(f"安全恢复会话失败: {e}")
    
    def force_load_official_map(self):
        """强制加载官方地图"""
        try:
            # 确保选中官方地图
            self.radio_online.setChecked(True)
            self.radio_kuro.setChecked(True)
            
            # 直接加载官方地图URL
            current_lang = self.language_manager.get_current_language() if hasattr(self, 'language_manager') else "zh_CN"
            map_urls = get_map_urls(current_lang)
            official_url = map_urls["official_map"]
            
            if self.web_view:
                self.web_view.setUrl(QUrl(official_url))
                self.log(f"✓ 强制加载官方地图: {official_url}")
                
        except Exception as e:
            self.log(f"强制加载官方地图失败: {e}")
    
    def load_app_settings(self):
        """加载应用设置"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"加载设置文件失败: {e}")
            return {}
    
    def save_app_settings(self, settings):
        """保存应用设置"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存设置文件失败: {e}")
    
    def is_first_time_user(self):
        """检查是否首次使用"""
        settings = self.load_app_settings()
        return not settings.get('disclaimer_accepted', False)
    
    def mark_disclaimer_accepted(self):
        """标记免责声明已接受"""
        settings = self.load_app_settings()
        settings['disclaimer_accepted'] = True
        settings['first_run_date'] = datetime.now().isoformat()
        self.save_app_settings(settings)
    
    def show_disclaimer_dialog(self):
        """显示免责声明对话框"""
        if self.is_first_time_user():
            dialog = DisclaimerDialog(self)
            result = dialog.exec()
            
            if result == QDialog.Accepted:
                # 用户同意条款
                self.mark_disclaimer_accepted()
                self.log("✓ 用户已同意使用条款")
                return True
            else:
                # 用户拒绝条款，退出程序
                self.log("用户拒绝使用条款，程序退出")
                return False
        return True  # 已经同意过条款
    
    def check_disclaimer_on_startup(self):
        """启动时检查免责声明"""
        if not self.show_disclaimer_dialog():
            # 用户拒绝条款，关闭程序
            QTimer.singleShot(100, self.close)
            return
        
        # 用户同意条款，继续正常启动流程
        self.continue_startup()
    
    def continue_startup(self):
        """继续启动流程（在免责声明检查后）"""
        # 确保默认选择官方地图（每次启动时强制设置）
        self.radio_online.setChecked(True)  # 确保在线模式被选中
        self.radio_kuro.setChecked(True)    # 确保官方地图被选中
        
        # 初始加载在线模式
        self.on_mode_changed()
        
        # 启动后延迟加载校准数据和恢复会话
        QTimer.singleShot(2000, self.safe_load_calibration)
        QTimer.singleShot(1000, self.safe_restore_session)
        
        # 确保官方地图被加载（在会话恢复后再次强制）
        QTimer.singleShot(1500, self.force_load_official_map)
        
        # 启动后自动分离地图窗口
        QTimer.singleShot(3000, self.auto_separate_map_window)
        
        # 启动地图追踪（默认开启）
        QTimer.singleShot(4000, self.start_default_tracking)
    
    def start_local_servers(self):
        """启动本地服务器（在初始化时调用）"""
        try:
            if hasattr(self, 'server_status_label'):
                self.server_status_label.setText("服务器状态: 启动中...")
                self.server_status_label.setStyleSheet("color: orange;")
            
            self.safe_log("正在启动本地图片服务器...")
            self.safe_log("- Flask + WebSocket 服务器 (端口: 8080)")
            self.safe_log("- HTTP 文件服务器 (端口: 8000)")
            
            if self.server_manager.start_servers():
                self.safe_log("✓ 本地图片服务器启动成功")
                self.safe_log("- 本地地图访问地址: http://localhost:8000/index.html")
                
                if hasattr(self, 'server_status_label'):
                    self.server_status_label.setText("服务器状态: 运行中 ✓")
                    self.server_status_label.setStyleSheet("color: green;")
                
                # 更新本地地图列表
                self.update_local_map_list()
            else:
                self.safe_log("⚠ 本地图片服务器启动失败")
                if hasattr(self, 'server_status_label'):
                    self.server_status_label.setText("服务器状态: 启动失败 ✗")
                    self.server_status_label.setStyleSheet("color: red;")
        except Exception as e:
            self.safe_log(f"启动本地服务器时出错: {e}")
            if hasattr(self, 'server_status_label'):
                self.server_status_label.setText("服务器状态: 错误 ✗")
                self.server_status_label.setStyleSheet("color: red;")
            import traceback
            traceback.print_exc()

    def get_login_status_info(self):
        """获取登录状态信息"""
        try:
            info = {
                "profile_dir": self.web_profile.persistentStoragePath() if hasattr(self, 'web_profile') else "N/A",
                "cache_dir": self.web_profile.cachePath() if hasattr(self, 'web_profile') else "N/A",
                "total_urls": len(self.login_history.get("visited_urls", [])),
                "login_domains": len(self.login_history.get("login_domains", [])),
                "last_domains": list(self.login_history.get("last_login_time", {}).keys())[-3:] if self.login_history.get("last_login_time") else []
            }
            return info
        except Exception as e:
            self.log(f"获取登录状态信息失败: {e}")
            return {"error": str(e)}

    def show_login_status(self):
        """显示登录状态信息"""
        try:
            info = self.get_login_status_info()
            status_text = f"""
登录状态持久化信息:

🔧 Profile存储目录: {info['profile_dir']}
💾 缓存目录: {info['cache_dir']}
📊 访问URL总数: {info['total_urls']}
🌐 登录域名数: {info['login_domains']}
🕒 最近登录域名: {', '.join(info['last_domains']) if info['last_domains'] else '无'}

系统状态: ✅ 全功能登录状态保存已启用
- QWebEngineProfile持久化存储 ✅
- URL历史记录管理 ✅  
- 增强Cookie和本地存储 ✅
            """
            QMessageBox.information(self, "登录状态信息", status_text)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"获取登录状态失败: {e}")

    def load_calibration_for_current_map(self):
        """为当前地图加载已保存的校准数据"""
        try:
            if self.current_mode == 'online':
                provider_name = self.radio_online_map_group.checkedButton().text()
                area_id = self.current_area_id
                transform_matrix = self.calibration_manager.load_calibration(
                    'online', provider_name, area_id
                )
            else:
                if (self.local_map_combo.count() > 0 and 
                    "无可用" not in self.local_map_combo.currentText()):
                    map_name = self.local_map_combo.currentText()
                    transform_matrix = self.calibration_manager.load_calibration(
                        'local', map_name
                    )
                else:
                    return
            
            if transform_matrix:
                self.transform_matrix = transform_matrix
                self.calibration_status_label.setText("校准状态: 已加载")
                self.jump_btn.setEnabled(True)
                self.log("已自动加载校准数据")
            else:
                self.calibration_status_label.setText("校准状态: 未校准")
                self.jump_btn.setEnabled(False)
                
        except Exception as e:
            self.log(f"加载校准数据时出错: {e}")

    def save_current_calibration(self):
        """保存当前地图的校准数据"""
        if not self.transform_matrix:
            self.log("⚠️ 无变换矩阵，无法保存校准数据")
            return False
            
        try:
            if self.current_mode == 'online':
                provider_name = self.radio_online_map_group.checkedButton().text()
                area_id = self.current_area_id
                self.log(f"📝 准备保存在线地图校准数据: 提供商={provider_name}, 区域ID={area_id}")
                success = self.calibration_manager.save_calibration(
                    'online', provider_name, self.transform_matrix, area_id
                )
            else:
                if (self.local_map_combo.count() > 0 and 
                    "无可用" not in self.local_map_combo.currentText()):
                    map_name = self.local_map_combo.currentText()
                    self.log(f"📝 准备保存本地地图校准数据: 地图名={map_name}")
                    success = self.calibration_manager.save_calibration(
                        'local', map_name, self.transform_matrix
                    )
                else:
                    self.log("⚠️ 没有可用的本地地图")
                    return False
            
            if success:
                self.log("✅ 校准数据已自动保存")
            else:
                self.log("❌ 校准数据保存失败")
            return success
            
        except Exception as e:
            self.log(f"❌ 保存校准数据时出错: {e}")
            import traceback
            self.log(f"错误详情: {traceback.format_exc()}")
            return False

    def setup_web_channel(self):
        try:
            self.backend = MapBackend(self)
            self.channel = QWebChannel()
            
            # 检查web_page是否有效
            if not hasattr(self, 'web_page') or not self.web_page:
                self.log("错误：web_page未初始化")
                return False
                
            self.web_page.setWebChannel(self.channel)
            self.channel.registerObject("backend", self.backend)
            self.backend.statusUpdated.connect(self.on_map_status_updated)
            self.log("QWebChannel设置完成")
            return True
            
        except Exception as e:
            self.log(f"QWebChannel设置失败: {e}")
            return False

    def connect_signals(self):
        # --- 新增模式切换信号 ---
        self.radio_mode_group.buttonClicked.connect(self.on_mode_changed)

        # 地图选择 (现在是分模式的)
        self.radio_online_map_group.buttonClicked.connect(self.load_current_map)
        self.local_map_combo.currentIndexChanged.connect(self.load_current_map)
        self.add_map_btn.clicked.connect(self.add_local_maps)
        self.delete_map_btn.clicked.connect(self.delete_local_map)
        
        self.web_view.urlChanged.connect(self.on_url_changed)
        # --- 修改 loadFinished 的连接目标 ---
        self.web_view.loadFinished.connect(self.on_page_load_finished)
        
        # 地图控制信号连接（由于UI组件被隐藏，这些信号连接被注释掉）
        # self.up_btn.clicked.connect(lambda: self.pan_map_direction("north"))
        # self.down_btn.clicked.connect(lambda: self.pan_map_direction("south"))
        # self.left_btn.clicked.connect(lambda: self.pan_map_direction("west"))
        # self.right_btn.clicked.connect(lambda: self.pan_map_direction("east"))
        # self.zoom_in_btn.clicked.connect(self.zoom_in_map)
        # self.zoom_out_btn.clicked.connect(self.zoom_out_map)
        self.recapture_btn.clicked.connect(self.trigger_capture_sequence)  # 恢复强制重捕获
        
        # 坐标跳转信号连接（由于UI组件被隐藏，这些信号连接被注释掉）
        # self.jump_btn.clicked.connect(self.jump_to_coordinates)
        
        # SVG路线导入信号连接（已独立显示）
        self.import_svg_btn.clicked.connect(self.import_svg_route)
        
        # SVG路线清除信号连接（已独立显示）
        self.clear_svg_btn.clicked.connect(self.clear_svg_route)
        
        # 校准功能
        self.calibration_btn.clicked.connect(self.open_calibration_window)

    def log(self, message):
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            if hasattr(self, 'log_area') and self.log_area:
                self.log_area.append(f"[{timestamp}] {message}")
                # 自动滚动到最后
                cursor = self.log_area.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.log_area.setTextCursor(cursor)
                self.log_area.ensureCursorVisible()
            else:
                # 如果log_area不可用，回退到控制台输出
                print(f"[{timestamp}] {message}")
        except Exception as e:
            # 最后的回退，直接输出到控制台
            print(f"[LOG ERROR] {message} (Error: {e})")

    @Slot(bool)
    def on_page_load_finished(self, ok):
        """页面加载完成后的统一处理入口"""
        try:
            if not ok:
                self.log("错误：页面加载失败！")
                self.status_label.setText("状态: 页面加载失败！")
                self.set_buttons_enabled(False)
                return

            # 检查页面和WebView是否仍然有效
            if not self.web_view or not self.web_view.page():
                self.log("警告：WebView或页面对象无效")
                return

            self.log("页面加载完毕，开始注入通用脚本...")
            
            # 步骤1: 安全注入 QWebChannel 基础库
            try:
                self.web_view.page().runJavaScript(QWEBCHANNEL_JS_CONTENT)
            except Exception as e:
                self.log(f"注入QWebChannel失败: {e}")
                return
            
            # 步骤2: 部署QWebChannel基础设施
            self.deploy_event_listeners()
            
            # 步骤3: 根据模式执行特定的捕获/初始化逻辑
            if self.current_mode == 'online':
                self.log("在线模式：启动捕获序列...")
                # 延迟启动捕获序列，确保脚本注入完成
                QTimer.singleShot(300, self.trigger_capture_sequence)
            else:
                self.log("本地模式：初始化完成。等待地图状态反馈...")
                self.status_label.setText("状态: 本地地图已加载")
                self.set_buttons_enabled(True)
                
                # 如果有选择的本地地图，广播切换指令
                if (self.local_map_combo.count() > 0 and 
                    "无可用" not in self.local_map_combo.currentText()):
                    map_name = self.local_map_combo.currentText()
                    self.log(f"自动切换到本地地图: {map_name}")
                    # 稍微延迟以确保WebSocket连接建立
                    def delayed_switch():
                        try:
                            if self.server_manager.is_running():
                                self.server_manager.broadcast_command({
                                    "type": "mapChange", "mapName": map_name, "lat": 0, "lng": 0, "zoom": 0
                                })
                        except Exception as e:
                            self.log(f"本地地图切换失败: {e}")
                    QTimer.singleShot(1000, delayed_switch)
                    
        except Exception as e:
            self.log(f"页面加载处理失败: {e}")
            self.status_label.setText(f"状态: 页面处理失败 - {str(e)}")
            self.set_buttons_enabled(False)

    # 将原来的 inject_webchannel_script 和 bind_map_listeners 合并到 deploy_event_listeners
    def deploy_event_listeners(self):
        self.log("正在部署统一事件监听器...")
        # 此脚本对在线地图和本地地图都兼容
        js_listener_script = """
            // 确保 QWebChannel 已被注入
            if (typeof QWebChannel !== 'undefined') {
                // 短暂延迟以确保页面中的对象（如`qt.webChannelTransport`）已准备就绪
                setTimeout(function() {
                    new QWebChannel(qt.webChannelTransport, function(channel) {
                        window.py_backend = channel.objects.backend;
                        console.log("QWebChannel已连接，后端对象已映射。");
                    });
                }, 200);
            }
        """
        self.web_view.page().runJavaScript(js_listener_script)
    
    def bind_map_listeners(self):
        js_listener_script = """
        window.mapListenersActive = false;
        
        new QWebChannel(qt.webChannelTransport, function(channel) {
            var py_backend = channel.objects.backend;

            if (!window.discoveredMap || typeof window.discoveredMap.getCenter !== 'function') {
                console.warn('地图实例无效，跳过监听器绑定');
                return;
            }

            if (window.mapListenersActive) {
                window.discoveredMap.off('moveend zoomend');
                console.log('已清除旧的事件监听器');
            }

            function send_status_to_python() {
                try {
                    const center = window.discoveredMap.getCenter();
                    const zoom = window.discoveredMap.getZoom();
                    py_backend.updateStatus(center.lat, center.lng, zoom);
                } catch (error) {
                    console.error('发送状态到Python时出错:', error);
                    window.mapListenersActive = false;
                }
            }

            window.discoveredMap.on('moveend zoomend', send_status_to_python);
            window.mapListenersActive = true;
            
            console.log('成功为地图绑定 moveend 和 zoomend 事件！');
            send_status_to_python();
        });
        """
        self.web_view.page().runJavaScript(js_listener_script)
        self.log("事件监听器部署完毕。现在可以实时监控地图状态。")

    @Slot(float, float, int)
    def on_map_status_updated(self, lat, lng, zoom):
        self.map_status_label.setText(f"实时状态: Lat: {lat:.6f}, Lng: {lng:.6f}, Zoom: {zoom}")

    @Slot()
    def on_mode_changed(self):
        try:
            new_mode = "local" if self.radio_local.isChecked() else "online"
            
            # 如果模式没有变化，直接返回
            if hasattr(self, 'current_mode') and self.current_mode == new_mode:
                return
                
            self.log(f"--- 切换到 {new_mode.upper()} 模式 ---")
            
            # 先停止任何正在进行的操作
            if hasattr(self, 'timer') and self.timer.isActive():
                self.timer.stop()
            
            self.current_mode = new_mode
            
            if self.current_mode == 'local':
                self.online_map_group.setVisible(False)
                self.local_map_group.setVisible(True)
                # self.recapture_btn.setEnabled(False)  # 本地模式不需要重捕获（组件已隐藏）
                
                # 检查本地服务器状态（服务器应该已经在运行）
                if not self.server_manager.is_running():
                    self.log("⚠ 本地服务器未运行，尝试重新启动...")
                    self.status_label.setText("状态: 正在重新启动本地服务器...")
                    try:
                        if self.server_manager.start_servers():
                            self.log("✓ 本地服务器重新启动成功")
                        else:
                            raise Exception("服务器重新启动失败")
                    except Exception as e:
                        self.log(f"本地服务器重新启动失败: {e}")
                        QMessageBox.critical(self, "错误", "无法启动本地服务器！请检查端口是否被占用。")
                        self.radio_online.setChecked(True)  # 切换回在线模式
                        self.current_mode = "online"
                        self.online_map_group.setVisible(True)
                        self.local_map_group.setVisible(False)
                        # self.recapture_btn.setEnabled(True)  # 组件已隐藏
                        return
                else:
                    self.log("✓ 本地服务器正在运行")
                        
                self.update_local_map_list()
            else:  # online mode
                self.online_map_group.setVisible(True)
                self.local_map_group.setVisible(False)
                # self.recapture_btn.setEnabled(True)  # 组件已隐藏
            
            # 延迟加载地图，避免界面冲突
            QTimer.singleShot(200, self.load_current_map)
            
        except Exception as e:
            self.log(f"模式切换失败: {e}")
            self.status_label.setText(f"状态: 模式切换失败 - {str(e)}")
            # 恢复到安全状态
            self.set_buttons_enabled(True)

    def update_local_map_list(self):
        self.local_maps = self.server_manager.get_local_maps()
        self.local_map_combo.clear()
        if self.local_maps:
            self.local_map_combo.addItems(self.local_maps)
            self.log(f"已加载 {len(self.local_maps)} 个本地地图")
        else:
            self.log("提示：未找到本地地图。请使用 tile_generator.py 添加地图。")
            self.local_map_combo.addItem("无可用本地地图")

    @Slot()
    def load_current_map(self):
        """根据当前模式和选择加载地图"""
        try:
            self.status_label.setText("状态: 正在加载地图...")
            self.map_status_label.setText("实时状态: 等待数据...")
            
            if self.current_mode == 'online':
                checked_button = self.radio_online_map_group.checkedButton()
                if not checked_button:
                    self.log(tr('warning_no_online_map_provider', '警告：没有选择在线地图提供商'))
                    return
                    
                # 使用按钮对象来获取正确的URL键
                if checked_button == self.radio_kuro:
                    url_key = "official_map"
                    provider_display = tr('radio_online_official', '官方地图')
                elif checked_button == self.radio_ghzs:
                    url_key = "aura_helper"
                    provider_display = tr('radio_online_aura', '光环助手')
                else:
                    self.log(tr('error_unknown_map_provider', '错误：未知的地图提供商'))
                    return
                    
                current_lang = self.language_manager.get_current_language() if hasattr(self, 'language_manager') else "zh_CN"
                map_urls = get_map_urls(current_lang)
                url_to_load = map_urls[url_key]
                self.url_status_label.setText(tr('current_map_status', '当前地图: {provider}', provider=provider_display))
                
                # 安全设置URL
                if self.web_view:
                    self.web_view.setUrl(QUrl(url_to_load))
                    self.log(f"开始加载在线地图: {provider_display}")
                    
            else:  # local mode
                if (self.local_map_combo.count() > 0 and 
                    "无可用" not in self.local_map_combo.currentText()):
                    map_name = self.local_map_combo.currentText()
                    self.url_status_label.setText(f"当前地图: {map_name}")
                    
                    # 检查服务器状态（服务器应该已经在运行）
                    if not self.server_manager.is_running():
                        self.log("⚠ 本地服务器未运行，尝试重新启动...")
                        if not self.server_manager.start_servers():
                            self.status_label.setText("状态: 本地服务器重启失败")
                            return
                        else:
                            self.log("✓ 本地服务器重新启动成功")
                    
                    # 首先确保加载本地地图页面
                    current_url = self.web_view.url().toString() if self.web_view else ""
                    if "localhost:8000/index.html" not in current_url:
                        self.log("加载本地地图页面...")
                        if self.web_view:
                            self.web_view.setUrl(QUrl("http://localhost:8000/index.html"))
                    else:
                        # 页面已加载，直接通知切换地图
                        self.log(f"切换到本地地图: {map_name}")
                        try:
                            self.server_manager.broadcast_command({
                                "type": "mapChange", "mapName": map_name, "lat": 0, "lng": 0, "zoom": 0
                            })
                        except Exception as e:
                            self.log(f"地图切换广播失败: {e}")
                else:
                    self.status_label.setText("状态: 无本地地图可加载")
                    self.log("提示：请先添加本地地图")
            
            # 加载完地图后，尝试加载对应的校准数据
            QTimer.singleShot(500, self.load_calibration_for_current_map)
            
        except Exception as e:
            self.log(f"加载地图失败: {e}")
            self.status_label.setText(f"状态: 地图加载失败 - {str(e)}")
            # 恢复界面状态
            self.set_buttons_enabled(True)

    @Slot(QUrl)
    def on_url_changed(self, url):
        url_string = url.toString()
        
        # 只有在在线模式下才处理URL变化
        if self.current_mode != 'online':
            return
            
        new_area_id = None
        if "kurobbs.com" in url_string:
            parsed_url = urlparse(url_string)
            query_params = parse_qs(parsed_url.query)
            new_area_id = query_params.get('state', [None])[0] or "8"
        elif ("ghzs.com" in url_string or "ghzs666.com" in url_string) and "#/?map=" in url_string:
            try:
                new_area_id = url_string.split('#/?map=')[1]
            except IndexError:
                new_area_id = "default"
        
        if not new_area_id:
            return
            
        self.url_status_label.setText(f"当前区域ID: {new_area_id}")
        if self.current_area_id != new_area_id:
            self.log(f"检测到区域ID切换: {self.current_area_id} -> {new_area_id}")
            self.current_area_id = new_area_id
            self.log("统一策略: 强制重捕获以获取最新的地图实例。")
            self.trigger_capture_sequence()
            # 区域切换后加载对应的校准数据
            QTimer.singleShot(1000, self.load_calibration_for_current_map)

    def trigger_capture_sequence(self):
        try:
            self.log("--- 混合战术捕获序列已启动 ---")
            self.status_label.setText("状态: 正在部署A计划 (构造函数拦截)...")
            self.set_buttons_enabled(False)
            
            # 安全清理现有定时器
            if hasattr(self, 'timer'):
                try:
                    self.timer.stop()
                    self.timer.deleteLater()
                except RuntimeError:
                    pass  # 对象已被删除
            
            reset_script = """
            window.discoveredMap = null; 
            window.mapListenersActive = false;
            if (typeof L !== 'undefined' && L.Map && L.Map.prototype.initialize) {
                L.Map.prototype.initialize._isPatched=false;
            }
            if (typeof L !== 'undefined' && L.Map && L.Map.prototype.setView) {
                L.Map.prototype.setView._isPatchedB=false;
            }
            """
            
            # 安全执行JavaScript
            if self.web_view and self.web_view.page():
                self.web_view.page().runJavaScript(reset_script)
                self.map_status_label.setText("实时状态: 等待捕获...")
            
            self.attempts = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.run_interceptor)
            self.timer.start(100)
            
        except Exception as e:
            self.log(f"捕获序列启动失败: {e}")
            self.status_label.setText("状态: 捕获序列启动失败")
            self.set_buttons_enabled(True)

    def run_interceptor(self):
        try:
            self.attempts += 1
            
            if self.attempts > 20 and self.attempts % 5 == 0:
                self.log("A计划未命中，已自动切换到B计划 (地雷阵)。等待用户交互...")
                self.status_label.setText("状态: A计划未命中，等待用户交互触发B计划...")

            if self.attempts > 200:
                self.log("捕获序列超时，停止尝试")
                self.status_label.setText("状态: 捕获超时！请手动交互地图或点击重捕获")
                if hasattr(self, 'timer') and self.timer.isActive():
                    self.timer.stop()
                self.set_buttons_enabled(True)  # 恢复按钮状态
                return
            
            # 检查WebView和页面是否仍然有效
            if not self.web_view or not self.web_view.page():
                self.log("警告：WebView或页面已无效，停止捕获")
                if hasattr(self, 'timer') and self.timer.isActive():
                    self.timer.stop()
                return
                
            # 安全执行JavaScript
            try:
                self.web_view.page().runJavaScript(JS_HYBRID_INTERCEPTOR)
                self.web_view.page().runJavaScript("!!window.discoveredMap", self.on_interception_result)
            except Exception as js_error:
                self.log(f"JavaScript执行失败: {js_error}")
                # 不立即停止，继续尝试
                
        except Exception as e:
            self.log(f"拦截器运行错误: {e}")
            if hasattr(self, 'timer') and self.timer.isActive():
                self.timer.stop()
            self.set_buttons_enabled(True)

    @Slot(object)
    def on_interception_result(self, success):
        if success:
            provider_name = self.radio_online_map_group.checkedButton().text()
            self.status_label.setText(f"状态: 成功捕获 [{provider_name}] 的逻辑！")
            self.set_buttons_enabled(True)
            self.timer.stop()
            self.log("捕获成功！正在部署事件监听器...")
            self.bind_map_listeners()
    
    def bind_map_listeners(self):
        js_listener_script = """
        window.mapListenersActive = false;
        
        new QWebChannel(qt.webChannelTransport, function(channel) {
            var py_backend = channel.objects.backend;

            if (!window.discoveredMap || typeof window.discoveredMap.getCenter !== 'function') {
                console.warn('地图实例无效，跳过监听器绑定');
                return;
            }

            if (window.mapListenersActive) {
                window.discoveredMap.off('moveend zoomend');
                console.log('已清除旧的事件监听器');
            }

            function send_status_to_python() {
                try {
                    const center = window.discoveredMap.getCenter();
                    const zoom = window.discoveredMap.getZoom();
                    py_backend.updateStatus(center.lat, center.lng, zoom);
                } catch (error) {
                    console.error('发送状态到Python时出错:', error);
                    window.mapListenersActive = false;
                }
            }

            window.discoveredMap.on('moveend zoomend', send_status_to_python);
            window.mapListenersActive = true;
            
            console.log('成功为地图绑定 moveend 和 zoomend 事件！');
            send_status_to_python();
        });
        """
        self.web_view.page().runJavaScript(js_listener_script)
        self.log("事件监听器部署完毕。现在可以实时监控地图状态。")

    def set_buttons_enabled(self, enabled):
        try:
            # 只设置仍然显示的按钮状态（隐藏的按钮不再设置）
            buttons = [
                # ('up_btn', enabled),          # 已隐藏
                # ('down_btn', enabled),        # 已隐藏
                # ('left_btn', enabled),        # 已隐藏
                # ('right_btn', enabled),       # 已隐藏
                # ('zoom_in_btn', enabled),     # 已隐藏
                # ('zoom_out_btn', enabled),    # 已隐藏
                # ('jump_btn', enabled and self.transform_matrix is not None),  # 已隐藏
                ('recapture_btn', enabled and getattr(self, 'current_mode', 'online') == 'online'),  # 恢复显示
                ('calibration_btn', True)  # 校准按钮始终可用
            ]
            
            for btn_name, btn_enabled in buttons:
                if hasattr(self, btn_name):
                    btn = getattr(self, btn_name)
                    if btn:
                        btn.setEnabled(btn_enabled)
                        
        except Exception as e:
            self.log(f"设置按钮状态错误: {e}")

    # --- 统一控制逻辑 ---
    def pan_map_direction(self, direction):
        try:
            self.log(f"执行方向移动: {direction}")
            if self.current_mode == 'online':
                # 在线模式
                direction_scripts = {
                    "north": "window.discoveredMap.panBy([0, -50]);",
                    "south": "window.discoveredMap.panBy([0, 50]);",
                    "west": "window.discoveredMap.panBy([-50, 0]);",
                    "east": "window.discoveredMap.panBy([50, 0]);"
                }
                if direction in direction_scripts and self.web_view and self.web_view.page():
                    self.web_view.page().runJavaScript(f"if(window.discoveredMap){{{direction_scripts[direction]}}}")
                else:
                    self.log(f"无效的方向或WebView不可用: {direction}")
            else:  # local mode
                # 本地模式通过广播指令
                move_steps = {"north": -50, "south": 50, "west": -50, "east": 50}
                if direction in move_steps:
                    if direction in ["north", "south"]:
                        command = {"type": "panBy", "y": move_steps[direction]}
                    else:
                        command = {"type": "panBy", "x": move_steps[direction]}
                    
                    if not self.server_manager.broadcast_command(command):
                        self.log("本地地图移动失败，请检查服务器状态")
                else:
                    self.log(f"无效的移动方向: {direction}")
        except Exception as e:
            self.log(f"地图移动错误: {e}")

    def zoom_in_map(self):
        try:
            if self.current_mode == 'online':
                if self.web_view and self.web_view.page():
                    self.web_view.page().runJavaScript("if(window.discoveredMap) { window.discoveredMap.zoomIn(); }")
                    self.log("在线地图放大")
                else:
                    self.log("WebView不可用，无法放大")
            else:
                if not self.server_manager.broadcast_command({"type": "zoomIn"}):
                    self.log("本地地图放大失败")
                else:
                    self.log("本地地图放大")
        except Exception as e:
            self.log(f"地图放大错误: {e}")

    def zoom_out_map(self):
        try:
            if self.current_mode == 'online':
                if self.web_view and self.web_view.page():
                    self.web_view.page().runJavaScript("if(window.discoveredMap) { window.discoveredMap.zoomOut(); }")
                    self.log("在线地图缩小")
                else:
                    self.log("WebView不可用，无法缩小")
            else:
                if not self.server_manager.broadcast_command({"type": "zoomOut"}):
                    self.log("本地地图缩小失败")
                else:
                    self.log("本地地图缩小")
        except Exception as e:
            self.log(f"地图缩小错误: {e}")

    def jump_to_coordinates(self):
        try:
            if self.transform_matrix is None:
                QMessageBox.warning(self, "校准未完成", "请先完成地图校准！")
                return

            # 验证输入
            try:
                x = float(self.x_coord_input.text().strip())
                y = float(self.y_coord_input.text().strip())
            except (ValueError, AttributeError):
                QMessageBox.warning(self, "输入错误", "请输入有效的数值坐标！")
                return

            # 坐标转换
            try:
                lat, lon = CalibrationSystem.transform(x, y, self.transform_matrix)
            except Exception as transform_error:
                QMessageBox.critical(self, "转换失败", f"坐标转换失败: {str(transform_error)}")
                return
            
            # 执行跳转（保持原有逻辑）
            success = False
            if self.current_mode == 'online':
                # 在线地图使用JavaScript跳转
                if self.web_view and self.web_view.page():
                    js_code = f"if(window.discoveredMap) {{ window.discoveredMap.panTo([{lat}, {lon}]); }}"
                    self.web_view.page().runJavaScript(js_code)
                    success = True
                    self.log(f"在线地图跳转: ({x}, {y}) -> ({lat:.6f}, {lon:.6f})")
                else:
                    QMessageBox.warning(self, "跳转失败", "WebView不可用，无法跳转")
            else:
                # 本地地图通过WebSocket广播跳转指令
                command = {
                    "type": "jumpTo",
                    "lat": lat,
                    "lng": lon
                }
                if self.server_manager.broadcast_command(command):
                    success = True
                    self.log(f"本地地图跳转: ({x}, {y}) -> ({lat:.6f}, {lon:.6f})")
                else:
                    QMessageBox.warning(self, "跳转失败", "本地服务器不可用，无法跳转")
            
            if success:
                # 清空输入框
                self.x_coord_input.clear()
                self.y_coord_input.clear()
            
        except Exception as e:
            self.log(f"跳转坐标发生错误: {e}")
            QMessageBox.critical(self, "跳转失败", f"跳转操作失败: {str(e)}")

    def open_calibration_window(self):
        # 获取当前选择的地图提供商和实际URL
        if self.current_mode == 'online':
            current_provider = self.radio_online_map_group.checkedButton().text()
            area_id = self.current_area_id
            has_existing = self.calibration_manager.has_calibration('online', current_provider, area_id)
            current_url = self.web_view.url().toString()
        else:
            current_provider = "本地地图"
            if (self.local_map_combo.count() > 0 and 
                "无可用" not in self.local_map_combo.currentText()):
                map_name = self.local_map_combo.currentText()
                has_existing = self.calibration_manager.has_calibration('local', map_name)
                # 对于本地地图，确保传递正确的URL
                current_url = "http://localhost:8000/index.html"
            else:
                QMessageBox.warning(self, "警告", "请先选择一个有效的本地地图")
                return
        
        # 如果已有校准数据，询问用户是否覆盖
        if has_existing:
            reply = QMessageBox.question(
                self, 
                "校准数据存在", 
                "当前地图已有校准数据，是否要重新校准？\n新的校准数据会覆盖原有数据。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        self.log(f"启动校准窗口 - 提供商: {current_provider}, 当前URL: {current_url}")
        
        calibration_window = CalibrationWindow(self, current_provider, current_url)
        calibration_window.calibrationFinished.connect(self.on_calibration_finished)
        calibration_window.exec()

    @Slot(object)
    def on_calibration_finished(self, transform_matrix):
        self.transform_matrix = transform_matrix
        self.calibration_status_label.setText("校准状态: 已完成")
        # self.jump_btn.setEnabled(True)  # jump_btn已隐藏，不再设置
        self.log("地图校准完成！现在可以使用坐标跳转功能。")
        
        # 自动保存校准数据
        if self.save_current_calibration():
            self.log("校准数据已保存，下次打开此地图时会自动加载。")
        else:
            self.log("⚠️ 校准数据保存失败！")

    def add_local_maps(self):
        """添加本地地图功能"""
        # 打开文件选择对话框
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择地图图片文件",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.tiff *.tif);;所有文件 (*)"
        )
        
        if not file_paths:
            return
            
        self.log(f"准备处理 {len(file_paths)} 个地图文件...")
        
        # 创建进度对话框
        self.progress_dialog = QProgressDialog("正在处理地图文件...", "取消", 0, 100, self)
        self.progress_dialog.setWindowTitle("生成地图")
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setModal(True)
        
        # 创建并启动工作线程
        self.map_worker = MapGeneratorWorker(file_paths)
        self.map_worker.progress_updated.connect(self.progress_dialog.setValue)
        self.map_worker.status_updated.connect(self.progress_dialog.setLabelText)
        self.map_worker.finished.connect(self.on_map_generation_finished)
        self.progress_dialog.canceled.connect(self.cancel_map_generation)
        
        self.map_worker.start()
        self.progress_dialog.show()
        
    def cancel_map_generation(self):
        """取消地图生成"""
        if hasattr(self, 'map_worker') and self.map_worker.isRunning():
            self.map_worker.terminate()
            self.map_worker.wait()
            self.log("地图生成已取消")
            
    @Slot(bool, str)
    def on_map_generation_finished(self, success, message):
        """地图生成完成处理"""
        self.progress_dialog.close()
        
        if success:
            self.log(f"地图生成完成: {message}")
            QMessageBox.information(self, "成功", message)
            # 刷新本地地图列表
            if self.current_mode == 'local':
                self.update_local_map_list()
        else:
            self.log(f"地图生成失败: {message}")
            QMessageBox.critical(self, "失败", message)
            
        # 清理工作线程
        if hasattr(self, 'map_worker'):
            self.map_worker.deleteLater()
            del self.map_worker
    
    def delete_local_map(self):
        """删除当前选择的本地地图"""
        try:
            # 检查是否有可删除的地图
            if (self.local_map_combo.count() == 0 or 
                "无可用" in self.local_map_combo.currentText()):
                QMessageBox.warning(self, "警告", "没有可删除的本地地图")
                return
            
            # 获取当前选择的地图名称
            map_name = self.local_map_combo.currentText()
            
            # 确认删除
            reply = QMessageBox.question(
                self, 
                "确认删除", 
                f"确定要删除地图 '{map_name}' 吗？\n\n此操作将：\n• 删除地图文件夹和图片资源\n• 清除相关校准数据\n• 从地图列表中移除\n\n此操作不可恢复！",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            self.log(f"🗑️ 开始删除本地地图: {map_name}")
            
            # 获取脚本目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 1. 删除原始图片文件（images目录）
            images_dir = os.path.join(script_dir, "images")
            image_file = os.path.join(images_dir, map_name)
            if os.path.exists(image_file):
                os.remove(image_file)
                self.log(f"✅ 已删除原始图片文件: {image_file}")
            else:
                self.log(f"⚠️ 原始图片文件不存在: {image_file}")
            
            # 2. 删除瓦片地图文件夹（tiles目录）
            tiles_dir = os.path.join(script_dir, "tiles")
            # 对于瓦片地图，文件夹名称是去掉扩展名的
            map_folder_name = os.path.splitext(map_name)[0] if '.' in map_name else map_name
            tile_folder = os.path.join(tiles_dir, map_folder_name)
            if os.path.exists(tile_folder):
                import shutil
                shutil.rmtree(tile_folder)
                self.log(f"✅ 已删除瓦片地图文件夹: {tile_folder}")
            else:
                self.log(f"⚠️ 瓦片地图文件夹不存在: {tile_folder}")
            
            # 3. 从maps.json中移除地图记录
            maps_json_file = os.path.join(script_dir, "maps.json")
            if os.path.exists(maps_json_file):
                try:
                    with open(maps_json_file, 'r', encoding='utf-8') as f:
                        maps_data = json.load(f)
                    
                    # maps.json是一个数组，需要找到对应的地图记录并移除
                    original_count = len(maps_data)
                    maps_data = [item for item in maps_data if item.get('name') != map_name]
                    
                    if len(maps_data) < original_count:
                        # 写回文件
                        with open(maps_json_file, 'w', encoding='utf-8') as f:
                            json.dump(maps_data, f, indent=4, ensure_ascii=False)
                        
                        self.log(f"✅ 已从maps.json中移除地图记录: {map_name}")
                    else:
                        self.log(f"⚠️ maps.json中没有找到地图记录: {map_name}")
                        
                except Exception as e:
                    self.log(f"❌ 更新maps.json失败: {e}")
            else:
                self.log(f"⚠️ maps.json文件不存在: {maps_json_file}")
            
            # 4. 清除相关校准数据
            if self.calibration_manager.has_calibration('local', map_name):
                if self.calibration_manager.delete_calibration('local', map_name):
                    self.log(f"✅ 已清除校准数据: {map_name}")
                else:
                    self.log(f"⚠️ 清除校准数据失败: {map_name}")
            
            # 5. 更新本地地图列表
            self.update_local_map_list()
            
            # 6. 如果当前正在使用被删除的地图，切换到其他地图或提示
            if self.current_mode == 'local':
                if self.local_map_combo.count() > 0 and "无可用" not in self.local_map_combo.itemText(0):
                    self.load_current_map()  # 加载第一个可用地图
                    self.log("已自动切换到其他本地地图")
                else:
                    self.log("⚠️ 没有其他本地地图，建议切换到在线模式")
            
            self.log(f"🎉 地图 '{map_name}' 删除完成")
            QMessageBox.information(self, "删除成功", f"地图 '{map_name}' 已成功删除")
            
        except Exception as e:
            error_msg = f"删除本地地图失败: {e}"
            self.log(f"❌ {error_msg}")
            QMessageBox.critical(self, "删除失败", error_msg)
    
    # --- 透明覆盖层相关方法 ---
    def setup_overlay_manager(self):
        """设置透明覆盖层管理器"""
        if not OVERLAY_AVAILABLE:
            self.log("透明覆盖层功能不可用")
            return
            
        try:
            # 创建覆盖层管理器
            self.overlay_manager = OverlayManager(self.web_view)
            
            # 设置初始参数
            if hasattr(self, 'circle_size_spinbox'):
                self.overlay_manager.set_circle_radius(self.circle_size_spinbox.value())
            if hasattr(self, 'z_color_mapping_checkbox'):
                self.overlay_manager.set_z_color_mapping(self.z_color_mapping_checkbox.isChecked())
            
            self.log("透明覆盖层初始化成功")
        except Exception as e:
            self.log(f"透明覆盖层初始化失败: {e}")
            import traceback
            traceback.print_exc()
    
    def on_circle_size_changed(self, value):
        """圆点大小变化处理"""
        if self.overlay_manager:
            self.overlay_manager.set_circle_radius(value)
            self.log(f"圆点大小已调整为: {value}px")
    
    def on_z_color_mapping_toggled(self, checked):
        """Z轴颜色映射开关切换处理"""
        if self.overlay_manager:
            self.overlay_manager.set_z_color_mapping(checked)
            status = "启用" if checked else "禁用"
            self.log(f"Z轴颜色映射已{status}")
    
    def on_overlay_visibility_toggled(self, checked):
        """覆盖层显示开关切换处理"""
        if self.overlay_manager:
            if checked:
                self.overlay_manager.show_overlay()
                self.log("中心圆点已显示")
            else:
                self.overlay_manager.hide_overlay()
                self.log("中心圆点已隐藏")

    # --- 路线录制相关方法 ---
    def start_route_recording(self):
        """开始路线录制"""
        if not ROUTE_RECORDER_AVAILABLE or not self.route_recorder:
            QMessageBox.warning(self, "录制不可用", "路线录制模块未正确加载！")
            return
        
        # 检查OCR是否启动
        if not (OCR_AVAILABLE and self.ocr_manager and hasattr(self.ocr_manager, 'ocr_worker') and self.ocr_manager.ocr_worker):
            reply = QMessageBox.question(
                self, 
                "OCR未启动", 
                "路线录制需要OCR功能提供坐标数据。\n是否要先启动OCR？", 
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.show_ocr_control_panel()
            return
        
        try:
            route_name = self.route_name_input.text().strip()
            if not route_name:
                route_name = None  # 将使用自动生成的名称
            
            success = self.route_recorder.start_recording(route_name)
            if success:
                self.log("路线录制已开始")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"开始录制失败: {e}")
            self.log(f"开始录制失败: {e}")
    
    def stop_route_recording(self):
        """停止路线录制"""
        if not self.route_recorder:
            return
        
        try:
            filepath = self.route_recorder.stop_recording()
            if filepath:
                QMessageBox.information(
                    self,
                    "录制完成",
                    f"路线录制完成！\n文件已保存到: {filepath}"
                )
                # 清空路线名称输入框
                self.route_name_input.clear()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"停止录制失败: {e}")
            self.log(f"停止录制失败: {e}")
    
    def show_recorded_routes(self):
        """显示已录制的路线"""
        if not self.route_recorder:
            return
        
        try:
            # 创建路线列表对话框
            dialog = RouteListDialog(self.route_recorder, self)
            dialog.exec()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"显示路线列表失败: {e}")
            self.log(f"显示路线列表失败: {e}")
    
    # 路线录制信号处理方法
    @Slot(str)
    def on_recording_started(self, route_name):
        """录制开始时的处理"""
        self.start_recording_btn.setEnabled(False)
        self.stop_recording_btn.setEnabled(True)
        self.recording_status_label.setText(f"录制状态: 正在录制 - {route_name}")
        self.recording_status_label.setStyleSheet("font-size: 11px; color: #28a745;")
        self.log(f"开始录制路线: {route_name}")
    
    @Slot(str, int)
    def on_recording_stopped(self, route_name, point_count):
        """录制停止时的处理"""
        self.start_recording_btn.setEnabled(True)
        self.stop_recording_btn.setEnabled(False)
        self.recording_status_label.setText(f"录制状态: 录制完成 - {route_name} ({point_count}个点)")
        self.recording_status_label.setStyleSheet("font-size: 11px; color: #17a2b8;")
        self.log(f"录制完成: {route_name}, 共{point_count}个坐标点")
    
    @Slot(int, int, int, int)
    def on_point_recorded(self, x, y, z, total_points):
        """记录点时的处理"""
        status = self.route_recorder.get_recording_status()
        self.recording_status_label.setText(
            f"录制中: {status['route_name']} - {total_points}个点 ({status['duration']})"
        )
        # 只记录到日志，不显示每个点（避免刷屏）
        if total_points % 10 == 0:  # 每10个点记录一次
            self.log(f"已录制{total_points}个坐标点")
    
    @Slot(str)
    def on_recording_error(self, error_msg):
        """录制错误时的处理"""
        self.log(f"录制错误: {error_msg}")
        self.recording_status_label.setText(f"录制状态: 错误 - {error_msg}")
        self.recording_status_label.setStyleSheet("font-size: 11px; color: #dc3545;")

    # --- OCR功能相关方法 ---
    def show_ocr_control_panel(self):
        """显示OCR控制面板"""
        if not OCR_AVAILABLE or not self.ocr_manager:
            QMessageBox.warning(self, "OCR不可用", "OCR模块未正确加载！")
            return
        
        try:
            self.ocr_manager.show_control_panel()
        except Exception as e:
            self.log(f"显示OCR控制面板失败: {e}")
            QMessageBox.critical(self, "错误", f"显示OCR控制面板失败: {e}")
    
    def start_ocr_recognition(self):
        """开始OCR识别"""
        if not OCR_AVAILABLE or not self.ocr_manager:
            QMessageBox.warning(self, "OCR不可用", "OCR模块未正确加载！")
            return
        
        try:
            success = self.ocr_manager.start_ocr()
            if success:
                self.ocr_start_btn.setEnabled(False)
                self.ocr_stop_btn.setEnabled(True)
                self.ocr_status_label.setText("OCR状态: 识别中")
                self.log("OCR识别已启动")
            else:
                QMessageBox.warning(self, "启动失败", "OCR识别启动失败，请检查设置")
        except Exception as e:
            self.log(f"启动OCR识别失败: {e}")
            QMessageBox.critical(self, "错误", f"启动OCR识别失败: {e}")
    
    def stop_ocr_recognition(self):
        """停止OCR识别"""
        if not OCR_AVAILABLE or not self.ocr_manager:
            return
        
        try:
            self.ocr_manager.stop_ocr()
            self.ocr_start_btn.setEnabled(True)
            self.ocr_stop_btn.setEnabled(False)
            self.ocr_status_label.setText("OCR状态: 已停止")
            self.log("OCR识别已停止")
        except Exception as e:
            self.log(f"停止OCR识别失败: {e}")
            QMessageBox.critical(self, "错误", f"停止OCR识别失败: {e}")
    
    def setup_ocr_region(self):
        """校准OCR区域"""
        if not OCR_AVAILABLE or not self.ocr_manager:
            QMessageBox.warning(self, "OCR不可用", "OCR模块未正确加载！")
            return
        
        try:
            self.ocr_manager.setup_ocr_region()
            self.log("OCR区域校准已启动")
        except Exception as e:
            self.log(f"启动OCR区域校准失败: {e}")
            QMessageBox.critical(self, "错误", f"启动OCR区域校准失败: {e}")
    
    # === 窗口控制功能 ===
    def toggle_map_topmost(self):
        """切换地图窗口顶置状态"""
        if not self.separated_map_window:
            QMessageBox.warning(self, "提示", "地图窗口未打开")
            self.map_topmost_checkbox.setChecked(False)
            return
        
        try:
            is_topmost = self.map_topmost_checkbox.isChecked()
            if is_topmost:
                self.separated_map_window.setWindowFlags(
                    self.separated_map_window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
                )
                self.log("地图窗口已设置为顶置")
            else:
                self.separated_map_window.setWindowFlags(
                    self.separated_map_window.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint
                )
                self.log("地图窗口已取消顶置")
            
            self.separated_map_window.show()  # 重新显示窗口以应用新的窗口标志
        except Exception as e:
            self.log(f"设置地图窗口顶置失败: {e}")
            QMessageBox.critical(self, "错误", f"设置地图窗口顶置失败: {e}")
    
    def toggle_map_passthrough(self):
        """切换地图窗口鼠标穿透状态"""
        if not self.separated_map_window:
            QMessageBox.warning(self, "提示", "地图窗口未打开")
            self.map_passthrough_checkbox.setChecked(False)
            return
        
        try:
            is_passthrough = self.map_passthrough_checkbox.isChecked()
            
            # 保存当前窗口位置和大小
            geometry = self.separated_map_window.geometry()
            
            if is_passthrough:
                # 开启鼠标穿透
                flags = Qt.WindowType.Widget | Qt.WindowType.WindowTransparentForInput
                if self.map_topmost_checkbox.isChecked():
                    flags |= Qt.WindowType.WindowStaysOnTopHint
                if self.map_frameless_checkbox.isChecked():
                    flags |= Qt.WindowType.FramelessWindowHint
                    
                self.separated_map_window.setWindowFlags(flags)
                self.separated_map_window.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True) 
                self.separated_map_window.setGeometry(geometry)  # 恢复位置和大小
                self.separated_map_window.show()
                self.log("地图窗口已开启鼠标穿透")
            else:
                # 关闭鼠标穿透 - 完全重建窗口
                self.separated_map_window.hide()  # 先隐藏
                
                # 清除所有属性
                self.separated_map_window.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                
                # 重新设置基本的窗口标志
                base_flags = Qt.WindowType.Widget
                if self.map_topmost_checkbox.isChecked():
                    base_flags |= Qt.WindowType.WindowStaysOnTopHint
                if self.map_frameless_checkbox.isChecked():
                    base_flags |= Qt.WindowType.FramelessWindowHint
                
                self.separated_map_window.setWindowFlags(base_flags)
                self.separated_map_window.setGeometry(geometry)  # 恢复位置和大小
                self.separated_map_window.show()
                self.separated_map_window.raise_()
                self.separated_map_window.activateWindow()  # 激活窗口
                
                self.log("地图窗口已关闭鼠标穿透")
        except Exception as e:
            self.log(f"设置地图窗口鼠标穿透失败: {e}")
            QMessageBox.critical(self, "错误", f"设置地图窗口鼠标穿透失败: {e}")
    
    def toggle_map_frameless(self):
        """切换地图窗口无边框模式"""
        if not self.separated_map_window:
            QMessageBox.warning(self, "提示", "地图窗口未打开")
            self.map_frameless_checkbox.setChecked(False)
            return
        
        try:
            is_frameless = self.map_frameless_checkbox.isChecked()
            if is_frameless:
                self.separated_map_window.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint if self.map_topmost_checkbox.isChecked() else Qt.WindowType.FramelessWindowHint
                )
                self.log("地图窗口已开启无边框模式")
            else:
                self.separated_map_window.setWindowFlags(
                    Qt.WindowType.Widget | (Qt.WindowType.WindowStaysOnTopHint if self.map_topmost_checkbox.isChecked() else Qt.WindowType.Widget)
                )
                self.log("地图窗口已关闭无边框模式")
            
            self.separated_map_window.show()  # 重新显示窗口以应用新的窗口标志
        except Exception as e:
            self.log(f"设置地图窗口无边框模式失败: {e}")
            QMessageBox.critical(self, "错误", f"设置地图窗口无边框模式失败: {e}")
    
    def on_map_opacity_changed(self, value):
        """地图窗口透明度改变"""
        if not self.separated_map_window:
            return
        
        try:
            opacity = value / 100.0
            self.separated_map_window.setWindowOpacity(opacity)
            self.map_opacity_label.setText(f"{value}%")
            self.log(f"地图窗口透明度设置为: {value}%")
        except Exception as e:
            self.log(f"设置地图窗口透明度失败: {e}")
    
    def toggle_main_topmost(self):
        """切换主界面顶置状态"""
        try:
            is_topmost = self.main_topmost_checkbox.isChecked()
            if is_topmost:
                self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
                self.log("主界面已设置为顶置")
            else:
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
                self.log("主界面已取消顶置")
            
            self.show()  # 重新显示窗口以应用新的窗口标志
        except Exception as e:
            self.log(f"设置主界面顶置失败: {e}")
            QMessageBox.critical(self, "错误", f"设置主界面顶置失败: {e}")
    
    
    @Slot(int, int, int)
    def on_ocr_coordinates_detected(self, x, y, z):
        """OCR检测到坐标时的处理"""
        self.log(f"OCR检测到坐标: ({x}, {y}, {z})")
        
        # 更新覆盖层的Z值，用于颜色映射
        if self.overlay_manager and hasattr(self, 'z_color_mapping_checkbox') and self.z_color_mapping_checkbox.isChecked():
            self.overlay_manager.set_z_value(z)
        
        # 录制路线点（如果正在录制）
        if self.route_recorder and self.route_recorder.is_recording:
            self.route_recorder.record_point(x, y, z)
        
        # 如果有校准矩阵且启用了OCR自动跳转，则自动跳转
        # 注意：这里的自动跳转逻辑在ocr_auto_jump方法中处理
    
    @Slot(str)
    def on_ocr_state_changed(self, state):
        """OCR状态变化时的处理"""
        if hasattr(self, 'ocr_status_label'):
            state_colors = {
                'LOCKED': '#4CAF50',    # 绿色
                'LOST': '#f44336',      # 红色  
                'SEARCHING': '#FF9800', # 橙色
                'STOPPED': '#666666'    # 灰色
            }
            color = state_colors.get(state, '#666666')
            self.ocr_status_label.setText(f"OCR状态: {state}")
            self.ocr_status_label.setStyleSheet(f"font-size: 11px; color: {color};")
        
        # 根据OCR状态更新开始/停止按钮状态
        if hasattr(self, 'ocr_start_btn') and hasattr(self, 'ocr_stop_btn'):
            if state == 'STOPPED':
                self.ocr_start_btn.setEnabled(True)
                self.ocr_stop_btn.setEnabled(False)
            else:
                self.ocr_start_btn.setEnabled(False)  
                self.ocr_stop_btn.setEnabled(True)
        
        self.log(f"OCR状态变化: {state}")
    
    @Slot(str)
    def on_ocr_error(self, error_msg):
        """OCR错误处理"""
        self.log(f"OCR错误: {error_msg}")
        # 可以选择显示错误对话框，但这里只记录日志避免过多弹窗
    
    def ocr_auto_jump(self, x, y, z):
        """OCR自动跳转功能"""
        try:
            self.log(f"收到OCR坐标: ({x}, {y}, {z})")
            
            if self.transform_matrix is None:
                self.log("OCR自动跳转失败: 地图未校准，请先完成地图校准")
                return
            
            # 直接进行坐标转换而不设置输入框（避免UI干扰）
            try:
                lat, lon = CalibrationSystem.transform(x, y, self.transform_matrix)
                self.log(f"坐标转换成功: ({x}, {y}) -> ({lat:.6f}, {lon:.6f})")
            except Exception as transform_error:
                self.log(f"坐标转换失败: {transform_error}")
                return
            
            # 执行跳转（保持原有逻辑）
            success = False
            if self.current_mode == 'online':
                # 在线地图使用JavaScript跳转
                if self.web_view and self.web_view.page():
                    js_code = f"if(window.discoveredMap) {{ window.discoveredMap.panTo([{lat}, {lon}]); }}"
                    self.web_view.page().runJavaScript(js_code)
                    success = True
                    self.log(f"在线地图OCR自动跳转成功: ({x}, {y}, {z}) -> ({lat:.6f}, {lon:.6f})")
                else:
                    self.log("OCR自动跳转失败: WebView不可用")
            else:
                # 本地地图通过WebSocket广播跳转指令
                command = {
                    "type": "jumpTo",
                    "lat": lat,
                    "lng": lon
                }
                if self.server_manager.broadcast_command(command):
                    success = True
                    self.log(f"本地地图OCR自动跳转成功: ({x}, {y}, {z}) -> ({lat:.6f}, {lon:.6f})")
                else:
                    self.log("OCR自动跳转失败: 本地服务器不可用")
            
        except Exception as e:
            self.log(f"OCR自动跳转异常: {e}")
            import traceback
            traceback.print_exc()
    
    def _cleanup_ocr(self):
        """清理OCR资源"""
        # 检查关闭标志并打印调试信息
        print(f"_cleanup_ocr 调用，_is_closing={getattr(self, '_is_closing', '未定义')}")
        
        # 如果正在关闭，立即强制终止程序
        if hasattr(self, '_is_closing') and self._is_closing:
            print("检测到程序正在关闭，立即强制终止进程...")
            try:
                # 尝试关闭地图窗口
                if hasattr(self, 'separated_map_window') and self.separated_map_window:
                    print("在OCR清理时强制关闭地图窗口...")
                    self.separated_map_window.hide()
                    self.separated_map_window.close()
                    self.separated_map_window.deleteLater()
                    print("地图窗口已在OCR清理时强制关闭")
                
                print("在OCR清理时立即终止进程...")
                import os
                os._exit(0)  # 强制终止进程
                
            except Exception as e:
                print(f"在OCR清理时强制终止进程出错: {e}")
                import os
                os._exit(1)
        else:
            print("未检测到关闭标志，继续正常清理OCR...")
        
        try:
            if OCR_AVAILABLE and hasattr(self, 'ocr_manager') and self.ocr_manager:
                self.ocr_manager.cleanup()
                self.log("OCR资源已清理")
        except Exception as e:
            print(f"清理OCR资源时出错: {e}")
        
        # 无论如何，如果这个方法被调用了，就强制终止程序
        print("OCR清理完成，无论如何都强制终止程序...")
        try:
            import os
            os._exit(0)
        except:
            import sys
            sys.exit(0)
    
    def _cleanup_overlay(self):
        """清理覆盖层资源"""
        try:
            if hasattr(self, 'overlay_manager') and self.overlay_manager:
                self.overlay_manager.cleanup()
                self.log("覆盖层资源已清理")
        except Exception as e:
            print(f"清理覆盖层资源时出错: {e}")
    
    def _cleanup_route_recorder(self):
        """清理路线录制器资源"""
        try:
            if hasattr(self, 'route_recorder') and self.route_recorder:
                self.route_recorder.cleanup()
                self.log("路线录制器资源已清理")
        except Exception as e:
            print(f"清理路线录制器资源时出错: {e}")
        
        # 在路线录制器清理完成后，强制终止整个程序
        if hasattr(self, '_is_closing') and self._is_closing:
            print("主程序正在关闭，强制终止所有进程...")
            try:
                # 尝试关闭地图窗口
                if hasattr(self, 'separated_map_window') and self.separated_map_window:
                    print("强制关闭地图窗口...")
                    try:
                        self.separated_map_window.window_closed.disconnect()
                    except:
                        pass
                    self.separated_map_window.hide()
                    self.separated_map_window.close()
                    self.separated_map_window.deleteLater()
                    print("地图窗口已强制关闭")
                
                print("立即终止进程...")
                import os
                os._exit(0)  # 强制终止进程
                
            except Exception as e:
                print(f"强制终止进程时出错: {e}")
                import os
                os._exit(1)
    
    def _cleanup_map_window(self):
        """清理分离地图窗口资源"""
        try:
            if hasattr(self, 'separated_map_window') and self.separated_map_window:
                print("正在关闭分离地图窗口...")
                self.separated_map_window.close()
                self.separated_map_window = None
                print("分离地图窗口已关闭")
        except Exception as e:
            print(f"清理分离地图窗口资源时出错: {e}")
    
    # --- 地图追踪功能 ---
    def toggle_map_tracking(self):
        """切换地图追踪状态"""
        try:
            if not self.tracking_active:
                self.start_tracking()
            else:
                self.stop_tracking()
        except Exception as e:
            self.log(f"切换追踪状态错误: {e}")
    
    def start_tracking(self):
        """开始地图追踪"""
        try:
            self.tracking_active = True
            self.tracking_btn.setText("停止地图追踪")
            self.tracking_btn.setChecked(True)
            self.tracking_status_label.setText("追踪状态: 正在追踪")
            self.tracking_status_label.setStyleSheet("font-size: 11px; color: #28a745;")
            
            # 开始定时更新追踪信息 (每秒更新一次)
            self.tracking_timer.start(1000)
            
            self.log("✓ 地图追踪已启动")
            
            # 立即更新一次位置
            self.update_tracking_position()
            
        except Exception as e:
            self.log(f"启动追踪失败: {e}")
            self.tracking_active = False
    
    def stop_tracking(self):
        """停止地图追踪"""
        try:
            self.tracking_active = False
            self.tracking_btn.setText("开始地图追踪")
            self.tracking_btn.setChecked(False)
            self.tracking_status_label.setText("追踪状态: 已停止")
            self.tracking_status_label.setStyleSheet("font-size: 11px; color: #666;")
            
            # 停止定时器
            if self.tracking_timer.isActive():
                self.tracking_timer.stop()
            
            self.current_position_label.setText("当前位置: 追踪已停止")
            self.log("◎ 地图追踪已停止")
            
        except Exception as e:
            self.log(f"停止追踪失败: {e}")
    
    def update_tracking_position(self):
        """更新追踪位置信息"""
        if not self.tracking_active:
            return
            
        try:
            # 获取当前地图状态
            if self.current_mode == 'online':
                # 在线模式：通过JavaScript获取当前位置
                self.web_view.page().runJavaScript("""
                    (function() {
                        if (window.discoveredMap) {
                            const center = window.discoveredMap.getCenter();
                            const zoom = window.discoveredMap.getZoom();
                            return {
                                lat: center.lat,
                                lng: center.lng,
                                zoom: zoom
                            };
                        }
                        return null;
                    })();
                """, self.on_tracking_position_received)
            else:
                # 本地模式：从服务器获取状态
                # 这里可以扩展本地模式的位置追踪
                pass
                
        except Exception as e:
            self.log(f"更新追踪位置错误: {e}")
    
    def on_tracking_position_received(self, position_data):
        """接收到追踪位置数据"""
        if not self.tracking_active or not position_data:
            return
            
        try:
            lat = position_data.get('lat')
            lng = position_data.get('lng')
            zoom = position_data.get('zoom')
            
            if lat is not None and lng is not None:
                # 更新当前位置信息
                self.current_lat = lat
                self.current_lng = lng
                self.current_zoom = zoom
                
                # 尝试转换为游戏坐标（如果已校准）
                if self.transform_matrix:
                    try:
                        game_x, game_y = CalibrationSystem.inverse_transform(lat, lng, self.transform_matrix)
                        position_text = f"经纬度: ({lat:.6f}, {lng:.6f}) | 游戏坐标: ({game_x:.1f}, {game_y:.1f}) | 缩放: {zoom:.1f}"
                    except:
                        position_text = f"经纬度: ({lat:.6f}, {lng:.6f}) | 缩放: {zoom:.1f} | 游戏坐标: 未校准"
                else:
                    position_text = f"经纬度: ({lat:.6f}, {lng:.6f}) | 缩放: {zoom:.1f} | 游戏坐标: 未校准"
                
                self.current_position_label.setText(f"当前位置: {position_text}")
                
                # 添加到追踪历史（最多保存100条记录）
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.tracking_history.append({
                    'timestamp': timestamp,
                    'lat': lat,
                    'lng': lng,
                    'zoom': zoom
                })
                
                # 限制历史记录数量
                if len(self.tracking_history) > 100:
                    self.tracking_history.pop(0)
                
        except Exception as e:
            self.log(f"处理追踪位置数据错误: {e}")
    
    def get_tracking_history(self):
        """获取追踪历史"""
        return self.tracking_history.copy()
    
    def clear_tracking_history(self):
        """清空追踪历史"""
        self.tracking_history.clear()
        self.log("追踪历史已清空")
    
    # --- SVG路线导入功能 ---
    def import_svg_route(self):
        """导入SVG路线文件"""
        try:
            # 检查当前是否为本地地图模式
            if self.current_mode != 'local':
                QMessageBox.warning(self, "模式错误", "SVG路线导入功能仅支持本地地图模式！\n请先切换到本地地图模式。")
                return
                
            # 文件选择对话框
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "选择SVG路线文件",
                "",
                "SVG文件 (*.svg);;所有文件 (*.*)"
            )
            
            if not file_path:
                return
            
            # 提取文件名作为路线名称
            import os
            route_name = os.path.basename(file_path)
            self.log(f"正在处理SVG文件: {file_path}")
            
            # 解析SVG元数据
            svg_data = self.parse_svg_metadata(file_path)
            if svg_data is None:
                QMessageBox.warning(self, "解析失败", "无法解析SVG文件或缺少必要的元数据！")
                # 确保UI状态正确
                self.current_route_label.setText("无")
                self.clear_svg_btn.setEnabled(False)
                return
                
            # 处理坐标转换
            if not svg_data["is_converted"]:
                # 需要坐标转换
                if self.transform_matrix is None:
                    QMessageBox.warning(self, "校准未完成", "SVG文件包含游戏坐标，需要先校准当前地图！\n请先完成地图校准后再导入SVG路线。")
                    # 确保UI状态正确
                    self.current_route_label.setText("无")
                    self.clear_svg_btn.setEnabled(False)
                    return
                    
                # 转换坐标
                self.log("正在转换游戏坐标到地图坐标...")
                try:
                    start_game = svg_data["points"]["start"]["game"]
                    end_game = svg_data["points"]["end"]["game"]
                    
                    start_lat, start_lng = CalibrationSystem.transform(start_game[0], start_game[1], self.transform_matrix)
                    end_lat, end_lng = CalibrationSystem.transform(end_game[0], end_game[1], self.transform_matrix)
                    
                    self.log(f"起点坐标转换: ({start_game[0]}, {start_game[1]}) -> ({start_lat:.6f}, {start_lng:.6f})")
                    self.log(f"终点坐标转换: ({end_game[0]}, {end_game[1]}) -> ({end_lat:.6f}, {end_lng:.6f})")
                    
                except Exception as e:
                    QMessageBox.critical(self, "坐标转换失败", f"坐标转换过程中出错: {e}")
                    # 确保UI状态正确
                    self.current_route_label.setText("无")
                    self.clear_svg_btn.setEnabled(False)
                    return
            else:
                # 已转换坐标，直接使用
                start_lat, start_lng = svg_data["points"]["start"]["game"][1], svg_data["points"]["start"]["game"][0]  # lat, lng
                end_lat, end_lng = svg_data["points"]["end"]["game"][1], svg_data["points"]["end"]["game"][0]        # lat, lng
                self.log("使用SVG文件中的已转换坐标")
                
            # 准备发送给前端的数据 - 升级版包含变换信息
            frontend_data = {
                "svgContent": svg_data["svg_content"],
                "viewBox": svg_data["view_box"],
                "startPoint": {
                    "svg_x": svg_data["points"]["start"]["svg"][0],
                    "svg_y": svg_data["points"]["start"]["svg"][1],
                    "lat": start_lat,
                    "lng": start_lng
                },
                "endPoint": {
                    "svg_x": svg_data["points"]["end"]["svg"][0],
                    "svg_y": svg_data["points"]["end"]["svg"][1],
                    "lat": end_lat,
                    "lng": end_lng
                },
                "transformMatrix": svg_data.get("transform_matrix"),
                "formatType": svg_data.get("format_type", "simple")
            }
            
            self.log(f"SVG格式类型: {svg_data.get('format_type', 'simple')}")
            
            # 发送数据到前端
            import json
            json_payload = json.dumps(frontend_data, ensure_ascii=False)
            js_command = f"window.displaySvgRoute({json_payload});"
            self.web_view.page().runJavaScript(js_command)
            
            # 更新UI状态
            self.current_route_label.setText(route_name)
            self.clear_svg_btn.setEnabled(True)
            
            self.log("✓ SVG路线数据已发送至前端进行渲染")
            
        except Exception as e:
            self.log(f"导入SVG路线失败: {e}")
            QMessageBox.critical(self, "导入失败", f"导入SVG路线时出错:\n{str(e)}")
            # 确保UI状态正确
            self.current_route_label.setText("无")
            self.clear_svg_btn.setEnabled(False)
            import traceback
            traceback.print_exc()
    
    def parse_svg_metadata(self, file_path):
        """解析SVG文件元数据 - 升级版支持复杂变换
        
        根据SVG_元数据格式完整说明.md解析SVG文件
        返回格式化的数据字典或None（如果解析失败）
        """
        try:
            import xml.etree.ElementTree as ET
            import re
            import numpy as np
            
            # 读取SVG文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # 解析XML
            try:
                root = ET.fromstring(svg_content)
                self.log(f"XML解析成功，根元素: {root.tag}")
            except ET.ParseError as e:
                self.log(f"SVG XML解析失败: {e}")
                return None
                
            # 提取viewBox信息
            view_box_attr = root.get('viewBox')
            if not view_box_attr:
                self.log("SVG文件缺少viewBox属性")
                return None
                
            view_box_values = view_box_attr.split()
            if len(view_box_values) != 4:
                self.log("SVG viewBox格式错误")
                return None
                
            view_box = {
                "x": float(view_box_values[0]),
                "y": float(view_box_values[1]),
                "width": float(view_box_values[2]),
                "height": float(view_box_values[3])
            }
            
            # 检测SVG变换矩阵 - 新增功能
            transform_matrix = self.detect_svg_transform_matrix(root)
            if transform_matrix:
                self.log(f"检测到SVG变换矩阵: {transform_matrix}")
            else:
                self.log("未检测到SVG变换矩阵，使用简单坐标映射")
            
            # 方法1: 尝试解析标准XML元数据 - 修复命名空间问题
            # 先尝试不带命名空间的查询
            metadata_elements = root.findall(".//metadata[@id='game_route_data']")
            self.log(f"无命名空间搜索metadata元素，找到{len(metadata_elements)}个")
            
            # 如果没找到，尝试带SVG命名空间的查询
            if not metadata_elements:
                namespaces = {'svg': 'http://www.w3.org/2000/svg'}
                metadata_elements = root.findall(".//svg:metadata[@id='game_route_data']", namespaces)
                self.log(f"带SVG命名空间搜索metadata元素，找到{len(metadata_elements)}个")
            
            # 如果还是没找到，尝试查找所有metadata元素（不考虑命名空间）
            if not metadata_elements:
                # 使用更通用的方法查找metadata元素
                for elem in root.iter():
                    if elem.tag.endswith('metadata') and elem.get('id') == 'game_route_data':
                        metadata_elements = [elem]
                        self.log(f"通用方法找到metadata元素: {elem.tag}")
                        break
            
            # 额外调试：查找所有metadata元素
            all_metadata = []
            for elem in root.iter():
                if elem.tag.endswith('metadata'):
                    all_metadata.append(elem)
                    
            self.log(f"总共找到{len(all_metadata)}个metadata元素")
            for i, meta in enumerate(all_metadata):
                meta_id = meta.get('id', '无ID')
                self.log(f"metadata[{i}]: tag={meta.tag}, id='{meta_id}'")
            
            if metadata_elements:
                self.log("找到XML格式元数据，开始解析...")
                metadata = metadata_elements[0]
                is_converted = metadata.get('converted') == 'true'
                
                points = {}
                # 修复point元素查找的命名空间问题
                point_elements = metadata.findall('point')
                self.log(f"无命名空间查找point元素，找到{len(point_elements)}个")
                
                # 如果没找到，尝试带命名空间查询
                if not point_elements:
                    namespaces = {'svg': 'http://www.w3.org/2000/svg'}
                    point_elements = metadata.findall('svg:point', namespaces)
                    self.log(f"带命名空间查找point元素，找到{len(point_elements)}个")
                
                # 如果还是没找到，使用通用方法
                if not point_elements:
                    point_elements = []
                    for elem in metadata.iter():
                        if elem.tag.endswith('point'):
                            point_elements.append(elem)
                    self.log(f"通用方法查找point元素，找到{len(point_elements)}个")
                
                for point in point_elements:
                    point_id = point.get('id')
                    self.log(f"处理point元素: id={point_id}")
                    
                    if point_id in ['start', 'end']:
                        # 获取所有属性进行调试
                        svg_x = point.get('svg_x')
                        svg_y = point.get('svg_y')
                        game_x = point.get('game_x')
                        game_y = point.get('game_y')
                        game_z = point.get('game_z')
                        
                        self.log(f"point {point_id} 属性: svg_x={svg_x}, svg_y={svg_y}, game_x={game_x}, game_y={game_y}, game_z={game_z}")
                        
                        # 检查必要属性是否存在
                        if all([svg_x, svg_y, game_x, game_y, game_z]):
                            try:
                                points[point_id] = {
                                    'svg': (float(svg_x), float(svg_y)),
                                    'game': (float(game_x), float(game_y), float(game_z))
                                }
                                self.log(f"成功解析point {point_id}")
                            except ValueError as e:
                                self.log(f"point {point_id} 数值转换失败: {e}")
                        else:
                            self.log(f"point {point_id} 缺少必要属性")
                
                self.log(f"解析结果：共找到{len(points)}个有效点")
                if 'start' in points and 'end' in points:
                    self.log("成功解析XML格式元数据")
                    return {
                        "svg_content": svg_content,
                        "view_box": view_box,
                        "is_converted": is_converted,
                        "points": points,
                        "transform_matrix": transform_matrix,
                        "format_type": "complex" if transform_matrix else "simple"
                    }
            
            # 方法2: 尝试解析注释格式元数据
            comment_pattern = r'<!--\s*game_route_data\s*(converted="true")?\s*\n(.*?)\n-->'
            match = re.search(comment_pattern, svg_content, re.DOTALL)
            
            if match:
                is_converted = match.group(1) is not None
                comment_content = match.group(2)
                
                points = {}
                # 解析起点和终点
                for point_type in ['start', 'end']:
                    pattern = f'{point_type}:\\s*svg_x="([^"]+)"\\s*svg_y="([^"]+)"\\s*game_x="([^"]+)"\\s*game_y="([^"]+)"\\s*game_z="([^"]+)"'
                    point_match = re.search(pattern, comment_content)
                    if point_match:
                        points[point_type] = {
                            'svg': (float(point_match.group(1)), float(point_match.group(2))),
                            'game': (float(point_match.group(3)), float(point_match.group(4)), float(point_match.group(5)))
                        }
                
                if 'start' in points and 'end' in points:
                    self.log("成功解析注释格式元数据")
                    return {
                        "svg_content": svg_content,
                        "view_box": view_box,
                        "is_converted": is_converted,
                        "points": points,
                        "transform_matrix": transform_matrix,
                        "format_type": "complex" if transform_matrix else "simple"
                    }
            
            self.log("SVG文件中未找到有效的元数据")
            return None
            
        except Exception as e:
            self.log(f"解析SVG元数据时出错: {e}")
            import traceback
            traceback.print_exc()
            return None

    def clear_svg_route(self):
        """清除当前SVG路线"""
        try:
            # 调用前端清除函数
            js_command = "window.clearSvgRoute();"
            self.web_view.page().runJavaScript(js_command)
            
            # 更新UI状态
            self.current_route_label.setText("无")
            self.clear_svg_btn.setEnabled(False)
            
            self.log("✓ 已清除当前SVG路线")
            
        except Exception as e:
            self.log(f"清除SVG路线失败: {e}")
            QMessageBox.warning(self, "清除失败", f"清除SVG路线时出错:\n{str(e)}")

    def detect_svg_transform_matrix(self, root):
        """检测SVG中的变换矩阵 - 修复命名空间问题"""
        try:
            import re
            
            # 方法1: 先尝试不带命名空间的查询
            g_elements = root.findall(".//g[@transform]")
            self.log(f"无命名空间查找g元素，找到{len(g_elements)}个")
            
            # 方法2: 如果没找到，尝试带命名空间的查询
            if not g_elements:
                namespaces = {'svg': 'http://www.w3.org/2000/svg'}
                g_elements = root.findall(".//svg:g[@transform]", namespaces)
                self.log(f"带命名空间查找g元素，找到{len(g_elements)}个")
            
            # 方法3: 如果还是没找到，使用通用方法遍历所有元素
            if not g_elements:
                g_elements = []
                for elem in root.iter():
                    if elem.tag.endswith('g') and elem.get('transform'):
                        g_elements.append(elem)
                self.log(f"通用方法查找g元素，找到{len(g_elements)}个")
            
            # 查找包含transform属性的g元素
            for g_element in g_elements:
                transform_attr = g_element.get('transform')
                if transform_attr:
                    self.log(f"找到transform属性: {transform_attr}")
                    # 解析matrix变换
                    matrix_match = re.search(r'matrix\(([-\d.,\s]+)\)', transform_attr)
                    if matrix_match:
                        values = matrix_match.group(1).split(',')
                        if len(values) == 6:
                            try:
                                matrix = {
                                    'a': float(values[0].strip()),
                                    'b': float(values[1].strip()),  
                                    'c': float(values[2].strip()),
                                    'd': float(values[3].strip()),
                                    'e': float(values[4].strip()),
                                    'f': float(values[5].strip())
                                }
                                self.log(f"成功解析变换矩阵: {matrix}")
                                return matrix
                            except ValueError as e:
                                self.log(f"变换矩阵解析失败: {e}")
                                continue
            
            return None
            
        except Exception as e:
            self.log(f"检测变换矩阵时出错: {e}")
            return None
    
    def apply_svg_transform(self, x, y, matrix):
        """应用SVG变换矩阵到坐标点"""
        if not matrix:
            return x, y
            
        # SVG变换公式: x' = a*x + c*y + e, y' = b*x + d*y + f
        new_x = matrix['a'] * x + matrix['c'] * y + matrix['e']
        new_y = matrix['b'] * x + matrix['d'] * y + matrix['f']
        
        return new_x, new_y
    
    def inverse_svg_transform(self, x, y, matrix):
        """SVG变换矩阵的逆变换"""
        if not matrix:
            return x, y
            
        try:
            # 计算变换矩阵的逆矩阵
            a, b, c, d, e, f = matrix['a'], matrix['b'], matrix['c'], matrix['d'], matrix['e'], matrix['f']
            
            # 计算行列式
            det = a * d - b * c
            if abs(det) < 1e-10:  # 防止除零
                return x, y
                
            # 逆矩阵计算
            inv_a = d / det
            inv_b = -b / det
            inv_c = -c / det
            inv_d = a / det
            inv_e = (c * f - d * e) / det
            inv_f = (b * e - a * f) / det
            
            # 应用逆变换
            orig_x = inv_a * x + inv_c * y + inv_e
            orig_y = inv_b * x + inv_d * y + inv_f
            
            return orig_x, orig_y
            
        except Exception as e:
            self.log(f"逆变换计算失败: {e}")
            return x, y

    def _cleanup_tracking(self):
        """清理追踪资源"""
        try:
            if hasattr(self, 'tracking_timer') and self.tracking_timer:
                self.tracking_timer.stop()
                self.tracking_timer.deleteLater()
                self.tracking_timer = None
            self.log("追踪资源已清理")
        except Exception as e:
            print(f"清理追踪资源时出错: {e}")
    
    def on_language_combo_changed(self):
        """语言选择变更处理"""
        if not LANGUAGE_AVAILABLE:
            return
            
        selected_index = self.language_combo.currentIndex()
        if selected_index >= 0:
            lang_code = self.language_combo.itemData(selected_index)
            if lang_code:
                self.language_manager.set_language(lang_code)
    
    def on_language_changed(self, lang_code):
        """语言变更处理"""
        try:
            # 更新窗口标题
            self.setWindowTitle(tr("app_title", "呜呜大地图 - 混合模式 V4"))
            
            # 显示语言变更提示
            QMessageBox.information(
                self, 
                tr("info", "信息"),
                tr("language_changed", "语言已更改") + "\n" + 
                tr("restart_to_apply", "重启以应用更改")
            )
            
            self.log(tr("msg_language_changed", "Language changed to: {language}").format(
                language=self.language_manager.get_current_language_name()
            ))
            
            # 如果当前是在线模式且使用光环助手地图，重新加载以使用正确的域名
            if self.current_mode == 'online' and hasattr(self, 'web_view') and self.web_view:
                current_url = self.web_view.url().toString()
                # 检查是否是光环助手地图
                if ("ghzs.com" in current_url or "ghzs666.com" in current_url):
                    # 重新加载光环助手地图以使用正确的域名
                    map_urls = get_map_urls(lang_code)
                    new_url = map_urls["aura_helper"]
                    if new_url != current_url:
                        self.web_view.setUrl(QUrl(new_url))
                        self.log(f"Language change triggered map reload: {new_url}")
            
        except Exception as e:
            print(f"语言变更处理失败: {e}")
    
    def update_ui_texts(self):
        """更新所有UI文本（用于语言切换后）"""
        try:
            # 这个方法可以在将来扩展，用于动态更新所有UI文本
            # 目前建议用户重启应用程序以完全应用语言变更
            pass
        except Exception as e:
            print(f"更新UI文本失败: {e}")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            # 停止追踪
            if hasattr(self, 'tracking_active') and self.tracking_active:
                self.stop_tracking()
            
            # 清理追踪资源
            self._cleanup_tracking()
            
            # 清理OCR资源
            self._cleanup_ocr()
            
            # 清理覆盖层资源
            self._cleanup_overlay()
            
            # 清理路线录制器资源
            self._cleanup_route_recorder()
            
            # 调用父类的closeEvent
            super().closeEvent(event)
            
        except Exception as e:
            print(f"关闭窗口时出错: {e}")
            event.accept()  # 确保窗口能正常关闭

if __name__ == "__main__":
    # 确保工作目录是脚本所在目录
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    app = QApplication(sys.argv)
    main_window = MapCalibrationMainWindow()
    main_window.show()
    sys.exit(app.exec())
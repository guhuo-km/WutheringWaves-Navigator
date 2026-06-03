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
            // 静默忽略无效响应消息，避免控制台spam
            // 这些消息可能来自页面重新加载或其他异步操作
            // console.error("Invalid response message received: ", message);
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

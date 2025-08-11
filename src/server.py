import json
import copy
from flask import Flask, jsonify
from flask_sock import Sock

# --- 1. 初始化应用 ---
app = Flask(__name__)
app.config["SECRET_KEY"] = "a_very_secret_key"
sock = Sock(app)

# --- 2. 全局状态管理 ---
clients = set()
try:
    with open('maps.json', 'r', encoding='utf-8') as f:
        initial_map_name = json.load(f)[0]['name']
except (FileNotFoundError, IndexError):
    initial_map_name = "default_map"

map_state = {
    "lat": 0, "lng": 0, "zoom": 0, "mapName": initial_map_name
}

# --- 3. 核心功能：广播消息 ---
def broadcast(message_dict):
    message_json = json.dumps(message_dict)
    for client in copy.copy(clients):
        try:
            client.send(message_json)
        except Exception as e:
            print(f"发送消息失败，移除客户端: {e}")
            clients.remove(client)
            # 当因发送失败而移除客户端时，也广播客户端数量变化
            broadcast_client_count()

def broadcast_client_count():
    """专门用于广播当前客户端数量"""
    count_message = {"type": "clientCountUpdate", "count": len(clients)}
    broadcast(count_message)

# --- 4. WebSocket 路由 ---
@sock.route('/ws')
def ws_handle(ws):
    print("一个客户端已连接")
    clients.add(ws)
    # 广播客户端数量变化
    broadcast_client_count()
    
    # 向新客户端发送当前完整状态
    initial_message = {"type": "initialState", **map_state}
    try:
        ws.send(json.dumps(initial_message))
    except Exception as e:
        print(f"发送初始状态失败: {e}")
        clients.remove(ws)
        broadcast_client_count() # 更新数量
        return

    try:
        while True:
            message = ws.receive()
            if message is None:
                break
            
            data = json.loads(message)
            print(f"收到消息: {data}")

            # 更新服务器状态并广播
            if data['type'] == 'stateUpdate':
                map_state.update(data)
                broadcast(data)
            elif data['type'] == 'mapChange':
                map_state.update(data)
                broadcast(data)
            # --- 新增的指令处理 ---
            elif data['type'] == 'panBy':
                broadcast(data)  # 直接将指令广播给所有地图客户端
            elif data['type'] == 'zoomIn':
                broadcast(data)  # 直接广播
            elif data['type'] == 'zoomOut':
                broadcast(data)  # 直接广播
            elif data['type'] == 'jumpTo':
                broadcast(data)  # 广播跳转指令

    except Exception as e:
        print(f"WebSocket连接出现错误: {e}")
    finally:
        print("一个客户端已断开")
        if ws in clients:
            clients.remove(ws)
            # 广播客户端数量变化
            broadcast_client_count()

# --- 5. API 路由 ---
@app.route('/')
def index():
    return jsonify({
        "message": "WutheringWaves Navigator WebSocket Server",
        "status": "running",
        "clients": len(clients),
        "current_state": map_state
    })

@app.route('/api/status')
def api_status():
    return jsonify({
        "clients_count": len(clients),
        "map_state": map_state
    })

# --- 6. 启动服务器 (保持不变) ---
if __name__ == '__main__':
    print("服务器启动于 http://127.0.0.1:8080")
    print("请在另一个浏览器窗口或设备上打开 index.html")
    app.run(host='0.0.0.0', port=8080, debug=True)
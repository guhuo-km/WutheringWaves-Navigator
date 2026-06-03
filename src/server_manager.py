# -*- coding: utf-8 -*-
import os
import json
import threading
import errno
import socket
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingTCPServer


class ServerThread(threading.Thread):
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
        self._stop_requested = True
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception as e:
            print(f"Error stopping server: {e}")
    
    def force_stop(self):
        self._stop_requested = True
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass


class LocalServerManager:
    def __init__(self):
        self.http_server_thread = None
        self._is_shutting_down = False
        self.last_error = None
        self.last_error_code = None

    def start_servers(self):
        if self.is_running():
            self.last_error = None
            self.last_error_code = None
            print("Server is already running.")
            return True

        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))

            class LocalFileHandler(SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=script_dir, **kwargs)

                def log_message(self, format, *args):
                    pass

            http_server = ThreadingTCPServer(("", 58427), LocalFileHandler)
            http_server.daemon_threads = True
            self.http_server_thread = ServerThread(http_server)
            self.http_server_thread.start()
            self.last_error = None
            self.last_error_code = None
            print("Local file server started in thread (http://localhost:58427)")

            return True
        except OSError as e:
            if e.errno in (errno.EADDRINUSE, 10048):
                self.last_error_code = "PORT_IN_USE"
                self.last_error = "本地地图服务端口 58427 被占用"
                try:
                    with socket.create_connection(("127.0.0.1", 58427), timeout=0.5):
                        self.last_error = "本地地图服务端口 58427 已被其他进程占用"
                except Exception:
                    self.last_error = "本地地图服务启动失败：端口 58427 冲突"
            else:
                self.last_error_code = "OS_ERROR"
                self.last_error = f"本地地图服务启动失败：{e}"
            print(self.last_error)
            self.stop_servers()
            return False
        except Exception as e:
            self.last_error_code = "UNKNOWN"
            self.last_error = f"本地地图服务启动失败：{e}"
            print(f"Failed to start server: {e}")
            self.stop_servers()
            return False

    def stop_servers(self):
        if self._is_shutting_down:
            return

        self._is_shutting_down = True

        def stop_http_server():
            if self.http_server_thread and self.http_server_thread.is_alive():
                print("Stopping file server...")
                try:
                    self.http_server_thread.stop()
                    self.http_server_thread.join(timeout=0.5)
                    print("File server stopped")
                except Exception as e:
                    print(f"Error stopping file server: {e}")
                finally:
                    self.http_server_thread = None

        http_stopper = threading.Thread(target=stop_http_server, daemon=True)
        http_stopper.start()
        http_stopper.join(timeout=1)

        if http_stopper.is_alive():
            print("HTTP stop thread timeout, force cleanup")
            self.http_server_thread = None

        self._is_shutting_down = False
        print("Server stopped")

    def is_running(self):
        try:
            return (not self._is_shutting_down and
                    self.http_server_thread is not None and
                    self.http_server_thread.is_alive())
        except Exception:
            return False

    def get_local_maps(self):
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            maps_json_path = os.path.join(script_dir, 'maps.json')
            with open(maps_json_path, 'r', encoding='utf-8') as f:
                return [item['name'] for item in json.load(f)]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def delete_local_map(self, map_name: str) -> bool:
        """
        Delete a local map and its associated files

        Args:
            map_name: Name of the map to delete

        Returns:
            True if deletion successful, False otherwise
        """
        try:
            import shutil
            script_dir = os.path.dirname(os.path.abspath(__file__))
            maps_json_path = os.path.join(script_dir, 'maps.json')

            # Load maps.json
            with open(maps_json_path, 'r', encoding='utf-8') as f:
                maps_data = json.load(f)

            # Find the map entry
            map_entry = None
            for item in maps_data:
                if item['name'] == map_name:
                    map_entry = item
                    break

            if not map_entry:
                print(f"Map not found in maps.json: {map_name}")
                return False

            # Remove from maps.json
            maps_data.remove(map_entry)
            with open(maps_json_path, 'w', encoding='utf-8') as f:
                json.dump(maps_data, f, indent=4, ensure_ascii=False)

            # Delete tiles directory if tiled
            if map_entry.get('tiled', False):
                tiles_dir = os.path.join(script_dir, 'tiles', map_name)
                if os.path.exists(tiles_dir):
                    shutil.rmtree(tiles_dir)
                    print(f"Deleted tiles directory: {tiles_dir}")

            # Delete image file if not tiled
            else:
                images_dir = os.path.join(script_dir, 'images')
                # Try to find and delete the image file
                for file in os.listdir(images_dir):
                    if file.startswith(map_name):
                        image_path = os.path.join(images_dir, file)
                        os.remove(image_path)
                        print(f"Deleted image file: {image_path}")
                        break

            print(f"Successfully deleted map: {map_name}")
            return True

        except Exception as e:
            print(f"Failed to delete map {map_name}: {e}")
            import traceback
            traceback.print_exc()
            return False

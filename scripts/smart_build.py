#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能打包脚本 - WutheringWaves Navigator
可以从任意位置运行，自动定位项目根目录

使用方法:
1. 直接运行: python smart_build.py
2. 指定项目路径: python smart_build.py /path/to/project
3. 交互式选择: python smart_build.py --interactive

作者: Claude
版本: 2.0
"""

import os
import sys
import subprocess
import platform
import shutil
import json
import argparse
import re
from pathlib import Path
import importlib.util

class SmartBuilder:
    def __init__(
        self,
        project_path=None,
        include_local_maps=False,
        include_images=False,
        include_runtime_configs=False,
        update_base_url=None,
        no_clean=False,
        skip_deps=False,
        skip_updater=False,
    ):
        self.script_dir = Path(__file__).parent.absolute()
        self.python_version = f"{sys.version_info.major}{sys.version_info.minor}"
        self.platform_system = platform.system()
        self.architecture = platform.architecture()[0]
        self.include_local_maps = include_local_maps
        self.include_images = include_images
        self.include_runtime_configs = include_runtime_configs
        self.update_base_url = (update_base_url or os.environ.get("WUWA_UPDATE_BASE_URL") or "").rstrip("/")
        self.no_clean = no_clean
        self.skip_deps = skip_deps
        self.skip_updater = skip_updater
        
        # 项目识别标志文件
        self.project_markers = [
            'src/main_app.py',
            'requirements.txt',
            'requirements_fluent.txt',
            'assets/ico.ico',
            'languages',
            'models'
        ]
        
        # 项目结构配置
        self.project_config = {
            'name': 'WutheringWaves-Navigator',
            'main_script': 'src/main_app.py',
            'icon': 'assets/ico.ico',
            'data_dirs': [
                {
                    'dest': 'languages',
                    'candidates': ['languages'],
                    'required': True
                },
                {
                    'dest': 'models',
                    'candidates': ['models'],
                    'required': True,
                    'include_files': ['class_names.txt', 'coord_ocr.onnx', 'README.md'],
                },
                {
                    'dest': 'templates',
                    'candidates': ['templates'],
                    'required': True
                },
                {
                    'dest': 'js',
                    'candidates': ['js'],
                    'required': False
                },
                {
                    'dest': 'assets',
                    'candidates': ['assets'],
                    'required': False
                },
                {
                    'dest': 'tiles',
                    'candidates': ['.runtime/tiles'],
                    'required': False,
                    'group': 'local_maps'
                },
                {
                    'dest': 'images',
                    'candidates': ['.runtime/images'],
                    'required': False,
                    'group': 'map_images'
                }
            ],
            'data_files': [
                'version.json',
                'src/index.html',
                'src/jszip.min.js'
            ],
            'local_map_files': [
                '.runtime/config/maps.json'
            ],
            'runtime_data_files': [
                '.runtime/config/ocr_config.json',
                '.runtime/config/app_settings.json'
            ],
            'requirements_files': ['requirements_fluent.txt', 'requirements.txt']
        }
        
        # 必需的依赖包
        self.package_import_aliases = {
            'opencv-python': 'cv2',
            'Pillow': 'PIL',
            'pyinstaller': 'PyInstaller',
            'PySide6-Fluent-Widgets': 'qfluentwidgets',
            'PySideSix-Frameless-Window': 'qframelesswindow'
        }
        self.required_packages = [
            'pyinstaller>=5.13.0',
            'PySide6>=6.5.0',
            'PySide6-Fluent-Widgets>=1.10.5',
            'PySideSix-Frameless-Window>=0.4.0',
            'keyboard>=0.13.5',
            'jinja2>=3.1.0',
            'darkdetect',
            'colorthief',
            'opencv-python>=4.8.0',
            'Pillow>=10.0.0',
            'numpy>=1.24.0',
            'onnxruntime>=1.23.0',
            'requests>=2.31.0'
        ]
        
        # 查找项目根目录
        self.project_root = self.find_project_root(project_path)
        if not self.project_root:
            print("[ERROR] 无法找到项目根目录！")
            sys.exit(1)

    def find_project_root(self, specified_path=None):
        """智能查找项目根目录"""
        print("[SEARCH] 正在查找项目根目录...")
        
        # 如果指定了路径，直接验证
        if specified_path:
            path = Path(specified_path).absolute()
            if self.is_project_root(path):
                print(f"[FOUND] 使用指定路径: {path}")
                return path
            else:
                print(f"[ERROR] 指定路径不是有效的项目目录: {path}")
                return None
        
        # 搜索候选目录
        search_paths = [
            # 1. 脚本所在目录
            self.script_dir,
            # 2. 脚本父目录
            self.script_dir.parent,
            # 3. 脚本祖父目录
            self.script_dir.parent.parent,
            # 4. 当前工作目录
            Path.cwd(),
            # 5. 当前工作目录的父目录
            Path.cwd().parent,
        ]
        
        # 按名称搜索
        potential_names = [
            'WutheringWaves-Navigator',
            'WutheringWaves-Navigator-main',
            'wutheringwaves-navigator',
            'Navigator'
        ]
        
        # 在常见位置搜索项目目录
        common_locations = [
            Path.home() / 'Downloads',
            Path.home() / 'Desktop',
            Path.home() / 'Documents',
            Path('C:/'),
            Path('D:/'),
        ]
        
        # 扩展搜索路径
        for location in common_locations:
            if location.exists():
                for name in potential_names:
                    search_paths.append(location / name)
                
                # 也搜索下载目录中的子目录
                if location.name == 'Downloads':
                    try:
                        for subdir in location.iterdir():
                            if subdir.is_dir() and any(n.lower() in subdir.name.lower() for n in ['wuthering', 'navigator']):
                                search_paths.append(subdir)
                    except:
                        pass
        
        # 验证搜索路径
        for path in search_paths:
            if path.exists() and self.is_project_root(path):
                print(f"[FOUND] 找到项目根目录: {path}")
                return path
        
        print("[NOT FOUND] 在以下位置搜索项目目录:")
        for path in search_paths[:10]:  # 只显示前10个
            print(f"  - {path}")
        
        return None

    def is_project_root(self, path):
        """检查目录是否为项目根目录"""
        if not path.is_dir():
            return False
        
        # 检查关键标志文件
        required_markers = ['src/main_app.py']
        for marker in required_markers:
            if not (path / marker).exists():
                return False

        if not (path / 'requirements.txt').exists() and not (path / 'requirements_fluent.txt').exists():
            return False
        
        # 检查可选标志
        optional_markers = ['assets/ico.ico', 'languages', 'models']
        found_optional = sum(1 for marker in optional_markers if (path / marker).exists())
        
        # 至少要有一个可选标志
        return found_optional >= 1

    def print_banner(self):
        """打印欢迎横幅"""
        banner = f"""
{'='*60}
    WutheringWaves Navigator - 智能打包工具 v2.0
{'='*60}
[PC]  操作系统: {self.platform_system} ({self.architecture})
[PY]  Python版本: {sys.version.split()[0]}
[SCRIPT] 脚本位置: {self.script_dir}
[PROJECT] 项目目录: {self.project_root}
[APP] 目标应用: {self.project_config['name']}
[MAP] 本地地图资源: {'包含' if self.include_local_maps else '跳过'}
[IMG] 地图图片资源: {'包含' if self.include_images else '跳过'}
[CFG] 运行时配置: {'包含' if self.include_runtime_configs else '跳过'}
{'='*60}
"""
        print(banner)

    def interactive_select_project(self):
        """交互式选择项目目录"""
        print("\n[INTERACTIVE] 交互式项目选择")
        print("=" * 40)
        
        while True:
            path_input = input("\n请输入项目目录路径 (或按Enter搜索): ").strip()
            
            if not path_input:
                # 执行自动搜索
                return self.find_project_root()
            
            path = Path(path_input).expanduser().absolute()
            if self.is_project_root(path):
                return path
            else:
                print(f"[ERROR] 不是有效的项目目录: {path}")
                print("请确保目录包含 src/main_app.py 和 requirements.txt 或 requirements_fluent.txt")
                
                retry = input("是否重试? (Y/N): ").strip().lower()
                if retry not in ['y', 'yes', '是']:
                    return None

    def check_python_version(self):
        """检查Python版本兼容性"""
        print("[CHECK] 检查Python版本...")
        if sys.version_info < (3, 8):
            print("[ERROR] 错误: 需要Python 3.8或更高版本")
            print(f"   当前版本: {sys.version}")
            return False
        print(f"[OK] Python版本检查通过: {sys.version.split()[0]}")
        return True

    def check_project_structure(self):
        """检查项目目录结构"""
        print("[CHECK] 检查项目结构...")
        missing_items = []
        
        # 检查主脚本
        main_script = self.project_root / self.project_config['main_script']
        if not main_script.exists():
            missing_items.append(f"主脚本: {self.project_config['main_script']}")
        
        # 检查图标文件
        icon_file = self.project_root / self.project_config['icon']
        if not icon_file.exists():
            print(f"[WARN] 警告: 图标文件不存在: {self.project_config['icon']}")
        
        # 检查数据目录
        for data_dir in self.project_config['data_dirs']:
            if not self.should_include_group(data_dir.get('group')):
                continue
            dir_path = self.resolve_data_dir(data_dir['candidates'])
            if not dir_path:
                if data_dir.get('required'):
                    missing_items.append(f"目录: {data_dir['dest']}")
                else:
                    print(f"[WARN] 可选目录不存在: {data_dir['dest']}")
        
        # 检查数据文件
        for data_file in self.project_config['data_files']:
            file_path = self.project_root / data_file
            if not file_path.exists():
                missing_items.append(f"文件: {data_file}")

        if self.include_local_maps:
            for data_file in self.project_config.get('local_map_files', []):
                file_path = self.project_root / data_file
                if not file_path.exists():
                    print(f"[WARN] 本地地图配置不存在: {data_file}")
        
        if missing_items:
            print("[ERROR] 项目结构检查失败，缺少以下项目:")
            for item in missing_items:
                print(f"   - {item}")
            return False
        
        print("[OK] 项目结构检查通过")
        return True

    def check_package_installed(self, package_name):
        """检查包是否已安装"""
        clean_name = re.split(r'[<>=]', package_name, maxsplit=1)[0].strip()
        import_name = self.package_import_aliases.get(clean_name, clean_name.replace('-', '_'))
        spec = importlib.util.find_spec(import_name)
        return spec is not None

    def select_requirements_file(self):
        """选择可用的requirements文件"""
        for filename in self.project_config['requirements_files']:
            if (self.project_root / filename).exists():
                return filename
        return None

    def resolve_data_dir(self, candidates):
        """按候选顺序查找可用的目录"""
        for rel_path in candidates:
            dir_path = self.project_root / rel_path
            if dir_path.exists() and dir_path.is_dir():
                return dir_path
        return None

    def should_include_group(self, group_name):
        if group_name == 'local_maps':
            return self.include_local_maps
        if group_name == 'map_images':
            return self.include_images
        return True

    def install_requirements(self):
        """检查并安装依赖包"""
        print("[CHECK] 检查依赖包...")
        
        # 检查requirements文件
        req_filename = self.select_requirements_file()
        if req_filename:
            req_file = self.project_root / req_filename
            print(f"[INFO] 使用依赖文件: {req_filename}")
            try:
                subprocess.run([
                    sys.executable, '-m', 'pip', 'install', '-r', str(req_file)
                ], check=True, capture_output=True, text=True)
                print("[OK] requirements安装完成")
            except subprocess.CalledProcessError as e:
                print(f"[WARN] requirements安装出现问题: {e}")
                print("继续检查必需包...")
        else:
            print("[WARN] 未找到requirements文件，跳过依赖文件安装")
        
        # 检查必需的包
        missing_packages = []
        for package in self.required_packages:
            package_name = re.split(r'[<>=]', package, maxsplit=1)[0].strip()
            if not self.check_package_installed(package_name):
                missing_packages.append(package)
        
        if missing_packages:
            print(f"[INSTALL] 需要安装 {len(missing_packages)} 个缺失的包:")
            for package in missing_packages:
                print(f"   - {package}")
            
            print("[START] 开始安装缺失的包...")
            for package in missing_packages:
                try:
                    print(f"   安装: {package}")
                    subprocess.run([
                        sys.executable, '-m', 'pip', 'install', package
                    ], check=True, capture_output=True)
                    print(f"   [OK] {package} 安装成功")
                except subprocess.CalledProcessError as e:
                    print(f"   [ERROR] {package} 安装失败: {e}")
                    return False
        else:
            print("[OK] 所有必需包已安装")
        
        return True

    def get_python_dll_path(self):
        """自动获取Python DLL路径"""
        python_dll_name = f"python{self.python_version}.dll"
        
        possible_paths = [
            Path(sys.executable).parent / python_dll_name,
            Path(sys.exec_prefix) / python_dll_name,
            Path(sys.prefix) / python_dll_name,
        ]
        
        for dll_path in possible_paths:
            if dll_path.exists():
                print(f"[CHECK] 找到Python DLL: {dll_path}")
                return str(dll_path)
        
        print(f"[WARN] 警告: 未找到 {python_dll_name}")
        return None

    def clean_build_dirs(self):
        """清理旧的构建目录"""
        print("[CLEAN] 清理旧的构建文件...")
        dirs_to_clean = ['build', 'dist']
        
        for dir_name in dirs_to_clean:
            dir_path = self.project_root / dir_name
            if dir_path.exists():
                shutil.rmtree(dir_path)
                print(f"   删除目录: {dir_name}")
        
        # 不删除spec文件，避免误删参考文件

    def build_pyinstaller_args(self):
        """构建PyInstaller参数"""
        print("[CONFIG] 配置打包参数...")
        
        args = [
            '--onedir',
            '--noconsole',
            f'--name={self.project_config["name"]}-Smart',
            f'--paths={self.project_root / "src"}',
        ]
        if not self.no_clean:
            args.append('--clean')
        else:
            args.append('--noconfirm')
        
        # 图标
        icon_path = self.project_root / self.project_config['icon']
        if icon_path.exists():
            args.append(f'--icon={icon_path}')
        
        # 添加数据目录
        for data_dir in self.project_config['data_dirs']:
            if not self.should_include_group(data_dir.get('group')):
                continue
            dir_path = self.resolve_data_dir(data_dir['candidates'])
            if dir_path:
                include_files = data_dir.get('include_files')
                if include_files:
                    for file_name in include_files:
                        file_path = dir_path / file_name
                        if file_path.exists():
                            args.append(f'--add-data={file_path}{os.pathsep}{data_dir["dest"]}')
                        elif data_dir.get('required'):
                            print(f"[WARN] 必需资源文件不存在: {file_path}")
                else:
                    args.append(f'--add-data={dir_path}{os.pathsep}{data_dir["dest"]}')
        
        # 添加数据文件
        data_files = list(self.project_config['data_files'])
        if self.include_local_maps:
            data_files.extend(self.project_config.get('local_map_files', []))
        if self.include_runtime_configs:
            data_files.extend(self.project_config.get('runtime_data_files', []))
        for data_file in data_files:
            file_path = self.project_root / data_file
            if file_path.exists():
                args.append(f'--add-data={file_path}{os.pathsep}.')
        
        # 添加Python DLL
        python_dll = self.get_python_dll_path()
        if python_dll:
            args.append(f'--add-binary={python_dll}{os.pathsep}.')
        
        # 收集依赖
        collect_packages = ['onnxruntime', 'cv2', 'qfluentwidgets', 'qframelesswindow']
        for package in collect_packages:
            if self.check_package_installed(package):
                args.append(f'--collect-all={package}')
        
        # 隐式导入
        hidden_imports = [
            'PySide6.QtCore',
            'PySide6.QtWidgets', 
            'PySide6.QtWebEngineWidgets',
            'PySide6.QtWebEngineCore',
            'PySide6.QtGui',
            'PySide6.QtNetwork',
            'PySide6.QtWebChannel'
        ]
        for module in hidden_imports:
            args.append(f'--hidden-import={module}')
        
        # 排除多余的 Qt 绑定和旧 PyTorch 推理栈
        excluded_modules = [
            'PyQt5',
            'torch',
            'torchvision',
            'ultralytics',
            'matplotlib',
            'pandas',
            'scipy',
            'pytest',
        ]
        for module in excluded_modules:
            args.append(f'--exclude-module={module}')
        
        # 主脚本
        main_script = self.project_root / self.project_config['main_script']
        args.append(str(main_script))

        
        return args

    def run_pyinstaller(self, args):
        """运行PyInstaller"""
        print("[START] 开始打包...")
        print("[INFO] PyInstaller参数:")
        for arg in args:
            print(f"   {arg}")

        # 切换到项目目录
        original_cwd = os.getcwd()
        os.chdir(self.project_root)

        try:
            import PyInstaller.__main__
            PyInstaller.__main__.run(args)
            return True
        except Exception as e:
            print(f"[ERROR] 打包失败: {e}")
            return False
        finally:
            os.chdir(original_cwd)

    def inject_dist_version_info(self):
        """Inject production update URL into packaged version.json when configured."""
        if not self.update_base_url:
            print("[INFO] 未配置更新地址，保留公开源码默认 version.json")
            return True

        source_version = self.project_root / "version.json"
        dist_version = self.project_root / "dist" / "WutheringWaves-Navigator-Smart" / "version.json"
        if not source_version.exists():
            print("[ERROR] version.json 不存在，无法注入更新地址")
            return False

        try:
            version_info = json.loads(source_version.read_text(encoding="utf-8"))
            version_info["update_base_url"] = f"{self.update_base_url}/latest.json"
            dist_version.parent.mkdir(parents=True, exist_ok=True)
            dist_version.write_text(json.dumps(version_info, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[OK] 已注入更新地址到打包产物: {version_info['update_base_url']}")
            return True
        except Exception as e:
            print(f"[ERROR] 注入更新地址失败: {e}")
            return False

    def build_updater(self):
        """构建独立更新器并复制到主程序目录"""
        updater_script = self.project_root / "src" / "updater_app.py"
        if not updater_script.exists():
            print("[WARN] updater_app.py 不存在，跳过更新器构建")
            return True

        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--paths",
            str(self.project_root / "src"),
            "--onefile",
            "--noconsole",
            "--clean",
            "--name",
            "WutheringWaves-Updater",
            "--exclude-module",
            "PySide6",
            "--exclude-module",
            "qfluentwidgets",
            "--exclude-module",
            "qframelesswindow",
            "--exclude-module",
            "cv2",
            "--exclude-module",
            "onnxruntime",
            str(updater_script),
        ]
        print("[BUILD] 正在构建独立更新器...")
        result = subprocess.run(cmd, cwd=self.project_root)
        if result.returncode != 0:
            print("[ERROR] 更新器构建失败")
            return False

        updater_exe = self.project_root / "dist" / "WutheringWaves-Updater.exe"
        target_exe = self.project_root / "dist" / "WutheringWaves-Navigator-Smart" / "WutheringWaves-Updater.exe"
        if updater_exe.exists():
            shutil.copy2(updater_exe, target_exe)
            print(f"[OK] 更新器已复制到: {target_exe}")
            return True

        print("[ERROR] 未找到更新器构建产物")
        return False

    def prune_packaged_artifacts(self):
        """删除打包后明确不需要的大体积运行文件。"""
        dist_dir = self.project_root / "dist" / "WutheringWaves-Navigator-Smart"
        if not dist_dir.exists():
            print("[WARN] 构建目录不存在，跳过体积裁剪")
            return True

        prune_patterns = (
            "_internal/PySide6/resources/qtwebengine_devtools_resources.debug.pak",
            "_internal/cv2/opencv_videoio_ffmpeg*_64.dll",
        )
        removed_count = 0
        removed_bytes = 0
        for pattern in prune_patterns:
            for path in dist_dir.glob(pattern):
                if not path.is_file():
                    continue
                size = path.stat().st_size
                path.unlink()
                removed_count += 1
                removed_bytes += size
                print(f"[PRUNE] 删除无用打包文件: {path.relative_to(dist_dir)} ({size / 1024 / 1024:.1f} MB)")

        print(f"[PRUNE] 共删除 {removed_count} 个文件，节省 {removed_bytes / 1024 / 1024:.1f} MB")
        return True

    def verify_build(self):
        """验证构建结果"""
        print("[CHECK] 验证构建结果...")

        dist_dir = self.project_root / 'dist' / f'{self.project_config["name"]}-Smart'
        exe_file = dist_dir / f'{self.project_config["name"]}-Smart.exe'
        updater_file = dist_dir / 'WutheringWaves-Updater.exe'

        if not dist_dir.exists():
            print("[ERROR] 构建目录不存在")
            return False

        if not exe_file.exists():
            print("[ERROR] 可执行文件不存在")
            return False

        if updater_file.exists():
            print(f"[OK] 更新器存在: {updater_file.name}")
        else:
            print(f"[WARN] 更新器不存在: {updater_file.name}")
        
        # 检查关键文件
        internal_dir = dist_dir / '_internal'
        python_dll = internal_dir / f'python{self.python_version}.dll'
        
        if python_dll.exists():
            print(f"[OK] Python DLL存在: {python_dll.name}")
        else:
            print(f"[WARN] 警告: Python DLL不存在: python{self.python_version}.dll")

        resource_root = internal_dir if internal_dir.exists() else dist_dir
        required_resources = [
            "assets/ico.ico",
            "assets/ico.png",
            "assets/icons/ocr_settings.svg",
            "assets/icons/map_settings.svg",
            "assets/icons/route_recording.svg",
            "assets/icons/hotkey.svg",
            "assets/icons/mouse_middle.svg",
            "assets/icons/mouse_x1.svg",
            "assets/icons/mouse_x2.svg",
            "js/wuwa_map_optimizer.js",
            "js/wuwa_map_optimizer_lite.js",
            "index.html",
            "jszip.min.js",
        ]
        missing_resources = []
        for rel_path in required_resources:
            if not (resource_root / rel_path).exists():
                missing_resources.append(rel_path)

        if missing_resources:
            print("[WARN] 警告: 构建结果缺少以下资源:")
            for rel_path in missing_resources:
                print(f"   - {rel_path}")
        else:
            print("[OK] 关键资源校验通过")

        # 显示构建信息
        exe_size = exe_file.stat().st_size / (1024 * 1024)
        print(f"[INSTALL] 可执行文件大小: {exe_size:.1f} MB")
        print(f"[DIR] 构建目录: {dist_dir}")
        print(f"[TARGET] 可执行文件: {exe_file}")
        
        return True

    def create_usage_info(self):
        """创建使用说明文件"""
        dist_dir = self.project_root / 'dist' / f'{self.project_config["name"]}-Smart'
        if not dist_dir.exists():
            return
        
        usage_info = f"""
# {self.project_config['name']} - 使用说明

## 系统信息
- 构建系统: {self.platform_system} {self.architecture}
- Python版本: {sys.version.split()[0]}
- 项目路径: {self.project_root}
- 构建时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 文件说明
- {self.project_config['name']}-Smart.exe: 主程序
- _internal/: 依赖文件夹（必须保留）

## 使用方法
1. 直接运行 {self.project_config['name']}-Smart.exe
2. 或将整个文件夹复制到其他计算机使用

## 注意事项
- 请保持 _internal 文件夹完整
- 如遇到问题，请检查是否安装了 Microsoft Visual C++ Redistributable

## 技术支持
如遇问题，请检查：
1. Windows系统是否为64位
2. 是否安装了最新的 Visual C++ 运行库
3. 防火墙和杀毒软件设置
"""
        
        readme_file = dist_dir / 'README.txt'
        with open(readme_file, 'w', encoding='utf-8') as f:
            f.write(usage_info)
        
        print(f"[FILE] 创建使用说明: {readme_file}")

    def build(self):
        """主要构建流程"""
        self.print_banner()
        
        # 检查环境
        if not self.check_python_version():
            return False
        
        if not self.check_project_structure():
            return False
        
        if self.skip_deps:
            print("[FAST] 跳过依赖安装检查")
        elif not self.install_requirements():
            print("[ERROR] 依赖安装失败，终止构建")
            return False
        
        if self.no_clean:
            print("[FAST] 跳过 build/dist 清理并复用 PyInstaller 缓存")
        else:
            self.clean_build_dirs()
        
        # 构建参数
        args = self.build_pyinstaller_args()
        
        # 执行打包
        if not self.run_pyinstaller(args):
            return False

        # 注入仅用于成品的更新地址；源码 version.json 继续保持公开安全默认值
        if not self.inject_dist_version_info():
            return False

        if self.skip_updater:
            print("[FAST] 跳过更新器构建")
        elif not self.build_updater():
            return False

        # 删除明确不需要的调试/视频运行文件
        if not self.prune_packaged_artifacts():
            return False

        # 验证结果
        if not self.verify_build():
            return False
        
        print("[SUCCESS] 打包完成！")
        print(f"[OUTPUT] 输出目录: {self.project_root / 'dist'}")
        return True

def parse_build_args(argv=None):
    parser = argparse.ArgumentParser(description='WutheringWaves Navigator 智能打包工具')
    parser.add_argument('project_path', nargs='?', help='项目目录路径')
    parser.add_argument('--interactive', '-i', action='store_true', help='交互式选择项目目录')
    parser.add_argument('--include-local-maps', action='store_true', help='包含本地地图瓦片资源')
    parser.add_argument('--skip-local-maps', action='store_true', help='跳过本地地图瓦片资源（可用于覆盖 include-local-maps）')
    parser.add_argument('--include-images', action='store_true', help='包含本地地图图片资源')
    parser.add_argument('--include-runtime-configs', action='store_true', help='包含运行时生成的配置JSON')
    parser.add_argument('--fast', action='store_true', help='开发快速打包：等同于 --no-clean --skip-deps --skip-updater')
    parser.add_argument('--no-clean', action='store_true', help='不清理 build/dist，不传 PyInstaller --clean，复用缓存')
    parser.add_argument('--skip-deps', action='store_true', help='跳过 requirements 安装/依赖检查')
    parser.add_argument('--skip-updater', action='store_true', help='跳过独立更新器打包，复用现有更新器')
    parser.add_argument(
        '--update-base-url',
        default=None,
        help='成品更新源基础 URL，例如 https://example.com/app/stable；也可用 WUWA_UPDATE_BASE_URL',
    )
    args = parser.parse_args(argv)
    if args.fast:
        args.no_clean = True
        args.skip_deps = True
        args.skip_updater = True
    return args


def main():
    """主函数"""
    args = parse_build_args()
    
    def pause_if_interactive(message):
        if sys.stdin and sys.stdin.isatty():
            try:
                input(message)
            except EOFError:
                print(message)
        else:
            print(message)

    try:
        include_local_maps = args.include_local_maps
        if args.skip_local_maps:
            include_local_maps = False
        include_images = args.include_images
        include_runtime_configs = args.include_runtime_configs

        if args.interactive:
            builder = SmartBuilder(
                include_local_maps=include_local_maps,
                include_images=include_images,
                include_runtime_configs=include_runtime_configs,
                update_base_url=args.update_base_url,
                no_clean=args.no_clean,
                skip_deps=args.skip_deps,
                skip_updater=args.skip_updater,
            )
            project_path = builder.interactive_select_project()
            if not project_path:
                print("[ERROR] 未选择有效的项目目录")
                return 1
            builder = SmartBuilder(
                project_path,
                include_local_maps=include_local_maps,
                include_images=include_images,
                include_runtime_configs=include_runtime_configs,
                update_base_url=args.update_base_url,
                no_clean=args.no_clean,
                skip_deps=args.skip_deps,
                skip_updater=args.skip_updater,
            )
        else:
            builder = SmartBuilder(
                args.project_path,
                include_local_maps=include_local_maps,
                include_images=include_images,
                include_runtime_configs=include_runtime_configs,
                update_base_url=args.update_base_url,
                no_clean=args.no_clean,
                skip_deps=args.skip_deps,
                skip_updater=args.skip_updater,
            )
        
        success = builder.build()
        if success:
            pause_if_interactive("\n[OK] 构建成功！按回车键退出...")
            return 0
        else:
            pause_if_interactive("\n[ERROR] 构建失败！按回车键退出...")
            return 1
            
    except KeyboardInterrupt:
        print("\n[STOP] 用户中断操作")
        return 1
    except Exception as e:
        print(f"\n[CRASH] 意外错误: {e}")
        pause_if_interactive("按回车键退出...")
        return 1

if __name__ == '__main__':
    sys.exit(main())

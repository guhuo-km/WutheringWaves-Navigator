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
from pathlib import Path
import importlib.util

class SmartBuilder:
    def __init__(self, project_path=None):
        self.script_dir = Path(__file__).parent.absolute()
        self.python_version = f"{sys.version_info.major}{sys.version_info.minor}"
        self.platform_system = platform.system()
        self.architecture = platform.architecture()[0]
        
        # 项目识别标志文件
        self.project_markers = [
            'src/main_app.py',
            'requirements.txt',
            'assets/ico.ico',
            'languages',
            'models'
        ]
        
        # 项目结构配置
        self.project_config = {
            'name': 'WutheringWaves-Navigator',
            'main_script': 'src/main_app.py',
            'icon': 'assets/ico.ico',
            'data_dirs': ['languages', 'models', 'config'],
            'data_files': ['web/index.html'],
            'requirements_file': 'requirements.txt'
        }
        
        # 必需的依赖包
        self.required_packages = [
            'pyinstaller>=5.13.0',
            'PySide6>=6.5.0',
            'opencv-python>=4.8.0',
            'numpy>=1.24.0',
            'ultralytics>=8.0.0',
            'torch>=2.0.0',
            'werkzeug>=2.3.0',
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
        required_markers = ['src/main_app.py', 'requirements.txt']
        for marker in required_markers:
            if not (path / marker).exists():
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
                print("请确保目录包含 src/main_app.py 和 requirements.txt")
                
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
            dir_path = self.project_root / data_dir
            if not dir_path.exists():
                missing_items.append(f"目录: {data_dir}")
        
        # 检查数据文件
        for data_file in self.project_config['data_files']:
            file_path = self.project_root / data_file
            if not file_path.exists():
                missing_items.append(f"文件: {data_file}")
        
        if missing_items:
            print("[ERROR] 项目结构检查失败，缺少以下项目:")
            for item in missing_items:
                print(f"   - {item}")
            return False
        
        print("[OK] 项目结构检查通过")
        return True

    def check_package_installed(self, package_name):
        """检查包是否已安装"""
        clean_name = package_name.split('>=')[0].split('==')[0].split('<')[0]
        spec = importlib.util.find_spec(clean_name.replace('-', '_'))
        return spec is not None

    def install_requirements(self):
        """检查并安装依赖包"""
        print("[CHECK] 检查依赖包...")
        
        # 检查requirements.txt
        req_file = self.project_root / self.project_config['requirements_file']
        if req_file.exists():
            print(f"[INFO] 发现requirements.txt文件")
            try:
                result = subprocess.run([
                    sys.executable, '-m', 'pip', 'install', '-r', str(req_file)
                ], check=True, capture_output=True, text=True)
                print("[OK] requirements.txt安装完成")
            except subprocess.CalledProcessError as e:
                print(f"[WARN] requirements.txt安装出现问题: {e}")
                print("继续检查必需包...")
        
        # 检查必需的包
        missing_packages = []
        for package in self.required_packages:
            package_name = package.split('>=')[0]
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
        
        # 删除spec文件
        for spec_file in self.project_root.glob('*.spec'):
            spec_file.unlink()
            print(f"   删除文件: {spec_file.name}")

    def build_pyinstaller_args(self):
        """构建PyInstaller参数"""
        print("[CONFIG] 配置打包参数...")
        
        args = [
            '--onedir',
            '--noconsole',
            f'--name={self.project_config["name"]}-Smart',
            '--clean',
        ]
        
        # 图标
        icon_path = self.project_root / self.project_config['icon']
        if icon_path.exists():
            args.append(f'--icon={icon_path}')
        
        # 添加数据目录
        for data_dir in self.project_config['data_dirs']:
            dir_path = self.project_root / data_dir
            if dir_path.exists():
                args.append(f'--add-data={dir_path};{data_dir}')
        
        # 添加数据文件
        for data_file in self.project_config['data_files']:
            file_path = self.project_root / data_file
            if file_path.exists():
                args.append(f'--add-data={file_path};.')
        
        # 添加Python DLL
        python_dll = self.get_python_dll_path()
        if python_dll:
            args.append(f'--add-binary={python_dll};.')
        
        # 收集依赖
        collect_packages = ['torch', 'torchvision', 'ultralytics', 'cv2']
        for package in collect_packages:
            if self.check_package_installed(package):
                args.append(f'--collect-all={package}')
        
        # 隐式导入
        hidden_imports = [
            'PySide6.QtCore',
            'PySide6.QtWidgets', 
            'PySide6.QtWebEngineWidgets',
            'PySide6.QtGui',
            'PySide6.QtNetwork'
        ]
        for module in hidden_imports:
            args.append(f'--hidden-import={module}')
        
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

    def verify_build(self):
        """验证构建结果"""
        print("[CHECK] 验证构建结果...")
        
        dist_dir = self.project_root / 'dist' / f'{self.project_config["name"]}-Smart'
        exe_file = dist_dir / f'{self.project_config["name"]}-Smart.exe'
        
        if not dist_dir.exists():
            print("[ERROR] 构建目录不存在")
            return False
        
        if not exe_file.exists():
            print("[ERROR] 可执行文件不存在")
            return False
        
        # 检查关键文件
        internal_dir = dist_dir / '_internal'
        python_dll = internal_dir / f'python{self.python_version}.dll'
        
        if python_dll.exists():
            print(f"[OK] Python DLL存在: {python_dll.name}")
        else:
            print(f"[WARN] 警告: Python DLL不存在: python{self.python_version}.dll")
        
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
        
        # 安装依赖
        if not self.install_requirements():
            print("[ERROR] 依赖安装失败，终止构建")
            return False
        
        # 清理旧文件
        self.clean_build_dirs()
        
        # 构建参数
        args = self.build_pyinstaller_args()
        
        # 执行打包
        if not self.run_pyinstaller(args):
            return False
        
        # 验证结果
        if not self.verify_build():
            return False
        
        # 创建说明文件
        self.create_usage_info()
        
        print("[SUCCESS] 打包完成！")
        print(f"[OUTPUT] 输出目录: {self.project_root / 'dist'}")
        return True

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='WutheringWaves Navigator 智能打包工具')
    parser.add_argument('project_path', nargs='?', help='项目目录路径')
    parser.add_argument('--interactive', '-i', action='store_true', help='交互式选择项目目录')
    
    args = parser.parse_args()
    
    try:
        if args.interactive:
            builder = SmartBuilder()
            project_path = builder.interactive_select_project()
            if not project_path:
                print("[ERROR] 未选择有效的项目目录")
                return 1
            builder = SmartBuilder(project_path)
        else:
            builder = SmartBuilder(args.project_path)
        
        success = builder.build()
        if success:
            input("\n[OK] 构建成功！按回车键退出...")
            return 0
        else:
            input("\n[ERROR] 构建失败！按回车键退出...")
            return 1
            
    except KeyboardInterrupt:
        print("\n[STOP] 用户中断操作")
        return 1
    except Exception as e:
        print(f"\n[CRASH] 意外错误: {e}")
        input("按回车键退出...")
        return 1

if __name__ == '__main__':
    sys.exit(main())
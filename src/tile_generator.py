import os
import json
from PIL import Image
import math
import shutil

# --- 配置 ---
TILE_SIZE = 256
MAX_IMAGE_SIZE_MB = 12
MAX_DIMENSION = 8192
OUTPUT_TILES_DIR = 'tiles'
OUTPUT_IMAGES_DIR = 'images'
MAP_CONFIG_FILE = 'maps.json'

Image.MAX_IMAGE_PIXELS = None

def get_image_info(image_path):
    if not os.path.exists(image_path):
        print(f"错误: 文件 '{image_path}' 不存在。")
        return None, None, None
    file_size_mb = os.path.getsize(image_path) / (1024 * 1024)
    with Image.open(image_path) as img:
        width, height = img.size
    return file_size_mb, width, height

def update_map_config(map_name, is_tiled, width, height, max_zoom):
    config = []
    if os.path.exists(MAP_CONFIG_FILE):
        with open(MAP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                print(f"警告: '{MAP_CONFIG_FILE}' 文件为空或格式错误，将创建新的配置。")
                config = []


    map_entry = next((item for item in config if item["name"] == map_name), None)
    if map_entry:
        map_entry["tiled"] = is_tiled
        map_entry["width"] = width
        map_entry["height"] = height
        map_entry["maxZoom"] = max_zoom if is_tiled else 0
    else:
        config.append({
            "name": map_name,
            "tiled": is_tiled,
            "width": width,
            "height": height,
            "maxZoom": max_zoom if is_tiled else 0
        })
    
    with open(MAP_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    print(f"'{MAP_CONFIG_FILE}' 已更新。")

def process_image(image_path):
    # --- 关键修改：使用不带扩展名的文件名作为地图ID ---
    map_identifier = os.path.splitext(os.path.basename(image_path))[0]
    original_map_name = os.path.basename(image_path)

    file_size_mb, width, height = get_image_info(image_path)

    if file_size_mb is None:
        return

    print(f"\n正在处理 '{original_map_name}' (地图ID: '{map_identifier}'):")
    print(f"  - 尺寸: {width}x{height} 像素")
    print(f"  - 文件大小: {file_size_mb:.2f} MB")

    if file_size_mb > MAX_IMAGE_SIZE_MB or width > MAX_DIMENSION or height > MAX_DIMENSION:
        print("  - 结果: 需要瓦片化处理。")
        generate_tiles(image_path, map_identifier, width, height)
    else:
        print("  - 结果: 作为普通图片处理。")
        os.makedirs(OUTPUT_IMAGES_DIR, exist_ok=True)
        shutil.copy(image_path, os.path.join(OUTPUT_IMAGES_DIR, original_map_name))
        print(f"  - 图片已复制到 '{OUTPUT_IMAGES_DIR}/' 目录。")
        # 对于普通图片，我们仍然使用原始文件名进行配置
        update_map_config(original_map_name, False, width, height, 0)

def generate_tiles(image_path, map_identifier, width, height):
    with Image.open(image_path) as original_img:
        img = original_img.convert("RGBA")
        max_zoom = math.ceil(math.log2(max(width, height) / TILE_SIZE))
        print(f"  - 计算得到最大缩放级别: {max_zoom}")

        for z in range(max_zoom + 1):
            current_width = int(width / (2**(max_zoom - z)))
            current_height = int(height / (2**(max_zoom - z)))
            if current_width == 0 or current_height == 0:
                print(f"  - 跳过 Zoom Level {z} (尺寸过小)")
                continue

            print(f"  - 正在生成 Zoom Level {z} (图像尺寸: {current_width}x{current_height})...")
            scaled_img = img.resize((current_width, current_height), Image.Resampling.LANCZOS)
            
            cols = math.ceil(current_width / TILE_SIZE)
            rows = math.ceil(current_height / TILE_SIZE)

            # --- 核心修改：创建一个能容纳所有瓦片的透明大画布 ---
            canvas_width = cols * TILE_SIZE
            canvas_height = rows * TILE_SIZE
            canvas_img = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
            canvas_img.paste(scaled_img, (0, 0))
            # ----------------------------------------------------

            for x in range(cols):
                for y in range(rows):
                    tile_dir = os.path.join(OUTPUT_TILES_DIR, map_identifier, str(z), str(x))
                    os.makedirs(tile_dir, exist_ok=True)
                    tile_path = os.path.join(tile_dir, f'{y}.png')
                    
                    # 即使文件存在也重新生成，以确保是新逻辑生成的
                    # if os.path.exists(tile_path): continue
                    
                    left = x * TILE_SIZE
                    top = y * TILE_SIZE
                    right = left + TILE_SIZE
                    bottom = top + TILE_SIZE
                    
                    # --- 从大画布上裁剪瓦片，而不是从缩放图上裁剪 ---
                    tile_img = canvas_img.crop((left, top, right, bottom))
                    tile_img.save(tile_path, 'PNG')
        
        print(f"  - 瓦片化完成！所有瓦片已保存至 '{os.path.join(OUTPUT_TILES_DIR, map_identifier)}'。")
        update_map_config(map_identifier, True, width, height, max_zoom)

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("使用方法: python tile_generator.py <图片1.jpg> [图片2.png] ...")
        sys.exit(1)
    
    os.makedirs(OUTPUT_IMAGES_DIR, exist_ok=True)

    for image_file in sys.argv[1:]:
        process_image(image_file)
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YOLOv8 Coordinate OCR Model Fine-Tuning Script
用于对现有的 coord_ocr.pt 模型进行微调，提升特定环境下的识别准确率。

用法:
    python finetune.py --data dataset/data.yaml --epochs 100
    python finetune.py --data dataset/data.yaml --epochs 50 --batch 8 --device cpu
    python finetune.py --data dataset/data.yaml --resume runs/detect/train/weights/last.pt
"""

import argparse
import sys
import json
from pathlib import Path

from ultralytics import YOLO

_PROJECT_ROOT = Path(__file__).resolve().parent


def validate_dataset(data_yaml_path: Path) -> dict:
    """验证数据集结构和标签格式，返回统计信息。"""
    import yaml as yaml_lib

    if not data_yaml_path.exists():
        print(f"错误: 数据集配置文件不存在: {data_yaml_path}")
        sys.exit(1)

    with open(data_yaml_path, "r", encoding="utf-8") as f:
        config = yaml_lib.safe_load(f)

    dataset_root = Path(data_yaml_path.parent)

    for key in ("train", "val"):
        if key not in config:
            print(f"错误: data.yaml 中缺少 '{key}' 字段")
            sys.exit(1)

        images_dir = dataset_root / config[key]
        labels_dir = dataset_root / config[key].replace("images", "labels")

        if not images_dir.exists():
            print(f"错误: 图片目录不存在: {images_dir}")
            sys.exit(1)
        if not labels_dir.exists():
            print(f"错误: 标签目录不存在: {labels_dir}")
            sys.exit(1)

    expected_nc = config.get("nc", 13)
    expected_names = config.get("names", [])
    class_count = len(expected_names)

    stats = {"train_images": 0, "train_labels": 0, "val_images": 0, "val_labels": 0,
             "invalid_labels": 0, "missing_labels": 0, "class_distribution": {}}

    for split_key in ("train", "val"):
        images_dir = dataset_root / config[split_key]
        labels_dir = dataset_root / config[split_key].replace("images", "labels")

        image_files = list(images_dir.glob("*"))
        image_files = [f for f in image_files if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp")]

        stats_key_img = f"{split_key}_images"
        stats_key_lbl = f"{split_key}_labels"
        stats[stats_key_img] = len(image_files)

        for img_file in image_files:
            label_file = labels_dir / f"{img_file.stem}.txt"
            if label_file.exists():
                stats[stats_key_lbl] += 1
                try:
                    with open(label_file, "r") as lf:
                        for line in lf:
                            parts = line.strip().split()
                            if len(parts) < 5:
                                stats["invalid_labels"] += 1
                                continue
                            cls_id = int(parts[0])
                            if cls_id >= class_count:
                                print(f"警告: {label_file} 中存在无效类别ID {cls_id} (最大 {class_count - 1})")
                                stats["invalid_labels"] += 1
                                continue
                            stats["class_distribution"][cls_id] = stats["class_distribution"].get(cls_id, 0) + 1
                except Exception:
                    stats["invalid_labels"] += 1
            else:
                stats["missing_labels"] += 1

    print("\n=== 数据集验证结果 ===")
    print(f"训练集图片: {stats['train_images']}, 标签: {stats['train_labels']}")
    print(f"验证集图片: {stats['val_images']}, 标签: {stats['val_labels']}")
    print(f"无效标签行: {stats['invalid_labels']}")
    print(f"缺失标签文件: {stats['missing_labels']}")
    print(f"类别分布: {stats['class_distribution']}")

    if stats["missing_labels"] > 0:
        print("警告: 部分图片缺少对应的标签文件，训练时将被跳过。")

    if stats["train_images"] < 10:
        print(f"错误: 训练集只有 {stats['train_images']} 张图片 (至少需要10张)")
        sys.exit(1)

    print("数据集验证通过！\n")
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="微调 YOLOv8 坐标 OCR 模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python finetune.py --data dataset/data.yaml
    python finetune.py --data dataset/data.yaml --epochs 200 --batch 16
    python finetune.py --data dataset/data.yaml --device cpu --imgsz 320
        """,
    )
    parser.add_argument("--data", type=str, default=str(_PROJECT_ROOT / "dataset/data.yaml"),
                        help="数据集配置文件路径 (默认: dataset/data.yaml)")
    parser.add_argument("--model", type=str, default=str(_PROJECT_ROOT / "models/coord_ocr.pt"),
                        help="预训练模型路径 (默认: models/coord_ocr.pt)")
    parser.add_argument("--epochs", type=int, default=100,
                        help="训练轮数 (默认: 100)")
    parser.add_argument("--batch", type=int, default=16,
                        help="批次大小 (默认: 16)")
    parser.add_argument("--imgsz", type=str, default="640",
                        help="输入图像尺寸, 如 640 或 64,640 (默认: 640)")
    parser.add_argument("--device", type=str, default="0",
                        help="设备: '0'(GPU0), 'cpu'(CPU), '0,1'(多GPU) (默认: 0)")
    parser.add_argument("--patience", type=int, default=20,
                        help="早停耐心值, 多少轮无改善后停止 (默认: 20)")
    parser.add_argument("--lr", type=float, default=None,
                        help="初始学习率 (默认: 自动)")
    parser.add_argument("--resume", action="store_true",
                        help="从上次中断的检查点恢复训练")
    parser.add_argument("--export", type=str, default=None,
                        help="训练完成后导出模型格式, 如 'onnx', 'torchscript'")
    parser.add_argument("--val-only", action="store_true",
                        help="仅验证现有模型, 不训练")
    parser.add_argument("--verbose", action="store_true",
                        help="显示详细日志")
    parser.add_argument("--color-only", action="store_true",
                        help="仅使用色彩增强（关闭所有几何变换），适合固定字体坐标识别")

    args = parser.parse_args()

    data_path = Path(args.data)
    model_path = Path(args.model)

    # 仅验证模式
    if args.val_only:
        if not model_path.exists():
            print(f"错误: 模型文件不存在: {model_path}")
            sys.exit(1)
        print(f"加载模型进行验证: {model_path}")
        model = YOLO(str(model_path))
        results = model.val(data=str(data_path), device=args.device, verbose=args.verbose)
        print(f"验证完成: {results}")
        return

    # 验证数据集
    print(f"验证数据集: {data_path}")
    validate_dataset(data_path)

    # 检查模型
    if not model_path.exists():
        print(f"错误: 模型文件不存在: {model_path}")
        print("请确认 models/coord_ocr.pt 文件存在, 或使用 --model 指定其他路径")
        sys.exit(1)

    # 加载模型
    print(f"加载预训练模型: {model_path}")
    model = YOLO(str(model_path))

    # 解析 imgsz: 支持 "640" 或 "64,640"
    imgsz_val = args.imgsz
    if ',' in imgsz_val:
        imgsz_val = tuple(int(x.strip()) for x in imgsz_val.split(','))
    else:
        imgsz_val = int(imgsz_val)

    # 构建训练参数
    train_args = dict(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=imgsz_val,
        batch=args.batch,
        device=args.device,
        patience=args.patience,
        resume=args.resume,
        verbose=args.verbose,
        exist_ok=True,
    )

    if args.color_only:
        train_args.update(dict(
            # 关闭所有几何变换
            degrees=0.0,
            translate=0.0,
            scale=0.3,
            shear=0.0,
            perspective=0.0,
            flipud=0.0,
            fliplr=0.0,
            mosaic=0.0,
            mixup=0.0,
            copy_paste=0.0,
            erasing=0.0,
            # 增强色彩抖动
            hsv_h=0.03,
            hsv_s=1.0,
            hsv_v=0.8,
        ))
        print("增强模式: 仅色彩增强，禁用几何变换")
    if args.lr is not None:
        train_args["lr0"] = args.lr

    print("\n=== 开始微调训练 ===")
    print(f"数据集: {data_path}")
    print(f"轮数: {args.epochs}, 批次: {args.batch}, 尺寸: {args.imgsz}")
    print(f"设备: {args.device}, 早停: {args.patience}")

    results = model.train(**train_args)

    # 训练结果摘要
    print("\n=== 训练完成 ===")
    output_dir = Path("runs/detect/train")
    best_pt = output_dir / "weights/best.pt"
    if best_pt.exists():
        print(f"最佳模型: {best_pt}")
        print("将 best.pt 重命名为 coord_ocr.pt 并替换 models/ 目录下的原文件即可使用。")

    # 导出
    if args.export:
        print(f"\n导出模型为 {args.export} 格式...")
        best_model = YOLO(str(best_pt))
        best_model.export(format=args.export)
        print(f"导出完成: {output_dir / f'weights/best.{args.export}'}")


if __name__ == "__main__":
    main()

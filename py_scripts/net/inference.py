import os
import sys
import glob
import argparse
import numpy as np
import cv2
import torch
from tqdm import tqdm
import segmentation_models_pytorch as smp
from pathlib import Path

# ==================== 路径 ====================
# 所有路径基于本文件位置推导，仓库被 clone 到任何目录都能直接运行
PROJECT_ROOT = Path(__file__).resolve().parents[2]      # .../AICleanBot
PY_DIR = PROJECT_ROOT / 'py_scripts'

# 将 train_student.py 所在目录加入路径，复用模型定义
sys.path.insert(0, os.path.dirname(__file__))
from train_student import (
    UNetMiniEXP1, UNetMiniExp2, UNetMiniExp3,
    UNetMiniExp4, UNetMiniExp5, UNetMiniExp6, UNetMiniExp7
)

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# 模型名称 -> (类/构建函数, 是否需要额外参数)
MODEL_REGISTRY = {
    # Student 模型（自定义轻量模型）
    'UNetMiniEXP1': (UNetMiniEXP1, None),
    'UNetMiniExp2': (UNetMiniExp2, None),
    'UNetMiniExp3': (UNetMiniExp3, None),
    'UNetMiniExp4': (UNetMiniExp4, None),
    'UNetMiniExp5': (UNetMiniExp5, None),
    'UNetMiniExp6': (UNetMiniExp6, None),
    'UNetMiniExp7': (UNetMiniExp7, None),
    # Teacher 模型（smp.Unet）- 注意：in_channels=3 对应 train_teacher.py 的设置
    'UNet_ResNet18': (lambda: smp.Unet(encoder_name='resnet18', encoder_weights=None, in_channels=3, classes=1), 'smp'),
    'UNet_ResNet34': (lambda: smp.Unet(encoder_name='resnet34', encoder_weights=None, in_channels=3, classes=1), 'smp'),
    'UNet_ResNet50': (lambda: smp.Unet(encoder_name='resnet50', encoder_weights=None, in_channels=3, classes=1), 'smp'),
    'UNet_EfficientNetB0': (lambda: smp.Unet(encoder_name='efficientnet-b0', encoder_weights=None, in_channels=3, classes=1), 'smp'),
}


def get_model_info_from_path(model_path):
    """从模型路径中自动推断模型类名（如 20260415_153256_UNetMiniExp5）"""
    model_dir_name = os.path.basename(os.path.dirname(model_path))
    for name, (cls_or_fn, model_type) in MODEL_REGISTRY.items():
        if name in model_dir_name:
            return name, cls_or_fn, model_type
    raise ValueError(
        f"无法从路径 '{model_dir_name}' 推断模型类型，"
        f"请确保目录名包含模型名称。\n"
        f"支持的模型: {list(MODEL_REGISTRY.keys())}"
    )


def load_model(model_path):
    model_name, cls_or_fn, model_type = get_model_info_from_path(model_path)
    print(f"模型类型: {model_name}")
    
    # 根据模型类型实例化
    if callable(cls_or_fn):
        model = cls_or_fn()
    else:
        model = cls_or_fn()
    
    model.load_state_dict(torch.load(model_path, map_location=DEVICE, weights_only=True))
    model.to(DEVICE)
    model.eval()
    return model, model_type


def preprocess(image_path, model_type):
    """
    预处理图像
    - Student 模型：灰度图，单通道
    - Teacher 模型：灰度图转 RGB，3 通道
    """
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    
    if model_type == 'smp':
        # Teacher 模型需要 3 通道输入
        img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        img_tensor = img_rgb.astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_tensor).permute(2, 0, 1).unsqueeze(0)  # HWC -> CHW -> BCHW
    else:
        # Student 模型单通道输入
        img_tensor = img.astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_tensor).unsqueeze(0).unsqueeze(0)  # HW -> CHW -> BCHW
    
    return img_tensor.to(DEVICE), img


def postprocess(output):
    pred = torch.sigmoid(output).squeeze().cpu().numpy()
    pred = (pred > 0.5).astype(np.uint8) * 255
    return pred


def save_visualization(img, pred, save_path):
    img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    mask = pred > 0
    alpha = 0.4
    result = img_bgr.copy()
    result[mask] = (img_bgr[mask].astype(float) * (1 - alpha) + np.array([128, 0, 128]) * alpha).astype(np.uint8)
    cv2.imwrite(save_path, result)


def build_visual_dir(model_path, input_dir):
    """
    根据模型路径自动构建可视化输出目录：
      可视化目录 = input_dir的上两级目录 + 'pred_' + 模型目录名
    例如：
      input_dir = .../dataset/val/images
      model_path = .../models/20260415_153256_UNetMiniExp5/best_model.pth
      → visual_dir = .../dataset/pred_20260415_153256_UNetMiniExp5
    """
    model_dir_name = os.path.basename(os.path.dirname(model_path))
    input_dir = input_dir.rstrip('/\\')
    # 获取上两级目录（从 .../val/images 到 .../dataset）
    parent_parent_dir = os.path.dirname(os.path.dirname(input_dir))
    return os.path.join(parent_parent_dir, f"pred_{model_dir_name}")


def infer(model_path, input_dir):
    # 自动构建可视化输出目录
    visual_dir = build_visual_dir(model_path, input_dir)
    os.makedirs(visual_dir, exist_ok=True)

    model, model_type = load_model(model_path)

    img_paths = sorted(
        glob.glob(os.path.join(input_dir, '*.[jp][pn]g')) +
        glob.glob(os.path.join(input_dir, '*.bmp'))
    )

    print(f"Device: {DEVICE}")
    print(f"Input dir: {input_dir}")
    print(f"Total images: {len(img_paths)}")
    print(f"Visual output: {visual_dir}")

    with torch.no_grad():
        for img_path in tqdm(img_paths, desc="Inference"):
            img_tensor, img_original = preprocess(img_path, model_type)
            output = model(img_tensor)

            pred = postprocess(output)

            name = os.path.basename(img_path)
            save_visualization(img_original, pred, os.path.join(visual_dir, name))

    print(f"\nDone! Visual saved to: {visual_dir}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='UNet 推理脚本（支持 Student 和 Teacher 模型）')
    parser.add_argument(
        '--model',
        default=str(PY_DIR / 'models' / '20260412_180030_UNetMiniExp5' / 'best_model.pth'),
        type=str,
        help='模型权重路径（.pth），目录名需包含模型类型，如 UNetMiniExp5 或 UNet_ResNet18'
    )
    parser.add_argument(
        '--input',
        default=str(PY_DIR / 'dataset' / 'val' / 'images'),
        type=str,
        help='输入图像目录'
    )
    args = parser.parse_args()

    infer(args.model, args.input)

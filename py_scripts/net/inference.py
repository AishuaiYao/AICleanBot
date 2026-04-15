import os
import sys
import glob
import argparse
import numpy as np
import cv2
import torch
from tqdm import tqdm

# 将 train_student.py 所在目录加入路径，复用模型定义
sys.path.insert(0, os.path.dirname(__file__))
from train_student import (
    UNetMiniEXP1, UNetMiniExp2, UNetMiniExp3,
    UNetMiniExp4, UNetMiniExp5, UNetMiniExp6, UNetMiniExp7
)

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# 模型名称 -> 类的映射
MODEL_REGISTRY = {
    'UNetMiniEXP1': UNetMiniEXP1,
    'UNetMiniExp2': UNetMiniExp2,
    'UNetMiniExp3': UNetMiniExp3,
    'UNetMiniExp4': UNetMiniExp4,
    'UNetMiniExp5': UNetMiniExp5,
    'UNetMiniExp6': UNetMiniExp6,
    'UNetMiniExp7': UNetMiniExp7,
}


def get_model_class_from_path(model_path):
    """从模型路径中自动推断模型类名（如 20260415_153256_UNetMiniExp5）"""
    model_dir_name = os.path.basename(os.path.dirname(model_path))
    for name, cls in MODEL_REGISTRY.items():
        if name in model_dir_name:
            return name, cls
    raise ValueError(
        f"无法从路径 '{model_dir_name}' 推断模型类型，"
        f"请确保目录名包含模型名称，如 UNetMiniExp5。\n"
        f"支持的模型: {list(MODEL_REGISTRY.keys())}"
    )


def load_model(model_path):
    model_name, model_cls = get_model_class_from_path(model_path)
    print(f"模型类型: {model_name}")
    model = model_cls()
    model.load_state_dict(torch.load(model_path, map_location=DEVICE))
    model.to(DEVICE)
    model.eval()
    return model


def preprocess(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    img_tensor = img.astype(np.float32) / 255.0
    img_tensor = torch.from_numpy(img_tensor).unsqueeze(0).unsqueeze(0)
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
      可视化目录 = input_dir + '_visual_' + 模型目录名
    例如：
      input_dir = .../FRAME_QQVGA
      model_path = .../models/20260415_153256_UNetMiniExp5/best_model.pth
      → visual_dir = .../FRAME_QQVGA_visual_20260415_153256_UNetMiniExp5
    """
    model_dir_name = os.path.basename(os.path.dirname(model_path))
    input_dir = input_dir.rstrip('/\\')
    return f"{input_dir}_visual_{model_dir_name}"


def infer(model_path, input_dir):
    # 自动构建可视化输出目录
    visual_dir = build_visual_dir(model_path, input_dir)
    os.makedirs(visual_dir, exist_ok=True)

    model = load_model(model_path)

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
            img_tensor, img_original = preprocess(img_path)
            output = model(img_tensor)

            pred = postprocess(output)

            name = os.path.basename(img_path)
            save_visualization(img_original, pred, os.path.join(visual_dir, name))

    print(f"\nDone! Visual saved to: {visual_dir}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='UNetMini 推理脚本')
    parser.add_argument(
        '--model',
        default=r'E:\AICleanBot\py_scripts\models\20260413_224444_UNetMiniExp5\best_model.pth',
        type=str,
        help='模型权重路径（.pth），目录名需包含模型类型，如 UNetMiniExp5'
    )
    parser.add_argument(
        '--input',
        default=r'C:\Users\aishuai\Downloads\AICleanBot-main\AICleanBot-main\py_scripts\dataset\FRAME_QQVGA',
        type=str,
        help='输入图像目录'
    )
    args = parser.parse_args()

    infer(args.model, args.input)
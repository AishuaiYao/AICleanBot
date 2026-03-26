from segmentation_models_pytorch.decoders.unet.model import Unet


import os
import glob
import argparse
import numpy as np
import cv2
import torch
import segmentation_models_pytorch as smp
from tqdm import tqdm


DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


def load_model(model_path):
    model = smp.Unet(
        encoder_name='resnet18',
        encoder_weights=None,
        in_channels=1,
        classes=1
    )
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
    alpha = 0.1
    result = img_bgr.copy()
    result[mask] = (img_bgr[mask].astype(float) * (1 - alpha) + np.array([128, 0, 128]) * alpha).astype(np.uint8)
    cv2.imwrite(save_path, result)


def infer(model_path, input_dir, output_dir, visual_dir):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(visual_dir, exist_ok=True)
    
    model: Unet = load_model(model_path)
    
    img_paths = glob.glob(os.path.join(input_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(input_dir, '*.bmp'))
    
    print(f"Device: {DEVICE}")
    print(f"Total images: {len(img_paths)}")
    
    with torch.no_grad():
        for img_path in tqdm(img_paths, desc="Inference"):
            img_tensor, img_original = preprocess(img_path)
            output = model(img_tensor)
            
            pred = postprocess(output)
            
            name = os.path.basename(img_path)
            cv2.imwrite(os.path.join(output_dir, name), pred)
            save_visualization(img_original, pred, os.path.join(visual_dir, name))
    
    print(f"Done! Mask saved to: {output_dir}")
    print(f"Visual saved to: {visual_dir}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default=r"D:\works\AICleanBot-main\py_scripts\model\20260316_170442\best_model.pth", type=str, help='Model path')
    parser.add_argument('--input', default=r"D:\works\AICleanBot-main\py_scripts\dataset\FRAME_QQVGA", type=str, help='Input image directory')
    parser.add_argument('--output', default=r"D:\works\AICleanBot-main\py_scripts\net\output", type=str, help='Output mask directory')
    parser.add_argument('--visual', default=r"D:\works\AICleanBot-main\py_scripts\net\visual", type=str, help='Visualization output directory')
    args = parser.parse_args()
    
    infer(args.model, args.input, args.output, args.visual)
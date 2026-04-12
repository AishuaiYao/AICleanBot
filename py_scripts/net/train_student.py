import os
import glob
import numpy as np
import cv2
import torch
from torch.utils.data import Dataset, DataLoader
import torch.nn as nn
import torch.optim as optim
from tqdm import tqdm
from datetime import datetime
import random
import matplotlib.pyplot as plt


# ==================== 自定义U-Net模型 ====================
class DoubleConv(nn.Module):
    """标准双卷积块"""
    def __init__(self, in_c, out_c):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_c, out_c, 3, 1, 1, bias=False),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_c, out_c, 3, 1, 1, bias=False),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True)
        )

    def forward(self, x):
        return self.conv(x)


class DepthwiseSeparableConv(nn.Module):
    """深度可分离卷积块: Depthwise + Pointwise"""
    def __init__(self, in_c, out_c):
        super().__init__()
        self.conv = nn.Sequential(
            # Depthwise: 每个通道独立卷积
            nn.Conv2d(in_c, in_c, 3, 1, 1, groups=in_c, bias=False),
            nn.BatchNorm2d(in_c),
            nn.ReLU(inplace=True),
            # Pointwise: 1x1卷积融合通道
            nn.Conv2d(in_c, out_c, 1, 1, 0, bias=False),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True),
            # 第二组 Depthwise + Pointwise
            nn.Conv2d(out_c, out_c, 3, 1, 1, groups=out_c, bias=False),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_c, out_c, 1, 1, 0, bias=False),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True)
        )

    def forward(self, x):
        return self.conv(x)


class UNetMiniEXP1(nn.Module):
    """轻量版U-Net (约500KB)"""
    def __init__(self):
        super().__init__()
        # Encoder (通道数: 8 -> 16 -> 32)
        self.enc1 = DoubleConv(1, 8)
        self.enc2 = DoubleConv(8, 16)
        self.enc3 = DoubleConv(16, 32)
        self.pool = nn.MaxPool2d(2)

        # Bottleneck
        self.bottleneck = DoubleConv(32, 64)

        # Decoder
        self.up3 = nn.ConvTranspose2d(64, 32, 2, 2)
        self.dec3 = DoubleConv(64, 32)
        self.up2 = nn.ConvTranspose2d(32, 16, 2, 2)
        self.dec2 = DoubleConv(32, 16)
        self.up1 = nn.ConvTranspose2d(16, 8, 2, 2)
        self.dec1 = DoubleConv(16, 8)

        # Output
        self.out = nn.Conv2d(8, 1, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))

        # Bottleneck
        b = self.bottleneck(self.pool(e3))

        # Decoder with skip connections
        d3 = self.up3(b)
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)

        d2 = self.up2(d3)
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)

        d1 = self.up1(d2)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)

        return self.out(d1)


class UNetMiniExp2(nn.Module):
    """增强版U-Net (约1MB) - 标准卷积"""
    def __init__(self):
        super().__init__()
        # Encoder (通道数: 12 -> 24 -> 48)
        self.enc1 = DoubleConv(1, 12)
        self.enc2 = DoubleConv(12, 24)
        self.enc3 = DoubleConv(24, 48)
        self.pool = nn.MaxPool2d(2)

        # Bottleneck
        self.bottleneck = DoubleConv(48, 96)

        # Decoder
        self.up3 = nn.ConvTranspose2d(96, 48, 2, 2)
        self.dec3 = DoubleConv(96, 48)
        self.up2 = nn.ConvTranspose2d(48, 24, 2, 2)
        self.dec2 = DoubleConv(48, 24)
        self.up1 = nn.ConvTranspose2d(24, 12, 2, 2)
        self.dec1 = DoubleConv(24, 12)

        # Output
        self.out = nn.Conv2d(12, 1, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))

        # Bottleneck
        b = self.bottleneck(self.pool(e3))

        # Decoder with skip connections
        d3 = self.up3(b)
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)

        d2 = self.up2(d3)
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)

        d1 = self.up1(d2)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)

        return self.out(d1)


class UNetMiniExp3(nn.Module):
    """深度可分离卷积 + 双线性插值上采样版U-Net"""
    def __init__(self):
        super().__init__()
        # Encoder (通道数: 12 -> 24 -> 48)
        self.enc1 = DepthwiseSeparableConv(1, 12)
        self.enc2 = DepthwiseSeparableConv(12, 24)
        self.enc3 = DepthwiseSeparableConv(24, 48)
        self.pool = nn.MaxPool2d(2)

        # Bottleneck
        self.bottleneck = DepthwiseSeparableConv(48, 96)

        # Decoder (使用双线性插值上采样 + 1x1卷积调整通道)
        self.up3 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        self.conv3 = nn.Conv2d(96, 48, 1, 1, 0, bias=False)
        self.dec3 = DepthwiseSeparableConv(96, 48)

        self.up2 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        self.conv2 = nn.Conv2d(48, 24, 1, 1, 0, bias=False)
        self.dec2 = DepthwiseSeparableConv(48, 24)

        self.up1 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        self.conv1 = nn.Conv2d(24, 12, 1, 1, 0, bias=False)
        self.dec1 = DepthwiseSeparableConv(24, 12)

        # Output
        self.out = nn.Conv2d(12, 1, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))

        # Bottleneck
        b = self.bottleneck(self.pool(e3))

        # Decoder with skip connections
        d3 = self.up3(b)
        d3 = self.conv3(d3)
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)

        d2 = self.up2(d3)
        d2 = self.conv2(d2)
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)

        d1 = self.up1(d2)
        d1 = self.conv1(d1)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)

        return self.out(d1)


class UNetMiniExp4(nn.Module):
    """深度可分离卷积 + 最近邻插值上采样版U-Net（ESP32-S3优化版）"""
    def __init__(self):
        super().__init__()
        # Encoder (通道数: 12 -> 24 -> 48)
        self.enc1 = DepthwiseSeparableConv(1, 12)
        self.enc2 = DepthwiseSeparableConv(12, 24)
        self.enc3 = DepthwiseSeparableConv(24, 48)
        self.pool = nn.MaxPool2d(2)

        # Bottleneck
        self.bottleneck = DepthwiseSeparableConv(48, 96)

        # Decoder (使用最近邻插值上采样 + 1x1卷积调整通道)
        self.up3 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv3 = nn.Conv2d(96, 48, 1, 1, 0, bias=False)
        self.dec3 = DepthwiseSeparableConv(96, 48)

        self.up2 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv2 = nn.Conv2d(48, 24, 1, 1, 0, bias=False)
        self.dec2 = DepthwiseSeparableConv(48, 24)

        self.up1 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv1 = nn.Conv2d(24, 12, 1, 1, 0, bias=False)
        self.dec1 = DepthwiseSeparableConv(24, 12)

        # Output
        self.out = nn.Conv2d(12, 1, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))

        # Bottleneck
        b = self.bottleneck(self.pool(e3))

        # Decoder with skip connections
        d3 = self.up3(b)
        d3 = self.conv3(d3)
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)

        d2 = self.up2(d3)
        d2 = self.conv2(d2)
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)

        d1 = self.up1(d2)
        d1 = self.conv1(d1)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)

        return self.out(d1)


class UNetMiniExp5(nn.Module):
    """深度可分离卷积 + 最近邻插值上采样版U-Net（ESP32-S3优化版 - 通道数对齐8倍数）
    
    通道数设计原则：所有卷积层的输入/输出通道数都是8的倍数
    这样可以启用esp-dl的优化汇编实现（要求通道数%8==0且内存16字节对齐）
    预计推理速度提升30-50%
    """
    def __init__(self):
        super().__init__()
        # Encoder (通道数: 16 -> 32 -> 64，都是8的倍数)
        self.enc1 = DepthwiseSeparableConv(1, 16)
        self.enc2 = DepthwiseSeparableConv(16, 32)
        self.enc3 = DepthwiseSeparableConv(32, 64)
        self.pool = nn.MaxPool2d(2)

        # Bottleneck (128 = 8的倍数)
        self.bottleneck = DepthwiseSeparableConv(64, 128)

        # Decoder (使用最近邻插值上采样 + 1x1卷积调整通道)
        self.up3 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv3 = nn.Conv2d(128, 64, 1, 1, 0, bias=False)
        self.dec3 = DepthwiseSeparableConv(128, 64)

        self.up2 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv2 = nn.Conv2d(64, 32, 1, 1, 0, bias=False)
        self.dec2 = DepthwiseSeparableConv(64, 32)

        self.up1 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv1 = nn.Conv2d(32, 16, 1, 1, 0, bias=False)
        self.dec1 = DepthwiseSeparableConv(32, 16)

        # Output
        self.out = nn.Conv2d(16, 1, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))

        # Bottleneck
        b = self.bottleneck(self.pool(e3))

        # Decoder with skip connections
        d3 = self.up3(b)
        d3 = self.conv3(d3)
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)

        d2 = self.up2(d3)
        d2 = self.conv2(d2)
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)

        d1 = self.up1(d2)
        d1 = self.conv1(d1)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)

        return self.out(d1)


class UNetMiniExp6(nn.Module):
    """混合卷积版U-Net（高分辨率层用普通卷积，低分辨率层用深度可分离卷积）
    
    优化策略：
    1. 通道数对齐8的倍数（启用esp-dl优化）
    2. 高分辨率层（enc1, dec1）使用DoubleConv，避免Pointwise卷积瓶颈
    3. 低分辨率层保持DepthwiseSeparableConv，减少参数量
    
    预计推理速度比Exp5更快（高分辨率层无Pointwise瓶颈）
    """
    def __init__(self):
        super().__init__()
        # Encoder - enc1用DoubleConv，enc2/enc3用DepthwiseSeparableConv
        self.enc1 = DoubleConv(1, 16)                    # 高分辨率：普通卷积
        self.enc2 = DepthwiseSeparableConv(16, 32)       # 中分辨率：深度可分离
        self.enc3 = DepthwiseSeparableConv(32, 64)       # 低分辨率：深度可分离
        self.pool = nn.MaxPool2d(2)

        # Bottleneck
        self.bottleneck = DepthwiseSeparableConv(64, 128)

        # Decoder - dec1用DoubleConv，dec2/dec3用DepthwiseSeparableConv
        self.up3 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv3 = nn.Conv2d(128, 64, 1, 1, 0, bias=False)
        self.dec3 = DepthwiseSeparableConv(128, 64)      # 低分辨率

        self.up2 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv2 = nn.Conv2d(64, 32, 1, 1, 0, bias=False)
        self.dec2 = DepthwiseSeparableConv(64, 32)       # 中分辨率

        self.up1 = nn.Upsample(scale_factor=2, mode='nearest')
        self.conv1 = nn.Conv2d(32, 16, 1, 1, 0, bias=False)
        self.dec1 = DoubleConv(32, 16)                   # 高分辨率：普通卷积

        # Output
        self.out = nn.Conv2d(16, 1, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))

        # Bottleneck
        b = self.bottleneck(self.pool(e3))

        # Decoder with skip connections
        d3 = self.up3(b)
        d3 = self.conv3(d3)
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)

        d2 = self.up2(d3)
        d2 = self.conv2(d2)
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)

        d1 = self.up1(d2)
        d1 = self.conv1(d1)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)

        return self.out(d1)


class UNetMiniExp7(nn.Module):
    """标准卷积版U-Net（通道数对齐8的倍数 + 无Pointwise瓶颈）
    
    优化策略：
    1. 全部使用DoubleConv（标准3x3卷积），无1x1 Pointwise瓶颈
    2. 通道数对齐8的倍数，启用esp-dl优化汇编
    3. 使用ConvTranspose2d上采样，避免额外1x1卷积
    
    预计推理速度最快（esp-dl对3x3卷积优化最好）
    """
    def __init__(self):
        super().__init__()
        # Encoder (通道数: 16 -> 32 -> 64，都是8的倍数)
        self.enc1 = DoubleConv(1, 16)
        self.enc2 = DoubleConv(16, 32)
        self.enc3 = DoubleConv(32, 64)
        self.pool = nn.MaxPool2d(2)

        # Bottleneck (128 = 8的倍数)
        self.bottleneck = DoubleConv(64, 128)

        # Decoder (使用ConvTranspose2d上采样)
        self.up3 = nn.ConvTranspose2d(128, 64, 2, 2)
        self.dec3 = DoubleConv(128, 64)

        self.up2 = nn.ConvTranspose2d(64, 32, 2, 2)
        self.dec2 = DoubleConv(64, 32)

        self.up1 = nn.ConvTranspose2d(32, 16, 2, 2)
        self.dec1 = DoubleConv(32, 16)

        # Output
        self.out = nn.Conv2d(16, 1, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))

        # Bottleneck
        b = self.bottleneck(self.pool(e3))

        # Decoder with skip connections
        d3 = self.up3(b)
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)

        d2 = self.up2(d3)
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)

        d1 = self.up1(d2)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)

        return self.out(d1)


# ==================== Focal Loss ====================
class FocalLoss(nn.Module):
    def __init__(self, alpha=0.75, gamma=2.0):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
    
    def forward(self, pred, target):
        bce = nn.functional.binary_cross_entropy_with_logits(pred, target, reduction='none')
        pred_prob = torch.sigmoid(pred)
        pt = target * pred_prob + (1 - target) * (1 - pred_prob)
        alpha_t = target * self.alpha + (1 - target) * (1 - self.alpha)
        focal = alpha_t * (1 - pt) ** self.gamma * bce
        return focal.mean()


# ==================== 组合损失函数 ====================
class CombinedLoss(nn.Module):
    def __init__(self, alpha=0.75, gamma=2.0):
        super().__init__()
        self.focal = FocalLoss(alpha=alpha, gamma=gamma)
        self.bce = nn.BCEWithLogitsLoss()
    
    def forward(self, pred, target):
        return self.focal(pred, target) + self.bce(pred, target)


# ==================== 配置 ====================
DATA_DIR = r'E:\AICleanBot\py_scripts\dataset'
IMAGE_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA')
LABEL_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA_label')
PRED_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA_pred')
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')

BATCH_SIZE = 8
LEARNING_RATE = 1e-4
EPOCHS = 0
PATIENCE = 10
MAX_EPOCHS = 1000
TRAIN_RATIO = 0.8

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# ==================== 数据增强配置 ====================
AUGMENTATION_CONFIG = {
    'h_flip': True,
    'v_flip': True,
    'rotate': True,
    'brightness': True,
    'contrast': True,
    'noise': True,
    'blur': True,
    'color_jitter': False,
}


# ==================== 数据增强函数 ====================
def apply_augmentations(img, label, config):
    h, w = img.shape[:2]
    applied_augs = []
    
    # 水平翻转
    if config.get('h_flip') and random.random() > 0.5:
        img = cv2.flip(img, 1)
        label = cv2.flip(label, 1)
        applied_augs.append('h_flip')
    
    # 垂直翻转
    if config.get('v_flip') and random.random() > 0.5:
        img = cv2.flip(img, 0)
        label = cv2.flip(label, 0)
        applied_augs.append('v_flip')
    
    # 随机旋转
    if config.get('rotate') and random.random() > 0.5:
        angle = random.uniform(-30, 30)
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        label = cv2.warpAffine(label, M, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        applied_augs.append(f'rot:{angle:.1f}')
    
    # 随机亮度
    if config.get('brightness') and random.random() > 0.5:
        factor = random.uniform(0.8, 1.2)
        img = np.clip(img * factor, 0, 255).astype(np.uint8)
        applied_augs.append(f'bri:{factor:.2f}')
    
    # 随机对比度
    if config.get('contrast') and random.random() > 0.5:
        factor = random.uniform(0.8, 1.2)
        mean = np.mean(img)
        img = np.clip((img - mean) * factor + mean, 0, 255).astype(np.uint8)
        applied_augs.append(f'con:{factor:.2f}')
    
    # 高斯模糊
    if config.get('blur') and random.random() > 0.5:
        ksize = random.choice([3, 5])
        img = cv2.GaussianBlur(img, (ksize, ksize), 0)
        applied_augs.append(f'blur:{ksize}')
    
    # 高斯噪声
    if config.get('noise') and random.random() > 0.5:
        mean = 0
        sigma = random.uniform(5, 15)
        gauss = np.random.normal(mean, sigma, img.shape).astype(np.float32)
        img = np.clip(img.astype(np.float32) + gauss, 0, 255).astype(np.uint8)
        applied_augs.append('noise')
    
    return img, label, applied_augs


# ==================== 数据集 ====================
class SegDataset(Dataset):
    def __init__(self, image_dir, label_dir, img_names, augment=False):
        self.augment = augment
        self.img_paths = [os.path.join(image_dir, n) for n in img_names]
        self.label_paths = [os.path.join(label_dir, n) for n in img_names]
        self.names = img_names
    
    def __len__(self):
        return len(self.names)
    
    def __getitem__(self, idx):
        img = cv2.imread(self.img_paths[idx], cv2.IMREAD_GRAYSCALE)
        label = cv2.imread(self.label_paths[idx], cv2.IMREAD_GRAYSCALE)
        
        if self.augment:
            img, label, _ = apply_augmentations(img, label, AUGMENTATION_CONFIG)
        
        img = img.astype(np.float32) / 255.0
        label = (label > 0).astype(np.float32)
        
        img = torch.from_numpy(img).unsqueeze(0)
        label = torch.from_numpy(label).unsqueeze(0)
        
        return img, label, self.names[idx]


# ==================== 指标计算 ====================
def calc_iou(pred, target, threshold=0.5):
    pred = (pred > threshold).float()
    intersection = (pred * target).sum()
    union = pred.sum() + target.sum() - intersection
    if union == 0:
        return 1.0
    return (intersection / union).item()


def calc_pixel_acc(pred, target, threshold=0.5):
    pred = (pred > threshold).float()
    correct = (pred == target).float().sum()
    total = target.numel()
    return (correct / total).item()


# ==================== 可视化保存 ====================
def save_visualization(img_tensor, pred_tensor, save_path):
    img = (img_tensor.squeeze().cpu().numpy() * 255).astype(np.uint8)
    pred = (pred_tensor.squeeze().cpu().numpy() > 0.5).astype(np.uint8) * 255
    
    img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    mask = pred > 0
    alpha = 0.1
    result = img_bgr.copy()
    result[mask] = (img_bgr[mask].astype(float) * (1 - alpha) + np.array([128, 0, 128]) * alpha).astype(np.uint8)
    
    cv2.imwrite(save_path, result)


# ==================== 实时绘图类 ====================
class TrainingPlotter:
    def __init__(self, save_dir):
        self.save_dir = save_dir
        self.epochs = []
        self.train_loss, self.val_loss = [], []
        self.train_iou, self.val_iou = [], []
        self.train_acc, self.val_acc = [], []
        
        plt.ion()
        self.fig, self.axes = plt.subplots(3, 1, figsize=(8, 12))
        self.fig.suptitle('Training Progress', fontsize=12)
        
    def update(self, epoch, train_loss, val_loss, train_iou, val_iou, train_acc, val_acc):
        self.epochs.append(epoch + 1)
        self.train_loss.append(train_loss)
        self.val_loss.append(val_loss)
        self.train_iou.append(train_iou)
        self.val_iou.append(val_iou)
        self.train_acc.append(train_acc)
        self.val_acc.append(val_acc)
        
        # 清空并重绘
        for ax in self.axes:
            ax.clear()
        
        # Loss曲线
        self.axes[0].plot(self.epochs, self.train_loss, 'b-', label='Train', linewidth=2)
        self.axes[0].plot(self.epochs, self.val_loss, 'r-', label='Val', linewidth=2)
        self.axes[0].set_xlabel('Epoch')
        self.axes[0].set_ylabel('Loss')
        self.axes[0].set_title('Loss Curve')
        self.axes[0].legend()
        self.axes[0].grid(True, alpha=0.3)
        
        # IoU曲线
        self.axes[1].plot(self.epochs, self.train_iou, 'b-', label='Train', linewidth=2)
        self.axes[1].plot(self.epochs, self.val_iou, 'r-', label='Val', linewidth=2)
        self.axes[1].set_xlabel('Epoch')
        self.axes[1].set_ylabel('IoU')
        self.axes[1].set_title('IoU Curve')
        self.axes[1].legend()
        self.axes[1].grid(True, alpha=0.3)
        
        # Acc曲线
        self.axes[2].plot(self.epochs, self.train_acc, 'b-', label='Train', linewidth=2)
        self.axes[2].plot(self.epochs, self.val_acc, 'r-', label='Val', linewidth=2)
        self.axes[2].set_xlabel('Epoch')
        self.axes[2].set_ylabel('Accuracy')
        self.axes[2].set_title('Accuracy Curve')
        self.axes[2].legend()
        self.axes[2].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.draw()
        plt.pause(0.1)
    
    def save(self):
        plt.ioff()
        fig_dir = os.path.join(os.path.dirname(self.save_dir), '..', 'figure', os.path.basename(self.save_dir))
        os.makedirs(fig_dir, exist_ok=True)
        
        # 保存三合一竖排图像
        fig, axes = plt.subplots(3, 1, figsize=(8, 12))
        
        # Loss曲线
        axes[0].plot(self.epochs, self.train_loss, 'b-', label='Train', linewidth=2)
        axes[0].plot(self.epochs, self.val_loss, 'r-', label='Val', linewidth=2)
        axes[0].set_ylabel('Loss', fontsize=11)
        axes[0].set_title('Loss Curve', fontsize=12)
        axes[0].legend(fontsize=10)
        axes[0].grid(True, alpha=0.3)
        
        # IoU曲线
        axes[1].plot(self.epochs, self.train_iou, 'b-', label='Train', linewidth=2)
        axes[1].plot(self.epochs, self.val_iou, 'r-', label='Val', linewidth=2)
        axes[1].set_ylabel('IoU', fontsize=11)
        axes[1].set_title('IoU Curve', fontsize=12)
        axes[1].legend(fontsize=10)
        axes[1].grid(True, alpha=0.3)
        
        # Acc曲线
        axes[2].plot(self.epochs, self.train_acc, 'b-', label='Train', linewidth=2)
        axes[2].plot(self.epochs, self.val_acc, 'r-', label='Val', linewidth=2)
        axes[2].set_xlabel('Epoch', fontsize=11)
        axes[2].set_ylabel('Accuracy', fontsize=11)
        axes[2].set_title('Accuracy Curve', fontsize=12)
        axes[2].legend(fontsize=10)
        axes[2].grid(True, alpha=0.3)
        
        plt.tight_layout()
        fig.savefig(os.path.join(fig_dir, 'training_curves.png'), dpi=150, bbox_inches='tight')
        plt.close(fig)
        plt.close(self.fig)
        return fig_dir

# ==================== 训练 ====================
def train():
    # 固定随机种子
    SEED = 42
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    
    os.makedirs(PRED_DIR, exist_ok=True)
    
    # 模型名称
    model_name = 'UNetMiniExp5'
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_dir = os.path.join(MODEL_DIR, f'{timestamp}_{model_name}')
    os.makedirs(save_dir, exist_ok=True)
    model_path = os.path.join(save_dir, 'best_model.pth')
    
    # 获取文件名
    img_files = set(glob.glob(os.path.join(IMAGE_DIR, '*.[jp][pn]g')) + glob.glob(os.path.join(IMAGE_DIR, '*.bmp')))
    label_files = set(glob.glob(os.path.join(LABEL_DIR, '*.[jp][pn]g')) + glob.glob(os.path.join(LABEL_DIR, '*.bmp')))
    
    img_names = {os.path.basename(p) for p in img_files}
    label_names = {os.path.basename(p) for p in label_files}
    common_names = sorted(list(img_names & label_names))
    
    random.shuffle(common_names)
    
    # 划分数据集
    train_size = int(len(common_names) * TRAIN_RATIO)
    train_names = common_names[:train_size]
    val_names = common_names[train_size:]
    
    train_dataset = SegDataset(IMAGE_DIR, LABEL_DIR, train_names, augment=True)
    val_dataset = SegDataset(IMAGE_DIR, LABEL_DIR, val_names, augment=False)
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=1, shuffle=False, num_workers=0)
    
    # 使用自定义模型
    model = UNetMiniExp5().to(DEVICE)
    
    criterion = CombinedLoss()
    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
    
    best_val_loss = float('inf')
    no_improve_count = 0
    plotter = TrainingPlotter(save_dir)
    
    print(f"Device: {DEVICE}")
    print(f"Total samples: {len(common_names)}")
    print(f"Train samples: {len(train_names)} (Augmentation: ON)")
    print(f"Val samples:   {len(val_names)}   (Augmentation: OFF)")
    
    if EPOCHS == 0:
        print(f"训练模式: 早停模式 (patience={PATIENCE}, max_epochs={MAX_EPOCHS})")
    else:
        print(f"训练模式: 固定轮数 (epochs={EPOCHS})")
    print("=" * 60)
    
    total_epochs = EPOCHS if EPOCHS > 0 else MAX_EPOCHS
    
    for epoch in range(total_epochs):
        # ========== Train ==========
        model.train()
        train_loss = 0.0
        train_iou = 0.0
        train_acc = 0.0
        
        for imgs, labels, _ in tqdm(train_loader, desc=f"Epoch {epoch+1}/{total_epochs} [Train]"):
            imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
            
            optimizer.zero_grad()
            outputs = model(imgs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item()
            train_iou += calc_iou(torch.sigmoid(outputs), labels)
            train_acc += calc_pixel_acc(torch.sigmoid(outputs), labels)
        
        train_loss /= len(train_loader)
        train_iou /= len(train_loader)
        train_acc /= len(train_loader)
        
        # ========== Validate ==========
        model.eval()
        val_loss = 0.0
        val_iou = 0.0
        val_acc = 0.0
        
        with torch.no_grad():
            for imgs, labels, names in tqdm(val_loader, desc=f"Epoch {epoch+1}/{total_epochs} [Val]"):
                imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
                
                outputs = model(imgs)
                loss = criterion(outputs, labels)
                
                val_loss += loss.item()
                val_iou += calc_iou(torch.sigmoid(outputs), labels)
                val_acc += calc_pixel_acc(torch.sigmoid(outputs), labels)
                
                save_visualization(imgs[0], torch.sigmoid(outputs[0]), os.path.join(PRED_DIR, names[0]))
        
        val_loss /= len(val_loader)
        val_iou /= len(val_loader)
        val_acc /= len(val_loader)
        
        # ========== Print ==========
        print(f"Epoch {epoch+1}/{total_epochs}")
        print(f"  Train - Loss: {train_loss:.4f}, IoU: {train_iou:.4f}, Acc: {train_acc:.4f}")
        print(f"  Val   - Loss: {val_loss:.4f}, IoU: {val_iou:.4f}, Acc: {val_acc:.4f}")
        
        # ========== Update Plot ==========
        plotter.update(epoch, train_loss, val_loss, train_iou, val_iou, train_acc, val_acc)
        
        # ========== Save Best Model & Early Stopping ==========
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            no_improve_count = 0
            torch.save(model.state_dict(), model_path)
            print(f"  >>> Best model saved: {model_path}")
        else:
            no_improve_count += 1
            if EPOCHS == 0 and no_improve_count >= PATIENCE:
                print(f"  >>> Early stopping triggered! No improvement for {PATIENCE} epochs")
                break
        
        print("-" * 60)
    
    fig_dir = plotter.save()
    print(f"Training completed! Best val loss: {best_val_loss:.4f}")
    print(f"模型已保存：{model_path}")
    print(f"训练曲线已保存：{fig_dir}")
    print(f"如需导出ONNX，请使用：tools.export_pth_to_onnx({model_name}, model_path, save_dir)")


if __name__ == '__main__':
    train()

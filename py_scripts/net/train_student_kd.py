import os
import glob
import numpy as np
import cv2
import torch
from torch.utils.data import Dataset, DataLoader
import torch.nn as nn
import torch.optim as optim
import segmentation_models_pytorch as smp
import torchvision.models as tv_models
from tqdm import tqdm
from datetime import datetime
import random
import matplotlib.pyplot as plt
import time
import sys

# 导入student模型定义
from train_student import (
    UNetMiniExp5, DepthwiseSeparableConv, DoubleConv,
    FocalLoss, DiceLoss, CombinedLoss,
    SegDataset, calc_iou, calc_pixel_acc,
    Tee, TrainingPlotter,
    apply_augmentations, AUGMENTATION_CONFIG
)


# ==================== 可视化保存 ====================
def save_visualization(img_tensor, pred_tensor, save_path):
    """兼容单通道/3通道输入的可视化函数"""
    img_np = img_tensor.cpu().numpy()
    if img_np.ndim == 3:
        gray = img_np[0]  # (H, W), float32, [0, 1]
    else:
        gray = img_np
    img = np.ascontiguousarray((gray * 255).clip(0, 255).astype(np.uint8))
    pred = (pred_tensor.squeeze().cpu().numpy() > 0.5).astype(np.uint8) * 255
    
    img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    mask = pred > 0
    alpha = 0.1
    result = img_bgr.copy()
    result[mask] = (img_bgr[mask].astype(float) * (1 - alpha) + np.array([128, 0, 128]) * alpha).astype(np.uint8)
    
    cv2.imwrite(save_path, result)


# ==================== 知识蒸馏损失 ====================
class KDLoss(nn.Module):
    """知识蒸馏损失（KL散度）
    
    对软化后的logits计算KL散度，让student学习teacher的"暗知识"
    """
    def __init__(self, temperature=4.0):
        super().__init__()
        self.T = temperature
    
    def forward(self, student_logits, teacher_logits):
        # 软化概率分布
        student_soft = torch.sigmoid(student_logits / self.T)
        teacher_soft = torch.sigmoid(teacher_logits / self.T).detach()
        
        # KL散度：teacher_soft * log(teacher_soft / student_soft)
        # 简化为MSE更稳定
        return nn.functional.mse_loss(student_soft, teacher_soft)


class DistillationLoss(nn.Module):
    """组合蒸馏损失
    
    L = α * hard_loss + (1-α) * kd_loss
    - hard_loss: 对真实标签的损失（Focal + Dice）
    - kd_loss: 对teacher输出的蒸馏损失
    """
    def __init__(self, alpha=0.6, temperature=4.0):
        super().__init__()
        self.alpha = alpha
        self.hard_loss = CombinedLoss()
        self.kd_loss = KDLoss(temperature=temperature)
    
    def forward(self, student_logits, teacher_logits, targets):
        L_hard = self.hard_loss(student_logits, targets)
        L_kd = self.kd_loss(student_logits, teacher_logits)
        return self.alpha * L_hard + (1 - self.alpha) * L_kd


# ==================== 配置 ====================
DATA_DIR = r'E:\AICleanBot\py_scripts\dataset'
TRAIN_DIR = os.path.join(DATA_DIR, 'train')
VAL_DIR = os.path.join(DATA_DIR, 'val')
PRED_DIR = os.path.join(DATA_DIR, 'pred')
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')

# Teacher配置
TEACHER_MODEL_PATH = r'e:\AICleanBot\py_scripts\models\20260416_213640_UNet_ResNet18\best_model.pth'

# 训练配置
BATCH_SIZE = 8
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-5
EPOCHS = 0  # 0表示早停模式
PATIENCE = 20
MAX_EPOCHS = 1000

# 蒸馏配置
KD_ALPHA = 0.6        # hard_loss权重
KD_TEMPERATURE = 4.0  # 蒸馏温度

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


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
    model_name = 'UNetMiniExp5_KD'
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_dir = os.path.join(MODEL_DIR, f'{timestamp}_{model_name}')
    os.makedirs(save_dir, exist_ok=True)
    model_path = os.path.join(save_dir, 'best_model.pth')
    
    # 创建日志文件
    log_dir = r'E:\AICleanBot\logs\train'
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f'{timestamp}_{model_name}.txt')
    tee = Tee(log_path)
    sys.stdout = tee
    
    start_time = time.time()
    
    # 创建数据集
    train_dataset = SegDataset(TRAIN_DIR, augment=True)
    val_dataset = SegDataset(VAL_DIR, augment=False)
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=1, shuffle=False, num_workers=0)
    
    # ========== 加载Teacher模型 ==========
    print("加载Teacher模型...")
    teacher_model = smp.Unet(
        encoder_name='resnet18',
        encoder_weights=None,
        in_channels=3,
        classes=1
    ).to(DEVICE)
    
    teacher_state = torch.load(TEACHER_MODEL_PATH, map_location=DEVICE)
    teacher_model.load_state_dict(teacher_state)
    teacher_model.eval()  # 冻结
    for param in teacher_model.parameters():
        param.requires_grad = False
    print(f"Teacher模型已加载: {TEACHER_MODEL_PATH}")
    
    # ========== 创建Student模型 ==========
    student_model = UNetMiniExp5().to(DEVICE)
    
    # 蒸馏损失
    criterion = DistillationLoss(alpha=KD_ALPHA, temperature=KD_TEMPERATURE)
    
    optimizer = optim.Adam(student_model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.CosineAnnealingWarmRestarts(
        optimizer, T_0=10, T_mult=2, eta_min=1e-6
    )
    
    best_val_iou = 0.0
    no_improve_count = 0
    plotter = TrainingPlotter(save_dir)
    
    print(f"Device: {DEVICE}")
    print(f"Train samples: {len(train_dataset)} (Augmentation: ON)")
    print(f"Val samples:   {len(val_dataset)}   (Augmentation: OFF)")
    print(f"KD Alpha: {KD_ALPHA}, Temperature: {KD_TEMPERATURE}")
    
    if EPOCHS == 0:
        print(f"训练模式: 早停模式 (patience={PATIENCE}, max_epochs={MAX_EPOCHS})")
    else:
        print(f"训练模式: 固定轮数 (epochs={EPOCHS})")
    print("=" * 60)
    
    total_epochs = EPOCHS if EPOCHS > 0 else MAX_EPOCHS
    
    for epoch in range(total_epochs):
        # ========== Train ==========
        student_model.train()
        train_loss = 0.0
        train_iou = 0.0
        train_acc = 0.0
        
        for imgs, labels, _ in tqdm(train_loader, desc=f"Epoch {epoch+1}/{total_epochs} [Train]"):
            imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
            
            # Student前向（单通道）
            student_outputs = student_model(imgs)
            
            # Teacher前向（需要3通道输入）
            with torch.no_grad():
                teacher_inputs = imgs.repeat(1, 3, 1, 1)  # 单通道复制为3通道
                teacher_outputs = teacher_model(teacher_inputs)
            
            # 计算蒸馏损失
            loss = criterion(student_outputs, teacher_outputs, labels)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item()
            train_iou += calc_iou(torch.sigmoid(student_outputs), labels)
            train_acc += calc_pixel_acc(torch.sigmoid(student_outputs), labels)
        
        train_loss /= len(train_loader)
        train_iou /= len(train_loader)
        train_acc /= len(train_loader)
        
        # ========== Validate ==========
        student_model.eval()
        val_loss = 0.0
        val_iou = 0.0
        val_acc = 0.0
        val_cache = []
        
        with torch.no_grad():
            for imgs, labels, names in tqdm(val_loader, desc=f"Epoch {epoch+1}/{total_epochs} [Val]"):
                imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
                
                # Student前向（单通道）
                student_outputs = student_model(imgs)
                
                # Teacher前向（需要3通道输入）
                teacher_inputs = imgs.repeat(1, 3, 1, 1)
                teacher_outputs = teacher_model(teacher_inputs)
                
                loss = criterion(student_outputs, teacher_outputs, labels)
                
                val_loss += loss.item()
                val_iou += calc_iou(torch.sigmoid(student_outputs), labels)
                val_acc += calc_pixel_acc(torch.sigmoid(student_outputs), labels)
                
                val_cache.append((imgs[0].cpu(), torch.sigmoid(student_outputs[0]).cpu(), names[0]))
        
        val_loss /= len(val_loader)
        val_iou /= len(val_loader)
        val_acc /= len(val_loader)
        
        # ========== Print ==========
        print(f"Epoch {epoch+1}/{total_epochs}")
        print(f"  Train - Loss: {train_loss:.4f}, IoU: {train_iou:.4f}, Acc: {train_acc:.4f}")
        print(f"  Val   - Loss: {val_loss:.4f}, IoU: {val_iou:.4f}, Acc: {val_acc:.4f}")
        
        scheduler.step()
        current_lr = optimizer.param_groups[0]['lr']
        print(f"  Learning Rate: {current_lr:.6f}")
        
        plotter.update(epoch, train_loss, val_loss, train_iou, val_iou, train_acc, val_acc)
        
        # ========== Save Best Model ==========
        if val_iou > best_val_iou:
            best_val_iou = val_iou
            no_improve_count = 0
            torch.save(student_model.state_dict(), model_path)
            for img, pred, name in val_cache:
                save_visualization(img, pred, os.path.join(PRED_DIR, name))
            print(f"  >>> Best model saved: {model_path}")
            print(f"  >>> Val visualization saved to: {PRED_DIR}")
        else:
            no_improve_count += 1
            if EPOCHS == 0 and no_improve_count >= PATIENCE:
                print(f"  >>> Early stopping triggered! No improvement for {PATIENCE} epochs")
                break
        
        print("-" * 60)
    
    fig_dir = plotter.save()
    total_time = time.time() - start_time
    hours, remainder = divmod(total_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    print(f"Training completed! Best val IoU: {best_val_iou:.4f}")
    print(f"模型已保存：{model_path}")
    print(f"训练曲线已保存：{fig_dir}")
    print(f"训练总耗时：{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
    print(f"Teacher模型: {TEACHER_MODEL_PATH}")
    
    sys.stdout = tee.terminal
    tee.close()


if __name__ == '__main__':
    train()

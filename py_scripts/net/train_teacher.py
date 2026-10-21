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
from pathlib import Path

# ==================== 路径 ====================
# 所有路径基于本文件位置推导，仓库被 clone 到任何目录都能直接运行
PROJECT_ROOT = Path(__file__).resolve().parents[2]      # .../AICleanBot
PY_DIR = PROJECT_ROOT / 'py_scripts'
LOG_ROOT = PROJECT_ROOT / 'logs'


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


# ==================== Dice Loss ====================
class DiceLoss(nn.Module):
    def __init__(self, smooth=1.0):
        super().__init__()
        self.smooth = smooth
    
    def forward(self, pred, target):
        pred = torch.sigmoid(pred)
        # 在 H×W 维度上计算，保留 batch 维度
        intersection = (pred * target).sum(dim=(2, 3))
        dice = (2 * intersection + self.smooth) / (
            pred.sum(dim=(2, 3)) + target.sum(dim=(2, 3)) + self.smooth
        )
        return 1 - dice.mean()


# ==================== 组合损失函数（Focal + Dice）====================
class CombinedLoss(nn.Module):
    """前景占比 ~8%（中等不平衡）场景：
    - Focal Loss: alpha=0.75 给前景3倍权重，gamma=2.0 聚焦难分类边缘像素
    - Dice Loss: 直接优化区域重叠，与 IoU 高度相关
    - 各占 0.5 权重，两者互补
    """
    def __init__(self, alpha=0.75, gamma=2.0):
        super().__init__()
        self.focal = FocalLoss(alpha=alpha, gamma=gamma)
        self.dice = DiceLoss()
    
    def forward(self, pred, target):
        return 0.5 * self.focal(pred, target) + 0.5 * self.dice(pred, target)


# ==================== 配置 ====================
DATA_DIR = str(PY_DIR / 'dataset')
TRAIN_DIR = os.path.join(DATA_DIR, 'train')
VAL_DIR = os.path.join(DATA_DIR, 'val')
PRED_DIR = os.path.join(DATA_DIR, 'pred')
MODEL_DIR = str(PY_DIR / 'models')

BATCH_SIZE = 8
LEARNING_RATE = 1e-3  # 提高初始学习率
WEIGHT_DECAY = 1e-5   # L2正则化
EPOCHS = 0
PATIENCE = 20
MAX_EPOCHS = 1000

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
    def __init__(self, data_dir, augment=False):
        """
        从已划分好的目录加载数据
        
        参数:
            data_dir: 包含 images 和 labels 子目录的根目录
            augment: 是否进行数据增强
        """
        self.augment = augment
        image_dir = os.path.join(data_dir, 'images')
        label_dir = os.path.join(data_dir, 'labels')
        
        # 获取所有图片文件名
        img_files = glob.glob(os.path.join(image_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(image_dir, '*.bmp'))
        self.img_paths = sorted(img_files)
        self.label_paths = [os.path.join(label_dir, os.path.basename(p)) for p in self.img_paths]
        self.names = [os.path.basename(p) for p in self.img_paths]
    
    def __len__(self):
        return len(self.names)
    
    def __getitem__(self, idx):
        img = cv2.imread(self.img_paths[idx], cv2.IMREAD_GRAYSCALE)
        label = cv2.imread(self.label_paths[idx], cv2.IMREAD_GRAYSCALE)
        
        if self.augment:
            img, label, _ = apply_augmentations(img, label, AUGMENTATION_CONFIG)
        
        img = img.astype(np.float32) / 255.0
        label = (label > 0).astype(np.float32)
        
        # 灰度图复制为3通道，以匹配ImageNet预训练编码器的输入要求
        img = np.stack([img, img, img], axis=0)  # (3, H, W)
        img = torch.from_numpy(img)
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


# ==================== 日志输出重定向 ====================
class Tee:
    def __init__(self, log_path):
        self.terminal = sys.stdout
        self.log = open(log_path, 'w', encoding='utf-8')
    
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()
    
    def close(self):
        self.log.close()


# ==================== 可视化保存 ====================
# ==================== 可视化保存 ====================
def save_visualization(img_tensor, pred_tensor, save_path):
    # img_tensor 形状为 (3, H, W)，取第0通道作为灰度图显示（三通道值相同）
    img_np = img_tensor.cpu().numpy()  # (3, H, W) 或 (H, W)
    if img_np.ndim == 3:
        gray = img_np[0]  # (H, W), float32, [0, 1]
    else:
        gray = img_np      # (H, W), float32, [0, 1]
    img = np.ascontiguousarray((gray * 255).clip(0, 255).astype(np.uint8))  # 确保内存连续
    pred = (pred_tensor.squeeze().cpu().numpy() > 0.5).astype(np.uint8) * 255
    
    img_bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    mask = pred > 0
    alpha = 0.1
    result = img_bgr.copy()
    result[mask] = (img_bgr[mask].astype(float) * (1 - alpha) + np.array([128, 0, 128]) * alpha).astype(np.uint8)
    
    cv2.imwrite(save_path, result)

# ==================== 绘图类（仅保存，不展示）====================
class TrainingPlotter:
    def __init__(self, save_dir):
        self.save_dir = save_dir
        self.epochs = []
        self.train_loss, self.val_loss = [], []
        self.train_iou, self.val_iou = [], []
        self.train_acc, self.val_acc = [], []
        
        # 使用非交互式后端，不弹出窗口
        plt.switch_backend('Agg')
        
    def update(self, epoch, train_loss, val_loss, train_iou, val_iou, train_acc, val_acc):
        self.epochs.append(epoch + 1)
        self.train_loss.append(train_loss)
        self.val_loss.append(val_loss)
        self.train_iou.append(train_iou)
        self.val_iou.append(val_iou)
        self.train_acc.append(train_acc)
        self.val_acc.append(val_acc)
        # 仅记录数据，不绘图展示
    
    def save(self):
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
    model_name = 'UNet_ResNet18'
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_dir = os.path.join(MODEL_DIR, f'{timestamp}_{model_name}')
    os.makedirs(save_dir, exist_ok=True)
    model_path = os.path.join(save_dir, 'best_model.pth')
    
    # 创建日志文件
    log_dir = str(LOG_ROOT / 'train')
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
    
    # 使用 smp Unet 模型（手动加载torchvision的ImageNet预训练权重，无需访问HuggingFace）
    model = smp.Unet(
        encoder_name='resnet18',
        encoder_weights=None,   # 先不加载权重
        in_channels=3,
        classes=1
    ).to(DEVICE)
    
    # 用 torchvision 加载 ResNet18 预训练权重
    # 若网络不通，可手动下载权重文件放到 TORCH_HOME/hub/checkpoints/ 目录：
    # 下载地址（国内镜像）：https://download.pytorch.org/models/resnet18-f37072fd.pth
    # 或：https://hf-mirror.com/pytorch/vision/resolve/main/resnet18-f37072fd.pth
    print("正在加载 ResNet18 ImageNet 预训练权重...")
    # 设置国内镜像加速（若直连失败可尝试）
    import os as _os
    _os.environ.setdefault('TORCH_HOME', _os.path.expanduser('~/.cache/torch'))
    try:
        tv_resnet = tv_models.resnet18(weights=tv_models.ResNet18_Weights.IMAGENET1K_V1)
    except Exception as e:
        print(f"警告：预训练权重下载失败（{e}），将使用随机初始化继续训练")
        tv_resnet = None
    
    if tv_resnet is not None:
        tv_state = tv_resnet.state_dict()
        # smp编码器的权重key格式与torchvision一致，直接按key匹配
        encoder_state = model.encoder.state_dict()
        matched, skipped = 0, 0
        new_state = {}
        for key in encoder_state:
            if key in tv_state and tv_state[key].shape == encoder_state[key].shape:
                new_state[key] = tv_state[key]
                matched += 1
            else:
                new_state[key] = encoder_state[key]
                skipped += 1
        model.encoder.load_state_dict(new_state)
        print(f"预训练权重加载完成：匹配 {matched} 层，跳过 {skipped} 层")
    else:
        print("使用随机初始化权重训练")
    
    criterion = CombinedLoss()
    # 编码器使用更小的学习率（预训练权重已较好，避免破坏）
    optimizer = optim.Adam([
        {'params': model.encoder.parameters(), 'lr': LEARNING_RATE * 0.1},
        {'params': model.decoder.parameters(), 'lr': LEARNING_RATE},
        {'params': model.segmentation_head.parameters(), 'lr': LEARNING_RATE},
    ], weight_decay=WEIGHT_DECAY)
    
    # 余弦退火学习率调度器（无重启，适合大模型稳定收敛）
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=200, eta_min=1e-6
    )
    
    best_val_iou = 0.0
    no_improve_count = 0
    plotter = TrainingPlotter(save_dir)
    
    print(f"Device: {DEVICE}")
    print(f"Train samples: {len(train_dataset)} (Augmentation: ON)")
    print(f"Val samples:   {len(val_dataset)}   (Augmentation: OFF)")
    
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
        val_cache = []  # 缓存验证结果，仅最佳模型时保存
        
        with torch.no_grad():
            for imgs, labels, names in tqdm(val_loader, desc=f"Epoch {epoch+1}/{total_epochs} [Val]"):
                imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
                
                outputs = model(imgs)
                loss = criterion(outputs, labels)
                
                val_loss += loss.item()
                val_iou += calc_iou(torch.sigmoid(outputs), labels)
                val_acc += calc_pixel_acc(torch.sigmoid(outputs), labels)
                
                # 缓存数据，延迟保存
                val_cache.append((imgs[0].cpu(), torch.sigmoid(outputs[0]).cpu(), names[0]))
        
        val_loss /= len(val_loader)
        val_iou /= len(val_loader)
        val_acc /= len(val_loader)
        
        # ========== Print ==========
        print(f"Epoch {epoch+1}/{total_epochs}")
        print(f"  Train - Loss: {train_loss:.4f}, IoU: {train_iou:.4f}, Acc: {train_acc:.4f}")
        print(f"  Val   - Loss: {val_loss:.4f}, IoU: {val_iou:.4f}, Acc: {val_acc:.4f}")
        
        # ========== Update Learning Rate ==========
        scheduler.step()
        current_lr = optimizer.param_groups[0]['lr']
        print(f"  Learning Rate: {current_lr:.6f}")
        
        # ========== Update Plot ==========
        plotter.update(epoch, train_loss, val_loss, train_iou, val_iou, train_acc, val_acc)
        
        # ========== Save Best Model & Early Stopping ==========
        if val_iou > best_val_iou:
            best_val_iou = val_iou
            no_improve_count = 0
            torch.save(model.state_dict(), model_path)
            # 保存验证集可视化
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
    
    sys.stdout = tee.terminal
    tee.close()


if __name__ == '__main__':
    train()
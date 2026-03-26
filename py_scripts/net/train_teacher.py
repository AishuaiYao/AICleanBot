import os
import glob
import numpy as np
import cv2
import torch
from torch.utils.data import Dataset, DataLoader
import torch.nn as nn
import torch.optim as optim
import segmentation_models_pytorch as smp
from tqdm import tqdm
from datetime import datetime
import random


# ==================== Focal Loss ====================
class FocalLoss(nn.Module):
    def __init__(self, alpha=0.25, gamma=2.0):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
    
    def forward(self, pred, target):
        # pred: logits (未经sigmoid)
        bce = nn.functional.binary_cross_entropy_with_logits(pred, target, reduction='none')
        
        # 计算pt
        pred_prob = torch.sigmoid(pred)
        pt = target * pred_prob + (1 - target) * (1 - pred_prob)
        
        # 计算alpha权重
        alpha_t = target * self.alpha + (1 - target) * (1 - self.alpha)
        
        # Focal Loss
        focal = alpha_t * (1 - pt) ** self.gamma * bce
        
        return focal.mean()


# ==================== 组合损失函数 ====================
class CombinedLoss(nn.Module):
    def __init__(self, alpha=0.75, gamma=2.0):
        super().__init__()
        self.dice = smp.losses.DiceLoss(mode='binary')
        self.focal = FocalLoss(alpha=alpha, gamma=gamma)
    
    def forward(self, pred, target):
        return self.dice(pred, target) + self.focal(pred, target)


# ==================== 配置 ====================
DATA_DIR = r'E:\AICleanBot\py_scripts\dataset'
IMAGE_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA')
LABEL_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA_label')
PRED_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA_pred')
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')
FIGURE_DIR = os.path.join(os.path.dirname(__file__), '..', 'figure')

# ==================== 可视化配置 ====================
SAVE_AUG_VIS = True  # 开关：是否保存数据增强对比图
AUG_VIS_FILENAME = 'aug_debug_batch.jpg'

BATCH_SIZE = 8
LEARNING_RATE = 1e-4
EPOCHS = 0  # 0=早停模式，>0=固定轮数
PATIENCE = 10  # 早停耐心值（仅EPOCHS=0时生效）
MAX_EPOCHS = 1000  # 最大训练轮数（仅EPOCHS=0时生效）
TRAIN_RATIO = 0.8

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# ==================== 数据增强配置 ====================
# 你可以在这里开启或关闭特定的增强功能
AUGMENTATION_CONFIG = {
    # --- 几何变换 (Geometry) : 同时作用于 Image 和 Label ---
    'h_flip': True,        # 水平翻转 (50% 概率)
    'v_flip': True,        # 垂直翻转 (50% 概率)
    'rotate': False,        # 随机旋转 (-30° ~ +30°)
    
    # --- 像素变换 (Pixel) : 只作用于 Image ---
    'brightness': True,    # 随机亮度 (0.8 ~ 1.2)
    'contrast': True,      # 随机对比度 (0.8 ~ 1.2)
    'noise': True,         # 高斯噪声
    'blur': True,          # 高斯模糊
    'color_jitter': False, # 色彩抖动 (灰度图通常不需要，除非是伪彩色)
}


# ==================== 数据增强函数 ====================
def apply_augmentations(img, label, config):
    h, w = img.shape[:2]
    applied_augs = []

    # -----------------------------------------------------------
    # 1. 几何变换 (必须同时应用到 img 和 label)
    # -----------------------------------------------------------
    
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
        # img 用双线性插值，label 用最近邻插值 (保持0/1值)
        img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        label = cv2.warpAffine(label, M, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        applied_augs.append(f'rot:{angle:.1f}')

    # -----------------------------------------------------------
    # 2. 像素变换 (只应用到 img)
    # -----------------------------------------------------------
    
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
        
    # 色彩抖动 (仅作为示例，灰度图效果有限，这里实现简单的 Gamma 校正模拟)
    if config.get('color_jitter') and random.random() > 0.5:
        gamma = random.uniform(0.8, 1.2)
        inv_gamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        img = cv2.LUT(img, table)
        applied_augs.append('jitter')

    return img, label, applied_augs


# ==================== 数据集 ====================
class SegDataset(Dataset):
    def __init__(self, image_dir, label_dir, img_names, augment=False):
        self.augment = augment
        
        # 只保留传入的文件名列表
        self.img_paths = [os.path.join(image_dir, n) for n in img_names]
        self.label_paths = [os.path.join(label_dir, n) for n in img_names]
        self.names = img_names
        
    def __len__(self):
        return len(self.names)
    
    def __getitem__(self, idx):
        # 读取原始图片 (灰度模式)
        img = cv2.imread(self.img_paths[idx], cv2.IMREAD_GRAYSCALE)
        label = cv2.imread(self.label_paths[idx], cv2.IMREAD_GRAYSCALE)
        
        # 备份原始用于可视化
        img_origin = img.copy()
        label_origin = label.copy()

        # --- 应用数据增强 (仅在训练模式下) ---
        applied_augs_list = []
        if self.augment:
            img, label, applied_augs_list = apply_augmentations(img, label, AUGMENTATION_CONFIG)
        
        # 备份增强后用于可视化
        img_aug = img.copy()
        label_aug = label.copy()

        # 生成可视化拼接图 (如果开启)
        # 格式: [原图, 原Label, 增强图, 增强Label]
        h, w = img_origin.shape
        vis_img = np.zeros((h, w * 4), dtype=np.uint8)
        if SAVE_AUG_VIS:
            vis_img = np.hstack([img_origin, label_origin, img_aug, label_aug])
            if applied_augs_list:
                # 在增强图上方打印增强手段
                text = ", ".join(applied_augs_list)
                # 计算文字位置 (打印在第3张图即增强图的上方)
                x_offset = w * 2 + 10
                y_offset = 20
                # 由于是灰度图，颜色只有0-255，为了清晰，可以用白色或者反色背景
                cv2.putText(vis_img, text, (x_offset, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255), 1, cv2.LINE_AA)

        # 归一化和格式转换
        img = img.astype(np.float32) / 255.0
        label = (label > 0).astype(np.float32)
        
        # 增加 Channel 维度 (H, W) -> (1, H, W)
        img = torch.from_numpy(img).unsqueeze(0)
        label = torch.from_numpy(label).unsqueeze(0)
        
        return img, label, self.names[idx], vis_img


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


# ==================== 训练 ====================
def train():
    # 固定随机种子（确保可复现）
    SEED = 42
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    
    # PyTorch确定性设置
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    
    os.makedirs(PRED_DIR, exist_ok=True)
    if SAVE_AUG_VIS:
        os.makedirs(FIGURE_DIR, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_dir = os.path.join(MODEL_DIR, timestamp)
    os.makedirs(save_dir, exist_ok=True)
    model_path = os.path.join(save_dir, 'best_model.pth')
    
    # --- 1. 获取所有文件名并打乱 ---
    img_files = set(glob.glob(os.path.join(IMAGE_DIR, '*.[jp][pn]g')) + glob.glob(os.path.join(IMAGE_DIR, '*.bmp')))
    label_files = set(glob.glob(os.path.join(LABEL_DIR, '*.[jp][pn]g')) + glob.glob(os.path.join(LABEL_DIR, '*.bmp')))
    
    img_names = {os.path.basename(p) for p in img_files}
    label_names = {os.path.basename(p) for p in label_files}
    common_names = sorted(list(img_names & label_names))
    
    random.shuffle(common_names)
    
    # --- 2. 手动划分 Train / Val ---
    train_size = int(len(common_names) * TRAIN_RATIO)
    train_names = common_names[:train_size]
    val_names = common_names[train_size:]
    
    # --- 3. 分别创建 Dataset (Train开启增强, Val关闭增强) ---
    train_dataset = SegDataset(IMAGE_DIR, LABEL_DIR, train_names, augment=True)
    val_dataset = SegDataset(IMAGE_DIR, LABEL_DIR, val_names, augment=False)
    
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=1, shuffle=False, num_workers=0)
    
    model = smp.Unet(
        encoder_name='resnet18',
        encoder_weights=None,
        in_channels=1,
        classes=1
    ).to(DEVICE)
    
    criterion = CombinedLoss()
    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
    
    best_val_loss = float('inf')
    no_improve_count = 0  # 早停计数器
    
    print(f"Device: {DEVICE}")
    print(f"Total samples: {len(common_names)}")
    print(f"Train samples: {len(train_names)} (Augmentation: ON)")
    print(f"Val samples:   {len(val_names)}   (Augmentation: OFF)")
    print(f"Augmentation Config: {AUGMENTATION_CONFIG}")
    
    if EPOCHS == 0:
        print(f"训练模式: 早停模式 (patience={PATIENCE}, max_epochs={MAX_EPOCHS})")
    else:
        print(f"训练模式: 固定轮数 (epochs={EPOCHS})")
    print("=" * 60)
    
    # 确定训练轮数
    total_epochs = EPOCHS if EPOCHS > 0 else MAX_EPOCHS
    
    for epoch in range(total_epochs):
        # ========== Train ==========
        model.train()
        train_loss = 0.0
        train_iou = 0.0
        train_acc = 0.0
        
        for imgs, labels, _, vis_imgs in tqdm(train_loader, desc=f"Epoch {epoch+1}/{EPOCHS} [Train]"):
            imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)

            # 保存本 batch 第一张增强对比图
            if SAVE_AUG_VIS:
                # vis_imgs 是 Tensor (B, H, W*4), 取第一个转换为 numpy 保存
                cv2.imwrite(os.path.join(FIGURE_DIR, AUG_VIS_FILENAME), vis_imgs[0].numpy())
            
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
            for imgs, labels, names, _ in tqdm(val_loader, desc=f"Epoch {epoch+1}/{EPOCHS} [Val]"):
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
        print(f"Epoch {epoch+1}/{EPOCHS}")
        print(f"  Train - Loss: {train_loss:.4f}, IoU: {train_iou:.4f}, Acc: {train_acc:.4f}")
        print(f"  Val   - Loss: {val_loss:.4f}, IoU: {val_iou:.4f}, Acc: {val_acc:.4f}")
        
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
    
    print(f"Training completed! Best val loss: {best_val_loss:.4f}")


if __name__ == '__main__':
    train()
import os
import glob
import numpy as np
import cv2
import torch
from torch.utils.data import Dataset, DataLoader, random_split
import torch.nn as nn
import torch.optim as optim
import segmentation_models_pytorch as smp
from tqdm import tqdm
from datetime import datetime


# ==================== 组合损失函数 ====================
class CombinedLoss(nn.Module):
    def __init__(self):
        super().__init__()
        self.dice = smp.losses.DiceLoss(mode='binary')
        self.bce = nn.BCEWithLogitsLoss()
    
    def forward(self, pred, target):
        return self.dice(pred, target) + self.bce(pred, target)


# ==================== 配置 ====================
DATA_DIR = r'E:\AICleanBot\py_scripts\dataset'
IMAGE_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA')
LABEL_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA_label')
PRED_DIR = os.path.join(DATA_DIR, 'FRAME_QQVGA_pred')
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')

BATCH_SIZE = 8
LEARNING_RATE = 1e-4
EPOCHS = 50
IMAGE_SIZE = 256
TRAIN_RATIO = 0.8

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


# ==================== 数据集 ====================
class SegDataset(Dataset):
    def __init__(self, image_dir, label_dir, img_size=256):
        self.img_size = img_size
        img_paths = set(glob.glob(os.path.join(image_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(image_dir, '*.bmp')))
        label_paths = set(glob.glob(os.path.join(label_dir, '*.[jp][pn]g')) + glob.glob(os.path.join(label_dir, '*.bmp')))
        
        img_names = {os.path.basename(p) for p in img_paths}
        label_names = {os.path.basename(p) for p in label_paths}
        common_names = sorted(img_names & label_names)
        
        self.img_paths = [os.path.join(image_dir, n) for n in common_names]
        self.label_paths = [os.path.join(label_dir, n) for n in common_names]
        self.names = common_names
        
    def __len__(self):
        return len(self.names)
    
    def __getitem__(self, idx):
        img = cv2.imread(self.img_paths[idx], cv2.IMREAD_GRAYSCALE)
        label = cv2.imread(self.label_paths[idx], cv2.IMREAD_GRAYSCALE)
        
        img = cv2.resize(img, (self.img_size, self.img_size))
        label = cv2.resize(label, (self.img_size, self.img_size))
        
        img = img.astype(np.float32) / 255.0
        label = (label > 127).astype(np.float32)
        
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


# ==================== 训练 ====================
def train():
    os.makedirs(PRED_DIR, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_dir = os.path.join(MODEL_DIR, timestamp)
    os.makedirs(save_dir, exist_ok=True)
    model_path = os.path.join(save_dir, 'best_model.pth')
    
    dataset = SegDataset(IMAGE_DIR, LABEL_DIR, IMAGE_SIZE)
    train_size = int(len(dataset) * TRAIN_RATIO)
    val_size = len(dataset) - train_size
    train_dataset, val_dataset = random_split(dataset, [train_size, val_size])
    
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
    
    print(f"Device: {DEVICE}")
    print(f"Train samples: {train_size}, Val samples: {val_size}")
    print("=" * 60)
    
    for epoch in range(EPOCHS):
        # ========== Train ==========
        model.train()
        train_loss = 0.0
        train_iou = 0.0
        train_acc = 0.0
        
        for imgs, labels, _ in tqdm(train_loader, desc=f"Epoch {epoch+1}/{EPOCHS} [Train]"):
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
            for imgs, labels, names in tqdm(val_loader, desc=f"Epoch {epoch+1}/{EPOCHS} [Val]"):
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
        
        # ========== Save Best Model ==========
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), model_path)
            print(f"  >>> Best model saved: {model_path}")
        
        print("-" * 60)
    
    print("Training completed!")


if __name__ == '__main__':
    train()
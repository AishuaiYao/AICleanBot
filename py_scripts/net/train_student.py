import os
import cv2
import torch
import torch.nn as nn
import torch.optim as optim
import torch.quantization as quantization
import numpy as np
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as T

# 1. 极简UNet（二分类固定单通道输出）
class DoubleConv(nn.Module):
    def __init__(self, in_c, out_c):
        super(DoubleConv, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_c, out_c, 3, 1, 1), nn.ReLU(),
            nn.Conv2d(out_c, out_c, 3, 1, 1), nn.ReLU()
        )
    def forward(self, x):
        return self.conv(x)


class UNetA(nn.Module):
    def __init__(self):
        super(UNetA, self).__init__()
        self.down1 = DoubleConv(1, 64)
        self.down2 = DoubleConv(64, 128)
        self.pool = nn.MaxPool2d(2)
        self.up1 = nn.ConvTranspose2d(128, 64, 2, 2)
        self.up2 = DoubleConv(128, 64)
        self.out = nn.Conv2d(64, 1, 1)

    def forward(self, x):
        x1 = self.down1(x)
        x2 = self.pool(x1)
        x3 = self.down2(x2)
        x4 = self.up1(x3)
        x5 = torch.cat([x4, x1], dim=1)
        x6 = self.up2(x5)
        return self.out(x6)

class UNetB(nn.Module):
    def __init__(self):
        super(UNetB, self).__init__()
        self.down1 = DoubleConv(1, 32)
        self.down2 = DoubleConv(32, 64)
        self.pool = nn.MaxPool2d(2)
        self.up1 = nn.ConvTranspose2d(64, 32, 2, 2)
        self.up2 = DoubleConv(64, 32)
        self.out = nn.Conv2d(32, 1, 1)

    def forward(self, x):
        x1 = self.down1(x)
        x2 = self.pool(x1)
        x3 = self.down2(x2)
        x4 = self.up1(x3)
        x5 = torch.cat([x4, x1], dim=1)
        x6 = self.up2(x5)
        return self.out(x6)

# 98.6k
class UNetC(nn.Module):
    def __init__(self):
        super(UNetC, self).__init__()
        self.down1 = DoubleConv(1, 16)
        self.down2 = DoubleConv(16, 32)
        self.pool = nn.MaxPool2d(2)
        self.up1 = nn.ConvTranspose2d(32, 16, 2, 2)
        self.up2 = DoubleConv(32, 16)
        self.out = nn.Conv2d(16, 1, 1)

    def forward(self, x):
        x1 = self.down1(x)
        x2 = self.pool(x1)
        x3 = self.down2(x2)
        x4 = self.up1(x3)
        x5 = torch.cat([x4, x1], dim=1)
        x6 = self.up2(x5)
        return self.out(x6)



# 2. 数据集加载（低版本兼容：Scale替代Resize，255转1）
class SegDataset(Dataset):
    def __init__(self, img_dir, label_dir, size=(256, 256)):
        self.size = size
        self.img_paths = []
        self.label_paths = []
        for img_file in os.listdir(img_dir):
            img_path = os.path.join(img_dir, img_file)
            label_path = os.path.join(label_dir, img_file)
            if os.path.exists(label_path):
                self.img_paths.append(img_path)
                self.label_paths.append(label_path)
        print(f"找到 {len(self.img_paths)} 对匹配的图片和标签")

    def __len__(self):
        return len(self.img_paths)

    def __getitem__(self, idx):
        # 图片预处理
        img = cv2.imread(self.img_paths[idx], cv2.IMREAD_GRAYSCALE)
        img = cv2.resize(img, self.size)
        img_tensor = torch.from_numpy(img).float() / 255.0
        img_tensor = img_tensor.unsqueeze(0)  # [H,W] -> [1,H,W]

        # 标签预处理（255转1，单通道）
        label = cv2.imread(self.label_paths[idx], cv2.IMREAD_GRAYSCALE)
        if label is None:
            raise FileNotFoundError(f"标签文件不存在: {self.label_paths[idx]}")
        label = cv2.resize(label, self.size)
        label_tensor = torch.from_numpy(label).float() / 255.0
        label_tensor = label_tensor.unsqueeze(0)  # [H,W] -> [1,H,W]

        # 返回张量+原始路径（用于可视化命名）
        return img_tensor, label_tensor, self.img_paths[idx]


def visualize_pred(model, dataloader, device, save_dir='pred_results'):
    os.makedirs(save_dir, exist_ok=True)  # 创建保存文件夹
    model.eval()
    with torch.no_grad():
        for imgs, labels, img_paths in dataloader:

            imgs, labels = imgs.to(device), labels.to(device)

            outputs = model(imgs)
            outputs = torch.sigmoid(outputs)  # logits转0-1概率
            preds = (outputs > 0.5).float()  # 0.5阈值分割
            preds = preds * 255  # 1转为255

            # 逐张拼接保存
            for i in range(imgs.shape[0]):
                img = imgs[i].cpu().numpy().squeeze() * 255
                img = img.astype(np.uint8)
                label = labels[i].cpu().numpy().squeeze() * 255
                label = label.astype(np.uint8)
                pred = preds[i].cpu().numpy().squeeze()
                pred = pred.astype(np.uint8)

                concat = np.hstack([img, label, pred])

                img_name = os.path.basename(img_paths[i])
                cv2.imwrite(os.path.join(save_dir, img_name), concat)
                print(f'预测结果已保存：{os.path.join(save_dir, img_name)}')
    model.train()

# 4. 主流程：训练+可视化+ONNX导出（无修改）
if __name__ == "__main__":
    # 超参数
    DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    EPOCHS = 5
    BATCH_SIZE = 2
    LR = 1e-3
    IMG_SIZE = (160, 120)

    # 加载数据集
    dataset = SegDataset('E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA', 'E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA_label', IMG_SIZE)
    dataloader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    # 模型、优化器、损失
    model = UNetC().to(DEVICE)
    optimizer = optim.Adam(model.parameters(), lr=LR)
    criterion = nn.BCEWithLogitsLoss()

    # 训练
    print(f'开始训练，共{EPOCHS}轮，设备：{DEVICE}')
    for epoch in range(EPOCHS):
        total_loss = 0.0
        for imgs, labels, _ in dataloader:
            imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
            optimizer.zero_grad()
            outputs = model(imgs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        print(f'Epoch {epoch + 1}/{EPOCHS}, Loss: {total_loss / len(dataloader):.4f}')

    # 将模型移到CPU用于导出ONNX
    model_cpu = model.cpu().eval()
    print('模型已移至CPU，eval模式')

    # 导出FP32 ONNX用于嵌入式设备后续量化
    onnx_path = os.path.join('E:\AICleanBot\py_scripts\models', 'unet_2class.onnx')
    print('\n正在导出FP32 ONNX模型...')
    torch.onnx.export(
        model_cpu,
        torch.randn(1, 1, *IMG_SIZE),
        onnx_path,
        input_names=["input"],
        output_names=["output"],
        opset_version=11,
        dynamic_axes={
            "input": {0: "batch", 2: "height", 3: "width"},
            "output": {0: "batch", 2: "height", 3: "width"}
        }
    )
    print(f'FP32 ONNX模型已导出：{onnx_path}')

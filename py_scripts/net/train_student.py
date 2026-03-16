import os
import cv2
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from torch.utils.data import Dataset, DataLoader


class DoubleConv(nn.Module):
    def __init__(self, in_c, out_c):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_c, out_c, 3, 1, 1), nn.ReLU(),
            nn.Conv2d(out_c, out_c, 3, 1, 1), nn.ReLU()
        )

    def forward(self, x):
        return self.conv(x)


class UNetC(nn.Module):
    def __init__(self):
        super().__init__()
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
        return self.out(self.up2(x5))


class SegDataset(Dataset):
    def __init__(self, img_dir, label_dir, size=(256, 256)):
        self.size = size
        self.img_paths = []
        self.label_paths = []
        for f in os.listdir(img_dir):
            img_path = os.path.join(img_dir, f)
            label_path = os.path.join(label_dir, f)
            if os.path.exists(label_path):
                self.img_paths.append(img_path)
                self.label_paths.append(label_path)
        print(f"找到 {len(self.img_paths)} 对匹配的图片和标签")

    def __len__(self):
        return len(self.img_paths)

    def __getitem__(self, idx):
        img = cv2.imread(self.img_paths[idx], cv2.IMREAD_GRAYSCALE)
        img = cv2.resize(img, self.size)
        img_tensor = torch.from_numpy(img).float().unsqueeze(0) / 255.0

        label = cv2.imread(self.label_paths[idx], cv2.IMREAD_GRAYSCALE)
        if label is None:
            raise FileNotFoundError(f"标签文件不存在: {self.label_paths[idx]}")
        label = cv2.resize(label, self.size)
        label_tensor = torch.from_numpy(label).float().unsqueeze(0) / 255.0

        return img_tensor, label_tensor, self.img_paths[idx]


if __name__ == "__main__":
    DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    EPOCHS = 5
    BATCH_SIZE = 2
    LR = 1e-3
    IMG_SIZE = (160, 120)

    dataset = SegDataset(
        'E:\\AICleanBot\\py_scripts\\dataset\\FRAME_QQVGA',
        'E:\\AICleanBot\\py_scripts\\dataset\\FRAME_QQVGA_label',
        IMG_SIZE
    )
    dataloader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    model = UNetC().to(DEVICE)
    optimizer = optim.Adam(model.parameters(), lr=LR)
    criterion = nn.BCEWithLogitsLoss()

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

    model_cpu = model.cpu().eval()
    print('模型已移至CPU，eval模式')

    onnx_path = os.path.join('E:\\AICleanBot\\py_scripts\\models', 'unet_2class.onnx')
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

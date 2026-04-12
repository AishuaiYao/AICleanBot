import os
import glob
import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset
from esp_ppq.api import espdl_quantize_onnx


def collate_fn(batch):
    # TensorDataset 迭代的时候返回的是 Tuple(x, y), 量化的时候只需要x, 不需要label y。
    batch = batch[0]
    return batch


if __name__ == "__main__":
    
    ONNX_MODEL_PATH = r"E:\AICleanBot\py_scripts\models\20260412_180030_UNetMiniExp5\model.onnx"
    ESPDL_MODEL_PATH = r"E:\AICleanBot\py_scripts\models\20260412_180030_UNetMiniExp5\model.espdl"
    INPUT_SHAPE = [1, 1, 120, 160]  # 1 个输入, 1通道, 120x160 (HxW)
    TARGET = "esp32s3"  # 量化目标类型，可选 'c', 'esp32s3' or 'esp32p4'
    NUM_OF_BITS = 8  # 量化位数
    DEVICE = "cpu"  # 'cuda' or 'cpu', if you use cuda, please make sure that cuda is available
    NUM_CALIB_SAMPLES = 32  # 校准样本数量
    
    # 从真实数据集加载校准数据
    IMAGE_DIR = r"E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA"
    print(f"从 {IMAGE_DIR} 加载 {NUM_CALIB_SAMPLES} 个校准样本...")
    
    img_files = glob.glob(os.path.join(IMAGE_DIR, '*.[jp][pn]g')) + glob.glob(os.path.join(IMAGE_DIR, '*.bmp'))
    img_files = sorted(img_files)[:NUM_CALIB_SAMPLES]
    
    images = []
    for img_path in img_files:
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        img = img.astype(np.float32) / 255.0
        img = torch.from_numpy(img).unsqueeze(0)  # [1, H, W]
        images.append(img)
    
    x = torch.stack(images)
    y = torch.zeros_like(x)  # dummy labels
    
    # dataloader shuffle必须设置为False。
    # 因为计算量化误差的时候会多次遍历数据集，如果shuffle是True的话，会得到错误的量化误差。
    dataset = TensorDataset(x, y)
    dataloader = DataLoader(dataset, batch_size=1, shuffle=False)
    
    print(f"开始量化模型...")
    print(f"输入模型: {ONNX_MODEL_PATH}")
    print(f"输出模型: {ESPDL_MODEL_PATH}")
    print(f"目标平台: {TARGET}")
    print(f"量化位数: {NUM_OF_BITS} bit")
    
    quant_ppq_graph = espdl_quantize_onnx(
        onnx_import_file=ONNX_MODEL_PATH,
        espdl_export_file=ESPDL_MODEL_PATH,
        calib_dataloader=dataloader,
        calib_steps=NUM_CALIB_SAMPLES,  # 校准的步数
        input_shape=INPUT_SHAPE,  # 输入形状
        inputs=None,
        target=TARGET,  # 量化目标类型
        num_of_bits=NUM_OF_BITS,  # 量化位数
        collate_fn=collate_fn,
        dispatching_override=None,
        device=DEVICE,
        error_report=True,
        skip_export=False,
        export_test_values=False,
        verbose=1,  # 输出详细日志信息
    )
    
    print(f"\n量化完成！模型已保存至: {ESPDL_MODEL_PATH}")


# (.venv) PS E:\AICleanBot> & e:\AICleanBot\.venv\Scripts\python.exe e:/AICleanBot/py_scripts/utils/quantize_onnx_model.py

# ___________ ____        ____  ____  ____
# / ____/ ___// __ \      / __ \/ __ \/ __ \
# / __/  \__ \/ /_/ /_____/ /_/ / /_/ / / / /
# / /___ ___/ / ____/_____/ ____/ ____/ /_/ /
# /_____//____/_/         /_/   /_/    \___\_\


# 从 E:\AICleanBot\py_scripts\dataset\FRAME_QQVGA 加载 32 个校准样本...
# 开始量化模型...
# 输入模型: E:\AICleanBot\py_scripts\models\20260412_180030_UNetMiniExp5\model.onnx
# 输出模型: E:\AICleanBot\py_scripts\models\20260412_180030_UNetMiniExp5\model.espdl
# 目标平台: esp32s3
# 量化位数: 8 bit
# [20:32:09] ConvTranspose Decomposition Pass Running ... Finished.
# [20:32:09] PPQ Quantization Fusion Pass Running ...       Finished.
# [20:32:09] PPQ Quantize Simplify Pass Running ...         Finished.
# [20:32:09] PPQ Parameter Quantization Pass Running ...    Finished.
# Calibration Progress(Phase 1): 100%|████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 32/32 [00:01<00:00, 25.98it/s] 
# Calibration Progress(Phase 2): 100%|████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 32/32 [00:02<00:00, 10.96it/s] 
# Finished.
# [20:32:14] PPQ Quantization Alignment Pass Running ...    Finished.
# [20:32:14] PPQ Passive Parameter Quantization Running ... Finished.
# --------- Network Snapshot ---------
# Num of Op:                    [69]
# Num of Quantized Op:          [69]
# Num of Variable:              [137]
# Num of Quantized Var:         [137]
# ------- Quantization Snapshot ------
# Num of Quant Config:          [208]
# ACTIVATED:                    [65]
# OVERLAPPED:                   [93]
# PASSIVE:                      [44]
# FP32:                         [6]
# Network Quantization Finished.
# Analysing Graphwise Quantization Error(Phrase 1):: 100%|██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 8/8 [00:01<00:00,  7.57it/s]
# Analysing Graphwise Quantization Error(Phrase 2):: 100%|██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 8/8 [00:01<00:00,  5.47it/s] 
# Layer                         | NOISE:SIGNAL POWER RATIO
# /dec1/conv/conv.9/Conv:       | ████████████████████ | 54.835%
# /bottleneck/conv/conv.9/Conv: | ███████████          | 30.141%
# /bottleneck/conv/conv.6/Conv: | ███████████          | 30.093%
# /dec3/conv/conv.6/Conv:       | ███████████          | 28.905%
# /dec3/conv/conv.0/Conv:       | ██████████           | 28.656%
# /dec3/conv/conv.9/Conv:       | █████████            | 25.761%
# /dec3/conv/conv.3/Conv:       | █████████            | 25.682%
# /bottleneck/conv/conv.3/Conv: | █████████            | 25.473%
# /enc3/conv/conv.9/Conv:       | █████████            | 23.671%
# /bottleneck/conv/conv.0/Conv: | ████████             | 23.263%
# /enc3/conv/conv.6/Conv:       | ████████             | 21.446%
# /conv3/Conv:                  | ████████             | 21.424%
# /dec2/conv/conv.0/Conv:       | ███████              | 19.210%
# /enc3/conv/conv.3/Conv:       | ██████               | 17.683%
# /conv2/Conv:                  | ██████               | 17.381%
# /dec2/conv/conv.6/Conv:       | ██████               | 16.088%
# /enc2/conv/conv.9/Conv:       | ██████               | 15.978%
# /dec2/conv/conv.3/Conv:       | ██████               | 15.816%
# /enc3/conv/conv.0/Conv:       | ██████               | 15.652%
# /dec2/conv/conv.9/Conv:       | ██████               | 15.526%
# /out/Conv:                    | ██████               | 15.307%
# /enc2/conv/conv.3/Conv:       | ██████               | 15.243%
# /dec1/conv/conv.6/Conv:       | ██████               | 15.181%
# /enc2/conv/conv.6/Conv:       | █████                | 13.638%
# /dec1/conv/conv.3/Conv:       | █████                | 13.592%
# /conv1/Conv:                  | █████                | 12.422%
# /dec1/conv/conv.0/Conv:       | ████                 | 10.999%
# /enc2/conv/conv.0/Conv:       | ███                  | 8.787%
# /enc1/conv/conv.9/Conv:       | ██                   | 5.431%
# /enc1/conv/conv.6/Conv:       | █                    | 1.951%
# /enc1/conv/conv.3/Conv:       |                      | 0.043%
# /enc1/conv/conv.0/Conv:       |                      | 0.009%
# Analysing Layerwise quantization error:: 100%|██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 32/32 [00:12<00:00,  2.54it/s] 
# Layer                         | NOISE:SIGNAL POWER RATIO
# /enc2/conv/conv.0/Conv:       | ████████████████████ | 0.191%
# /enc1/conv/conv.0/Conv:       | ████████████████████ | 0.187%
# /enc1/conv/conv.6/Conv:       | ████████████         | 0.116%
# /dec1/conv/conv.6/Conv:       | ████████             | 0.073%
# /conv1/Conv:                  | ███████              | 0.065%
# /out/Conv:                    | ████                 | 0.042%
# /enc1/conv/conv.9/Conv:       | ███                  | 0.026%
# /enc2/conv/conv.6/Conv:       | ██                   | 0.020%
# /dec1/conv/conv.3/Conv:       | █                    | 0.014%
# /enc1/conv/conv.3/Conv:       | █                    | 0.013%
# /enc3/conv/conv.6/Conv:       | █                    | 0.010%
# /enc3/conv/conv.0/Conv:       | █                    | 0.010%
# /conv2/Conv:                  | █                    | 0.010%
# /conv3/Conv:                  | █                    | 0.008%
# /enc3/conv/conv.3/Conv:       | █                    | 0.007%
# /dec1/conv/conv.0/Conv:       |                      | 0.005%
# /enc2/conv/conv.9/Conv:       |                      | 0.005%
# /bottleneck/conv/conv.0/Conv: |                      | 0.004%
# /dec3/conv/conv.0/Conv:       |                      | 0.003%
# /enc2/conv/conv.3/Conv:       |                      | 0.003%
# /dec3/conv/conv.3/Conv:       |                      | 0.002%
# /dec2/conv/conv.6/Conv:       |                      | 0.002%
# /enc3/conv/conv.9/Conv:       |                      | 0.002%
# /dec2/conv/conv.9/Conv:       |                      | 0.001%
# /dec3/conv/conv.6/Conv:       |                      | 0.001%
# /dec1/conv/conv.9/Conv:       |                      | 0.001%
# /bottleneck/conv/conv.6/Conv: |                      | 0.001%
# /bottleneck/conv/conv.9/Conv: |                      | 0.001%
# /dec3/conv/conv.9/Conv:       |                      | 0.001%
# /bottleneck/conv/conv.3/Conv: |                      | 0.001%
# /dec2/conv/conv.3/Conv:       |                      | 0.001%
# /dec2/conv/conv.0/Conv:       |                      | 0.001%
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_0 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_3 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_1 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_4 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_2 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_5 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_0 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_3 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_1 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_4 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_2 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_5 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_0 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_3 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_1 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_4 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_2 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_5 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  skip not QuantableOperation
# [INFO][ESPDL][2026-04-12 20:32:29]:  skip not QuantableOperation
# [INFO][ESPDL][2026-04-12 20:32:29]:  skip not QuantableOperation
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_0 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_3 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_1 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_4 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_2 because it's not exportable
# [INFO][ESPDL][2026-04-12 20:32:29]:  Skip PPQ_Variable_5 because it's not exportable

# 量化完成！模型已保存至: E:\AICleanBot\py_scripts\models\20260412_180030_UNetMiniExp5\model.espdl

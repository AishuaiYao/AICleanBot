import os
import sys
import torch
from torch.utils.data import DataLoader, TensorDataset
from esp_ppq.api import espdl_quantize_onnx


class Tee:
    """同时输出到终端和文件"""
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()
    def flush(self):
        for f in self.files:
            f.flush()


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
    
    # 设置日志保存
    LOG_DIR = r"E:\AICleanBot\logs\quantize"
    os.makedirs(LOG_DIR, exist_ok=True)
    model_name = os.path.basename(os.path.dirname(ONNX_MODEL_PATH))  # 提取 20260412_180030_UNetMiniExp5
    log_path = os.path.join(LOG_DIR, f"{model_name}.txt")
    log_file = open(log_path, 'w', encoding='utf-8')
    original_stdout = sys.stdout
    sys.stdout = Tee(original_stdout, log_file)
    
    # 生成校准数据（随机灰度图像）
    print(f"生成 {NUM_CALIB_SAMPLES} 个校准样本...")
    x = torch.rand(NUM_CALIB_SAMPLES, 1, 120, 160, dtype=torch.float32)
    y = torch.zeros(NUM_CALIB_SAMPLES, 1, 120, 160, dtype=torch.float32)  # dummy labels
    
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
        export_test_values=True,
        verbose=1,  # 输出详细日志信息
    )
    
    print(f"\n量化完成！模型已保存至: {ESPDL_MODEL_PATH}")
    print(f"日志已保存至: {log_path}")
    
    # 恢复标准输出并关闭日志文件
    sys.stdout = original_stdout
    log_file.close()


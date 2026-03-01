from sin_model import generate_data, SinPredictor
from torch.utils.data import DataLoader, TensorDataset
from esp_ppq.api import espdl_quantize_onnx
from esp_ppq.executor import TorchExecutor
import torch


def collate_fn(batch):
    batch = batch[0].to(DEVICE)
    return batch


if __name__ == "__main__":

    ONNX_MODEL_PATH = "sin_model.onnx"
    ESPDL_MODEL_PATH = "sin_model.espdl"
    INPUT_SHAPE = [1, 1]
    TARGET = "esp32s3"
    NUM_OF_BITS = 8
    DEVICE = "cpu"

    x, y = generate_data()
    dataset = TensorDataset(x, y)
    dataloader = DataLoader(dataset, batch_size=32, shuffle=False)

    # 1. 量化并导出 espdl
    quant_ppq_graph = espdl_quantize_onnx(
        onnx_import_file=ONNX_MODEL_PATH,
        espdl_export_file=ESPDL_MODEL_PATH,
        calib_dataloader=dataloader,
        calib_steps=32,
        input_shape=INPUT_SHAPE,
        inputs=None,
        target=TARGET,
        num_of_bits=NUM_OF_BITS,
        collate_fn=collate_fn,
        device=DEVICE,
        error_report=True,
        skip_export=False,
        export_test_values=True,
        verbose=1,
    )

    # ===================== 用 info 里的输入推理 =====================
    # 从 .info 来
    input_quant = -10
    input_exp = -4
    input_real = input_quant * (2 ** input_exp)  # = -0.625

    test_input = torch.tensor([[input_real]], dtype=torch.float32).to(DEVICE)

    executor = TorchExecutor(graph=quant_ppq_graph, device=DEVICE)
    output_list = executor.forward(test_input)  # 这里返回 list

    # 取出第一个输出
    output_real = output_list[0]

    # ===================== 对比结果 =====================
    print("\n===== 量化模型推理结果 =====")
    print("输入(真实值):", test_input.item())
    print("量化模型输出(真实值):", output_real.item())

    # info 里的标准答案
    output_quant = -56
    output_exp = -7
    output_gt_real = output_quant * (2 ** output_exp)
    print("info 里的标准答案(真实值):", output_gt_real)

    # 误差
    print("绝对误差:", abs(output_real.item() - output_gt_real))
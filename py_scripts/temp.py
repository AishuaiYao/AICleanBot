import requests
import os

# 下载链接
url = "https://github.com/madhephaestus/ESP32Encoder/archive/refs/heads/master.zip"
# 保存的文件名
save_filename = "ESP32Encoder-master.zip"

def download_zip():
    try:
        # 发送GET请求，流式下载（适合大文件）
        response = requests.get(url, stream=True)
        response.raise_for_status()  # 检查请求是否成功
        
        # 写入文件
        with open(save_filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        print(f"下载完成！文件保存为：{os.path.abspath(save_filename)}")
    except requests.exceptions.RequestException as e:
        print(f"下载失败：{e}")

if __name__ == "__main__":
    # 检查是否安装requests，未安装则自动安装
    try:
        import requests
    except ImportError:
        os.system("pip install requests")
        import requests
    download_zip()
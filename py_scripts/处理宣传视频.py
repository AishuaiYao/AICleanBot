"""使用 FFmpeg 将本目录 MP4 导出为前30秒、1280×720(16:9)、码率约1M、H.264+AAC、小于100M。
依赖：ffmpeg 和 ffprobe 已加入 PATH。原文件不变。
运行：python 处理宣传视频.py
"""
from pathlib import Path
import json
import subprocess


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format',
        '-of', 'json', str(path)]))


def main():
    folder = Path(__file__).resolve().parent
    output = folder / '已处理_30秒_1280x720'
    output.mkdir(exist_ok=True)
    for source in sorted(folder.glob('*.mp4')):
        info = probe(source)
        if float(info['format']['duration']) < 30:
            raise ValueError(f'{source.name} 不足30秒，请先确认截取策略')
        dest = output / (source.stem + '-30s.mp4')
        # 完整保留超宽游戏画面，居中补黑边，不裁掉两侧操作按钮。
        filters = ('scale=1280:720:force_original_aspect_ratio=decrease:'
                   'force_divisible_by=2,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,'
                   'setsar=1,fps=30')
        print(f'正在处理：{source.name}', flush=True)
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-i', str(source), '-t', '30', '-map', '0:v:0', '-map', '0:a:0?',
            '-vf', filters, '-c:v', 'libx264', '-preset', 'fast',
            '-b:v', '1M', '-maxrate', '1M', '-bufsize', '2M',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '128k', '-ar', '48000',
            '-af', 'apad', '-map_metadata', '-1', '-movflags', '+faststart',
            str(dest)], check=True)
        result = probe(dest)
        video = next(s for s in result['streams'] if s['codec_type'] == 'video')
        audio = next((s for s in result['streams'] if s['codec_type'] == 'audio'), None)
        duration = float(result['format']['duration'])
        size = dest.stat().st_size
        if ((video['width'], video['height']) != (1280, 720)
                or video.get('codec_name') != 'h264'
                or (audio is not None and audio.get('codec_name') != 'aac')
                or abs(duration - 30) > .05 or size >= 100_000_000):
            raise ValueError(f'输出验证失败：{dest.name}，{duration}s，{size}字节')
        print(f'完成：{dest.name} | {duration:.3f}s | 1280×720 | h264/aac | {size/1_000_000:.2f}MB', flush=True)
    print(f'输出目录：{output}', flush=True)


if __name__ == '__main__':
    main()

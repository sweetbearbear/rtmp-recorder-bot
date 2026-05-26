import os
import re
import signal
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, BotCommand

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BASE_DIR = Path(os.getenv("BASE_DIR", "/home/sweetbear/rtmp"))
MAX_RECORDINGS = int(os.getenv("MAX_RECORDINGS", "3"))

VIDEOS_DIR = BASE_DIR / "videos"
TEMP_DIR = BASE_DIR / "temp"
LOGS_DIR = BASE_DIR / "logs"

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class RecordingTask:
    def __init__(
        self,
        task_id: int,
        url: str,
        stream_id: str,
        temp_path: Path,
        final_path: Path,
        log_path: Path,
        process: asyncio.subprocess.Process,
        started_at: datetime,
    ):
        self.task_id = task_id
        self.url = url
        self.stream_id = stream_id
        self.temp_path = temp_path
        self.final_path = final_path
        self.log_path = log_path
        self.process = process
        self.started_at = started_at


recordings: Dict[int, RecordingTask] = {}
next_task_id = 1


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == ADMIN_ID)


def admin_only_text() -> str:
    return "你没有权限使用这个 Bot。"


def extract_stream_id(url: str) -> str:
    """
    从直播流地址里提取直播 ID。

    示例：
    rtmp://pull2.ivo89.com/5showcam/204440_1779774754?auth_key=xxx

    提取：
    204440
    """

    clean_url = url.strip()

    match = re.search(r"/5showcam/([^/?#]+)", clean_url)
    if match:
        raw_name = match.group(1)
    else:
        raw_name = clean_url.rstrip("/").split("/")[-1].split("?")[0]

    stream_id = raw_name.split("_")[0]
    stream_id = re.sub(r"[^0-9A-Za-z_-]", "_", stream_id)

    return stream_id or "unknown"


def build_record_filename(url: str, started_at: datetime) -> str:
    """
    文件名格式：
    204440_20260526_1638.flv
    """

    stream_id = extract_stream_id(url)
    date_text = started_at.strftime("%Y%m%d")
    time_text = started_at.strftime("%H%M")

    return f"{stream_id}_{date_text}_{time_text}.flv"


def format_duration(started_at: datetime) -> str:
    seconds = int((datetime.now(BEIJING_TZ) - started_at).total_seconds())

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}小时{minutes}分钟{secs}秒"
    if minutes > 0:
        return f"{minutes}分钟{secs}秒"
    return f"{secs}秒"


def parse_record_command(text: str) -> Optional[str]:
    """
    支持：
    /record rtmp://xxx
    """

    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        return None

    return parts[1].strip()


def looks_like_stream_url(url: str) -> bool:
    allowed_prefixes = (
        "rtmp://",
        "rtmps://",
        "http://",
        "https://",
    )

    return url.startswith(allowed_prefixes)


async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="启动和查看帮助"),
        BotCommand(command="record", description="开始录制直播流"),
        BotCommand(command="stop", description="停止录制任务"),
        BotCommand(command="status", description="查看录制状态"),
        BotCommand(command="list", description="查看已录制视频"),
        BotCommand(command="help", description="查看命令说明"),
    ]

    await bot.set_my_commands(commands)


@dp.message(CommandStart())
async def start_handler(message: Message):
    if not is_admin(message):
        await message.answer(admin_only_text())
        return

    await message.answer(
        "RTMP 录制 Bot 已启动。\n\n"
        "可用命令：\n"
        "/record rtmp://地址 - 开始录制\n"
        "/status - 查看录制状态\n"
        "/stop 任务ID - 停止指定任务\n"
        "/stop all - 停止全部任务\n"
        "/list - 查看已录制视频\n"
        "/help - 查看帮助\n\n"
        "示例：\n"
        "/record rtmp://pull2.ivo89.com/5showcam/204440_1779774754?auth_key=xxx\n\n"
        "文件名格式：\n"
        "直播ID_年月日_时分.flv"
    )


@dp.message(Command("help"))
async def help_handler(message: Message):
    if not is_admin(message):
        await message.answer(admin_only_text())
        return

    await message.answer(
        "命令说明：\n\n"
        "开始录制：\n"
        "/record rtmp://直播流地址\n\n"
        "查看状态：\n"
        "/status\n\n"
        "停止指定任务：\n"
        "/stop 1\n\n"
        "停止全部任务：\n"
        "/stop all\n\n"
        "查看视频：\n"
        "/list\n\n"
        "录制格式：flv\n"
        "录制方式：ffmpeg -c copy，不转码\n"
        "文件名格式：直播ID_年月日_时分.flv\n"
        f"当前最大并发录制数：{MAX_RECORDINGS}"
    )


@dp.message(Command("record"))
async def record_handler(message: Message):
    global next_task_id

    if not is_admin(message):
        await message.answer(admin_only_text())
        return

    if len(recordings) >= MAX_RECORDINGS:
        await message.answer(
            f"当前录制任务已达上限：{MAX_RECORDINGS} 个。\n"
            "请先停止部分任务后再开始新的录制。"
        )
        return

    url = parse_record_command(message.text or "")

    if not url:
        await message.answer(
            "用法：\n"
            "/record rtmp://直播流地址\n\n"
            "示例：\n"
            "/record rtmp://pull2.ivo89.com/5showcam/204440_1779774754?auth_key=xxx"
        )
        return

    if not looks_like_stream_url(url):
        await message.answer(
            "直播流地址格式不太对。\n"
            "目前支持 rtmp://、rtmps://、http://、https:// 开头的地址。"
        )
        return

    task_id = next_task_id
    next_task_id += 1

    now = datetime.now(BEIJING_TZ)
    stream_id = extract_stream_id(url)

    filename = build_record_filename(url, now)
    temp_path = TEMP_DIR / filename
    final_path = VIDEOS_DIR / filename

    log_name = filename.replace(".flv", ".log")
    log_path = LOGS_DIR / log_name

    if temp_path.exists() or final_path.exists():
        suffix = now.strftime("%S")
        filename = filename.replace(".flv", f"_{suffix}.flv")
        temp_path = TEMP_DIR / filename
        final_path = VIDEOS_DIR / filename
        log_path = LOGS_DIR / filename.replace(".flv", ".log")

    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-rw_timeout",
        "15000000",
        "-i",
        url,
        "-c",
        "copy",
        "-f",
        "flv",
        str(temp_path),
    ]

    try:
        log_file = open(log_path, "wb")

        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=log_file,
            stderr=log_file,
            preexec_fn=os.setsid,
        )

        recordings[task_id] = RecordingTask(
            task_id=task_id,
            url=url,
            stream_id=stream_id,
            temp_path=temp_path,
            final_path=final_path,
            log_path=log_path,
            process=process,
            started_at=now,
        )

        asyncio.create_task(watch_recording(task_id, log_file))

        await message.answer(
            "已开始录制。\n\n"
            f"任务ID：{task_id}\n"
            f"直播ID：{stream_id}\n"
            f"录制格式：flv\n"
            f"文件名：{temp_path.name}\n\n"
            "停止录制：\n"
            f"/stop {task_id}"
        )

    except FileNotFoundError:
        await message.answer("启动 ffmpeg 失败：系统里找不到 ffmpeg。")
    except Exception as e:
        await message.answer(f"启动录制失败：{e}")


async def watch_recording(task_id: int, log_file):
    task = recordings.get(task_id)

    if not task:
        try:
            log_file.close()
        except Exception:
            pass
        return

    try:
        await task.process.wait()
    finally:
        try:
            log_file.close()
        except Exception:
            pass

    task = recordings.pop(task_id, None)

    if not task:
        return

    if task.temp_path.exists() and task.temp_path.stat().st_size > 0:
        try:
            task.temp_path.rename(task.final_path)
        except Exception:
            pass


@dp.message(Command("stop"))
async def stop_handler(message: Message):
    if not is_admin(message):
        await message.answer(admin_only_text())
        return

    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "用法：\n"
            "/stop 任务ID\n"
            "/stop all\n\n"
            "先用 /status 查看任务ID。"
        )
        return

    target = parts[1].strip().lower()

    if target == "all":
        if not recordings:
            await message.answer("当前没有正在录制的任务。")
            return

        ids = list(recordings.keys())

        for task_id in ids:
            await stop_recording_task(task_id)

        await message.answer(f"已发送停止信号，共 {len(ids)} 个任务。")
        return

    if not target.isdigit():
        await message.answer("任务ID需要是数字，比如：/stop 1")
        return

    task_id = int(target)

    if task_id not in recordings:
        await message.answer(f"没有找到任务ID：{task_id}")
        return

    await stop_recording_task(task_id)

    await message.answer(
        f"已发送停止信号：任务 {task_id}\n"
        "视频会自动从 temp 移动到 videos。"
    )


async def stop_recording_task(task_id: int):
    task = recordings.get(task_id)

    if not task:
        return

    process = task.process

    if process.returncode is not None:
        return

    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        try:
            process.terminate()
        except Exception:
            return

    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except asyncio.TimeoutError:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


@dp.message(Command("status"))
async def status_handler(message: Message):
    if not is_admin(message):
        await message.answer(admin_only_text())
        return

    video_count = len([p for p in VIDEOS_DIR.iterdir() if p.is_file()])
    temp_count = len([p for p in TEMP_DIR.iterdir() if p.is_file()])

    if not recordings:
        await message.answer(
            "当前状态：空闲\n\n"
            f"已完成视频数量：{video_count}\n"
            f"临时文件数量：{temp_count}\n"
            f"最大并发录制数：{MAX_RECORDINGS}"
        )
        return

    lines = [
        "当前状态：正在录制",
        "",
        f"正在录制任务数：{len(recordings)} / {MAX_RECORDINGS}",
        f"已完成视频数量：{video_count}",
        "",
        "任务列表：",
    ]

    for task_id, task in recordings.items():
        size_mb = 0

        if task.temp_path.exists():
            size_mb = task.temp_path.stat().st_size / 1024 / 1024

        lines.append(
            f"\n任务ID：{task_id}\n"
            f"直播ID：{task.stream_id}\n"
            f"时长：{format_duration(task.started_at)}\n"
            f"临时大小：{size_mb:.2f} MB\n"
            f"文件名：{task.temp_path.name}\n"
            f"停止命令：/stop {task_id}"
        )

    await message.answer("\n".join(lines))


@dp.message(Command("list"))
async def list_handler(message: Message):
    if not is_admin(message):
        await message.answer(admin_only_text())
        return

    files = sorted(
        [p for p in VIDEOS_DIR.iterdir() if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not files:
        await message.answer("videos 目录里还没有录制完成的视频。")
        return

    lines = ["最近录制的视频："]

    for index, file in enumerate(files[:10], start=1):
        size_mb = file.stat().st_size / 1024 / 1024
        mtime = datetime.fromtimestamp(
            file.stat().st_mtime,
            tz=BEIJING_TZ,
        ).strftime("%Y-%m-%d %H:%M:%S")

        lines.append(
            f"\n{index}. {file.name}\n"
            f"大小：{size_mb:.2f} MB\n"
            f"时间：{mtime}"
        )

    await message.answer("\n".join(lines))


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("缺少 BOT_TOKEN，请检查 app/.env 文件")

    await set_bot_commands()

    print("Bot 正在运行...")
    print(f"BASE_DIR: {BASE_DIR}")
    print(f"MAX_RECORDINGS: {MAX_RECORDINGS}")
    print("FORMAT: flv")
    print("TIMEZONE: Asia/Shanghai")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

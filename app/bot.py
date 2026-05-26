import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BASE_DIR = os.getenv("BASE_DIR", "/home/sweetbear/rtmp")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def is_admin(message: Message) -> bool:
    return message.from_user and message.from_user.id == ADMIN_ID


@dp.message(CommandStart())
async def start_handler(message: Message):
    if not is_admin(message):
        await message.answer("你没有权限使用这个 Bot。")
        return

    await message.answer(
        "RTMP 录制 Bot 已启动。\n\n"
        "当前支持命令：\n"
        "/start - 查看帮助\n"
        "/status - 查看状态"
    )


@dp.message(Command("status"))
async def status_handler(message: Message):
    if not is_admin(message):
        await message.answer("你没有权限使用这个 Bot。")
        return

    videos_dir = os.path.join(BASE_DIR, "videos")
    temp_dir = os.path.join(BASE_DIR, "temp")

    video_count = len(os.listdir(videos_dir)) if os.path.exists(videos_dir) else 0
    temp_count = len(os.listdir(temp_dir)) if os.path.exists(temp_dir) else 0

    await message.answer(
        "当前状态：空闲\n\n"
        f"视频目录：{videos_dir}\n"
        f"已完成视频数量：{video_count}\n"
        f"临时文件数量：{temp_count}"
    )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("缺少 BOT_TOKEN，请检查 .env 文件")

    print("Bot 正在运行...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

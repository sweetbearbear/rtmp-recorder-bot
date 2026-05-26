#!/usr/bin/env bash
set -e

APP_DIR="/home/sweetbear/rtmp"
SERVICE_NAME="rtmp-bot"

echo "==> 进入项目目录"
cd "$APP_DIR"

echo "==> 拉取 GitHub 最新代码"
git pull

echo "==> 激活虚拟环境并更新依赖"
source "$APP_DIR/.venv/bin/activate"
pip install -r requirements.txt

echo "==> 重启服务"
sudo systemctl restart "$SERVICE_NAME"

echo "==> 查看服务状态"
sudo systemctl --no-pager status "$SERVICE_NAME"

echo "==> 更新完成"

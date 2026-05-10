#!/bin/bash
# MonkeyCode 协议验证 MVP 运行脚本

set -e
cd "$(dirname "$0")"

# 检查依赖
if ! python3 -c "import requests" 2>/dev/null; then
    echo "安装依赖..."
    pip3 install -r requirements.txt
fi

echo "=========================================="
echo "  MonkeyCode 协议验证 MVP"
echo "=========================================="
echo ""
echo "选择运行模式:"
echo "  1) 运行协议验证测试"
echo "  2) 启动 OpenAI 兼容代理"
echo "  3) 交互式登录获取 Session Cookie"
echo ""
read -p "请选择 (1/2/3): " choice

case $choice in
    1)
        echo ""
        echo "运行协议验证测试..."
        python3 test_protocol.py
        ;;
    2)
        echo ""
        echo "启动 OpenAI 兼容代理..."
        python3 proxy.py
        ;;
    3)
        echo ""
        read -p "用户名: " username
        read -s -p "密码: " password
        echo ""
        MONKEYCODE_USERNAME="$username" MONKEYCODE_PASSWORD="$password" python3 -c "
from auth import MonkeyCodeAuth
auth = MonkeyCodeAuth()
result = auth.login_with_password()
if result['success']:
    print(f'Session Cookie: {auth.session_cookie}')
    print('请将此 Cookie 设置为环境变量 MONKEYCODE_SESSION_COOKIE')
else:
    print(f'登录失败: {result}')
"
        ;;
    *)
        echo "无效选择"
        exit 1
        ;;
esac

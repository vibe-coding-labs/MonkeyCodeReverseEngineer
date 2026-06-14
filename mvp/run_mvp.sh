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
echo "  1) 运行协议验证测试 (test_protocol.py)"
echo "  2) 启动 OpenAI 兼容代理 (旧版 mock)"
echo "  3) 交互式登录获取 Session Cookie"
echo "  4) 启动真实代理 (proxy_real.py，端口 9091)"
echo "  5) 端到端完整链路验证 (verify_full_flow.py)"
echo "  6) 仅测试认证和模型 (verify_full_flow.py --skip-task)"
echo ""
read -p "请选择 (1/2/3/4/5/6): " choice

case $choice in
    1)
        echo ""
        echo "运行协议验证测试..."
        python3 test_protocol.py
        ;;
    2)
        echo ""
        echo "启动 OpenAI 兼容代理 (旧版 mock)..."
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
    4)
        echo ""
        echo "启动真实 OpenAI 兼容代理 (端口 9091)..."
        python3 proxy_real.py
        ;;
    5)
        echo ""
        echo "运行端到端完整链路验证..."
        python3 verify_full_flow.py
        ;;
    6)
        echo ""
        echo "运行认证和模型测试 (跳过任务创建)..."
        python3 verify_full_flow.py --skip-task
        ;;
    *)
        echo "无效选择"
        exit 1
        ;;
esac

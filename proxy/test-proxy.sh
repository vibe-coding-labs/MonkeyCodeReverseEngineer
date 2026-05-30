#!/bin/bash
# MonkeyCode Reverse Proxy 测试脚本
#
# 测试项:
# 1. 健康检查
# 2. 模型列表
# 3. Chat Completions API (流式/非流式)
# 4. Responses API (流式)
# 5. 多轮对话支持
#
# 用法:
#   ./test-proxy.sh [BASE_URL]
#
# 示例:
#   ./test-proxy.sh http://localhost:9090

set -e

BASE_URL="${1:-http://localhost:9090}"
PASS=0
FAIL=0

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试函数
test_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    PASS=$((PASS + 1))
}

test_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    if [ -n "$2" ]; then
        echo -e "   ${YELLOW}详情${NC}: $2"
    fi
    FAIL=$((FAIL + 1))
}

echo "=========================================="
echo "  MonkeyCode Reverse Proxy 测试"
echo "  目标: $BASE_URL"
echo "=========================================="
echo ""

# ========== 测试 1: 健康检查 ==========
echo "📋 测试 1: 健康检查"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/health" 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)

if [ "$HTTP_CODE" = "200" ]; then
    STATUS=$(echo "$BODY" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    if [ "$STATUS" = "ok" ]; then
        test_pass "健康检查端点正常"
    else
        test_fail "健康检查返回异常状态" "$STATUS"
    fi
else
    test_fail "健康检查端点不可达" "HTTP $HTTP_CODE"
fi

# ========== 测试 2: 模型列表 ==========
echo ""
echo "📋 测试 2: 模型列表"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/v1/models" 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)

if [ "$HTTP_CODE" = "200" ]; then
    OBJECT=$(echo "$BODY" | grep -o '"object":"[^"]*"' | cut -d'"' -f4)
    if [ "$OBJECT" = "list" ]; then
        MODEL_COUNT=$(echo "$BODY" | grep -o '"id"' | wc -l)
        test_pass "模型列表端点正常 ($MODEL_COUNT 个模型)"
    else
        test_fail "模型列表返回异常格式" "$OBJECT"
    fi
else
    test_fail "模型列表端点不可达" "HTTP $HTTP_CODE"
fi

# ========== 测试 3: Chat Completions (非流式) ==========
echo ""
echo "📋 测试 3: Chat Completions (非流式)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "monkeycode/OpenAI/gpt-4o",
        "messages": [{"role": "user", "content": "Say hello in one word"}],
        "stream": false
    }' 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -1)

if [ "$HTTP_CODE" = "200" ]; then
    OBJECT=$(echo "$BODY" | grep -o '"object":"[^"]*"' | cut -d'"' -f4)
    if [ "$OBJECT" = "chat.completion" ]; then
        CONTENT=$(echo "$BODY" | grep -o '"content":"[^"]*"' | head -1 | cut -d'"' -f4)
        if [ -n "$CONTENT" ]; then
            test_pass "Chat Completions (非流式) 正常: $CONTENT"
        else
            test_fail "Chat Completions (非流式) 返回空内容" ""
        fi
    else
        test_fail "Chat Completions (非流式) 返回异常格式" "$OBJECT"
    fi
else
    test_fail "Chat Completions (非流式) 端点不可达" "HTTP $HTTP_CODE"
fi

# ========== 测试 4: Chat Completions (流式) ==========
echo ""
echo "📋 测试 4: Chat Completions (流式)"
STREAM_RESPONSE=$(curl -s -X POST "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "monkeycode/OpenAI/gpt-4o",
        "messages": [{"role": "user", "content": "Say hi"}],
        "stream": true
    }' 2>/dev/null | head -5)

if echo "$STREAM_RESPONSE" | grep -q "data:"; then
    test_pass "Chat Completions (流式) 正常"
else
    test_fail "Chat Completions (流式) 返回异常" "$STREAM_RESPONSE"
fi

# ========== 测试 5: Responses API (流式) ==========
echo ""
echo "📋 测试 5: Responses API (流式)"
STREAM_RESPONSE=$(curl -s -X POST "$BASE_URL/v1/responses" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "monkeycode/OpenAI/gpt-4o",
        "input": [{"role": "user", "content": "Say hello"}],
        "stream": true
    }' 2>/dev/null | head -5)

if echo "$STREAM_RESPONSE" | grep -q "event:"; then
    test_pass "Responses API (流式) 正常"
else
    test_fail "Responses API (流式) 返回异常" "$STREAM_RESPONSE"
fi

# ========== 测试 6: 多轮对话 ==========
echo ""
echo "📋 测试 6: 多轮对话支持"

# 第一轮对话
RESPONSE1=$(curl -s -D - -X POST "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "monkeycode/OpenAI/gpt-4o",
        "messages": [{"role": "user", "content": "Remember the number 42"}],
        "stream": false
    }' 2>/dev/null)

# 提取 conversation_id
CONV_ID=$(echo "$RESPONSE1" | grep -i "x-conversation-id:" | awk '{print $2}' | tr -d '\r')

if [ -n "$CONV_ID" ]; then
    test_pass "多轮对话 - 第一轮创建成功 (ID: $CONV_ID)"

    # 第二轮对话 (复用)
    RESPONSE2=$(curl -s -X POST "$BASE_URL/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"monkeycode/OpenAI/gpt-4o\",
            \"messages\": [{\"role\": \"user\", \"content\": \"What number did I ask you to remember?\"}],
            \"conversation_id\": \"$CONV_ID\",
            \"stream\": false
        }" 2>/dev/null)

    if echo "$RESPONSE2" | grep -q "42"; then
        test_pass "多轮对话 - 第二轮上下文保持正确"
    else
        test_fail "多轮对话 - 第二轮上下文丢失" ""
    fi
else
    test_fail "多轮对话 - 未返回 conversation_id" ""
fi

# ========== 测试 7: 错误处理 ==========
echo ""
echo "📋 测试 7: 错误处理"

# 无效模型
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "invalid-model",
        "messages": [{"role": "user", "content": "test"}],
        "stream": false
    }' 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)

if [ "$HTTP_CODE" = "404" ]; then
    test_pass "错误处理 - 无效模型返回 404"
else
    test_fail "错误处理 - 无效模型返回异常" "HTTP $HTTP_CODE"
fi

# 空消息
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "monkeycode/OpenAI/gpt-4o",
        "messages": [],
        "stream": false
    }' 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)

if [ "$HTTP_CODE" = "400" ]; then
    test_pass "错误处理 - 空消息返回 400"
else
    test_fail "错误处理 - 空消息返回异常" "HTTP $HTTP_CODE"
fi

# ========== 测试结果汇总 ==========
echo ""
echo "=========================================="
echo "  测试结果汇总"
echo "=========================================="
echo -e "  ${GREEN}通过${NC}: $PASS"
echo -e "  ${RED}失败${NC}: $FAIL"
echo -e "  总计: $((PASS + FAIL))"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}🎉 所有测试通过！${NC}"
    exit 0
else
    echo -e "${RED}⚠️  有 $FAIL 个测试失败${NC}"
    exit 1
fi

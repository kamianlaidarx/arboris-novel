# AIMETA P=模型发现端到端验证脚本|R=真实后端+模拟第三方服务联调|NR=不含单元测试|E=e2e_model_discovery|X=internal|A=可执行脚本|D=httpx,http.server|S=net,db|RD=./README.ai
"""端到端验证：真实后端 + 模拟的第三方 OpenAI 兼容服务。

与单元测试不同，这里会：

1. 用 ``http.server`` 起一个模拟的第三方中转站（要求 Bearer 鉴权，提供 /v1/models）；
2. 用 uvicorn 启动**真实的** FastAPI 应用（SQLite 数据库、真实鉴权、真实路由）；
3. 通过 HTTP 走完「登录 -> 保存配置 -> 自动获取模型列表 -> 缓存 -> 错误路径」全流程。

运行方式::

    cd backend
    ../.venv/bin/python tests/e2e_model_discovery.py

脚本以退出码表示结果：0 表示全部通过。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]

VALID_KEY = "sk-e2e-valid-key"
MODELS = [
    {"id": "e2e-chat-pro", "owned_by": "e2e"},
    {"id": "e2e-reasoner-v2", "owned_by": "e2e"},
    {"id": "e2e-vision-max", "owned_by": "e2e"},
    {"id": "e2e-embedding-large", "owned_by": "e2e"},
    {"id": "e2e-reranker-v1", "owned_by": "e2e"},
    {"id": "e2e-image-gen", "owned_by": "e2e"},
]

_checks: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    _checks.append((name, bool(condition), detail))
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --------------------------------------------------------------- 模拟第三方服务


class MockUpstreamHandler(BaseHTTPRequestHandler):
    """模拟一个 OpenAI 兼容中转站。

    只有携带正确 Bearer Token 的 ``GET /v1/models`` 才返回模型列表；
    其余路径返回 404，用于验证候选端点回退逻辑。
    """

    protocol_version = "HTTP/1.1"
    request_count = 0

    def log_message(self, *args):  # noqa: D102 - 静默处理
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
        MockUpstreamHandler.request_count += 1

        if self.path != "/v1/models":
            self._send(404, {"error": {"message": f"no route for {self.path}"}})
            return

        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {VALID_KEY}":
            self._send(401, {"error": {"message": "invalid api key"}})
            return

        self._send(200, {"object": "list", "data": MODELS})


def start_mock_upstream(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), MockUpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ------------------------------------------------------------------- 后端进程


def start_backend(port: int, db_path: Path, log_path: Path) -> tuple[subprocess.Popen, object]:
    env = {
        **os.environ,
        "SECRET_KEY": "e2e-secret-key-0123456789",
        "DB_PROVIDER": "sqlite",
        "SQLITE_DB_PATH": str(db_path),
        "ALLOW_PRIVATE_LLM_ENDPOINTS": "true",  # 模拟服务在 127.0.0.1 上
        "ADMIN_DEFAULT_USERNAME": "e2eadmin",
        "ADMIN_DEFAULT_PASSWORD": "E2ePassword123!",
        "ADMIN_DEFAULT_EMAIL": "e2e@example.com",
        "LOGGING_LEVEL": "WARNING",
        # debug=True 会让 SQLAlchemy 把每条 SQL 都打到 stdout，这里关掉
        "DEBUG": "false",
        "LLM_MODEL_CACHE_TTL": "300",
        "LLM_MODEL_REQUEST_TIMEOUT": "10",
    }
    # 去掉代理设置：本验证全程走 127.0.0.1。两点原因：
    # 1) 部分环境下 ALL_PROXY=socks5://... 会让 httpx 因缺少 socksio 直接报错；
    # 2) NO_PROXY 里含 "[::1]" 这类条目会让 httpx 的 URL 解析抛 ValueError。
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        env.pop(key, None)

    # 输出重定向到文件而不是 PIPE：若用 PIPE 且不持续读取，
    # 子进程会在缓冲区写满后阻塞，导致 uvicorn 永远无法完成启动。
    log_file = log_path.open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return process, log_file


def wait_for_health(client: httpx.Client, timeout: float = 90.0) -> tuple[bool, str]:
    """轮询健康检查端点，返回 ``(是否就绪, 最后一次错误说明)``。"""

    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            response = client.get("/health", timeout=3.0)
            if response.status_code == 200:
                return True, ""
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:  # noqa: BLE001 - 诊断用，需捕获全部异常
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    return False, last_error


# ------------------------------------------------------------------------ 主流程


def main() -> int:
    upstream_port = free_port()
    backend_port = free_port()
    db_path = Path("/tmp/arboris_e2e_model_discovery.db")
    log_path = Path("/tmp/arboris_e2e_backend.log")
    db_path.unlink(missing_ok=True)
    log_path.unlink(missing_ok=True)

    upstream = start_mock_upstream(upstream_port)
    print(f"模拟第三方服务: http://127.0.0.1:{upstream_port}/v1")
    print(f"被测后端:       http://127.0.0.1:{backend_port}")

    backend, backend_log = start_backend(backend_port, db_path, log_path)
    base_url = f"http://127.0.0.1:{backend_port}"

    try:
        with httpx.Client(base_url=base_url, timeout=30.0, trust_env=False) as client:
            healthy, health_error = wait_for_health(client)
            if not healthy:
                print(f"后端启动失败：健康检查始终未通过（{health_error}）")
                print(f"进程输出（{log_path}）如下：")
                backend_log.flush()
                print(log_path.read_text(encoding="utf-8", errors="ignore")[-3000:])
                return 1
            check("后端启动并通过健康检查", True)

            # ---- 登录 ----
            response = client.post(
                "/api/auth/token",
                data={"username": "e2eadmin", "password": "E2ePassword123!"},
            )
            check("管理员登录成功", response.status_code == 200, f"HTTP {response.status_code}")
            if response.status_code != 200:
                return 1
            token = response.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # ---- 供应商预设 ----
            response = client.get("/api/llm-config/providers", headers=headers)
            presets = {item["id"]: item for item in response.json()}
            check(
                "供应商预设接口可用",
                response.status_code == 200 and "deepseek" in presets and len(presets) >= 15,
                f"{len(presets)} 个预设",
            )

            response = client.get(
                "/api/llm-config/provider",
                params={"base_url": "https://api.deepseek.com/v1"},
                headers=headers,
            )
            check(
                "按地址识别供应商正确",
                response.json().get("id") == "deepseek",
                f"识别为 {response.json().get('id')}",
            )

            # ---- 未配置任何凭证时应当返回可读错误 ----
            response = client.post("/api/llm-config/models", json={}, headers=headers)
            detail = response.json().get("detail", {})
            check(
                "未提供凭证时返回 400 + 可操作提示",
                response.status_code == 400 and detail.get("error") == "InvalidCredentialsError",
                f"HTTP {response.status_code} / {detail.get('error')}",
            )

            # ---- 保存自定义配置 ----
            upstream_base = f"http://127.0.0.1:{upstream_port}/v1"
            response = client.put(
                "/api/llm-config",
                json={
                    "llm_provider_url": upstream_base,
                    "llm_provider_api_key": VALID_KEY,
                },
                headers=headers,
            )
            check("保存自定义 LLM 配置", response.status_code == 200, f"HTTP {response.status_code}")

            # ---- 自动获取模型列表（回退到已保存配置，不重复传 Key）----
            response = client.post("/api/llm-config/models", json={"refresh": True}, headers=headers)
            check("自动获取模型列表成功", response.status_code == 200, f"HTTP {response.status_code}")
            if response.status_code != 200:
                print(json.dumps(response.json(), ensure_ascii=False, indent=2))
                return 1

            payload = response.json()
            ids = payload["model_ids"]
            check(
                "返回全部 6 个模型",
                len(ids) == len(MODELS) and set(ids) == {item["id"] for item in MODELS},
                f"{len(ids)} 个",
            )
            check(
                "命中真实端点 /v1/models",
                payload["endpoint"] == f"{upstream_base}/models",
                payload["endpoint"] or "",
            )
            check(
                "能力标签分类正确",
                payload["capability_counts"].get("chat", 0) >= 2
                and payload["capability_counts"].get("embedding") == 1
                and payload["capability_counts"].get("rerank") == 1
                and payload["capability_counts"].get("image") == 1,
                json.dumps(payload["capability_counts"], ensure_ascii=False),
            )
            check("首次请求未命中缓存", payload["cached"] is False)

            # ---- 缓存命中 ----
            before = MockUpstreamHandler.request_count
            response = client.post("/api/llm-config/models", json={}, headers=headers)
            cached_payload = response.json()
            check(
                "第二次请求命中缓存且未再打第三方",
                cached_payload["cached"] is True
                and MockUpstreamHandler.request_count == before
                and cached_payload["expires_in"] > 0,
                f"cached={cached_payload['cached']} expires_in={cached_payload['expires_in']}s",
            )

            # ---- 强制刷新绕过缓存 ----
            response = client.post("/api/llm-config/models", json={"refresh": True}, headers=headers)
            check(
                "强制刷新绕过缓存",
                response.json()["cached"] is False
                and MockUpstreamHandler.request_count > before,
                f"upstream 请求数 {before} -> {MockUpstreamHandler.request_count}",
            )

            # ---- 能力过滤 ----
            response = client.post(
                "/api/llm-config/models",
                json={"capabilities": ["embedding"], "refresh": True},
                headers=headers,
            )
            check(
                "按能力过滤只返回向量模型",
                response.json()["model_ids"] == ["e2e-embedding-large"],
                str(response.json()["model_ids"]),
            )

            # ---- 错误路径：Key 无效 ----
            response = client.post(
                "/api/llm-config/models",
                json={
                    "llm_provider_url": upstream_base,
                    "llm_provider_api_key": "sk-wrong-key",
                    "refresh": True,
                },
                headers=headers,
            )
            detail = response.json().get("detail", {})
            check(
                "无效 Key 返回 401 且带排查建议",
                response.status_code == 401
                and detail.get("error") == "ProviderAuthError"
                and bool(detail.get("hint")),
                f"HTTP {response.status_code} / {detail.get('hint', '')[:40]}",
            )

            # ---- 错误路径：不支持模型列表的中转站 ----
            response = client.post(
                "/api/llm-config/models",
                json={
                    "llm_provider_url": "https://relay-that-has-no-models.invalid",
                    "llm_provider_api_key": VALID_KEY,
                    "refresh": True,
                },
                headers=headers,
            )
            detail = response.json().get("detail", {})
            check(
                "无法连接的地址返回 504 而不是空列表",
                response.status_code == 504 and detail.get("error") == "ProviderUnreachableError",
                f"HTTP {response.status_code} / {detail.get('error')}",
            )

            # ---- 错误路径：内网地址（本例已放开，验证开关生效的反面）----
            response = client.post(
                "/api/llm-config/models",
                json={
                    "llm_provider_url": f"http://127.0.0.1:{upstream_port}/v1",
                    "llm_provider_api_key": VALID_KEY,
                    "refresh": True,
                },
                headers=headers,
            )
            check(
                "放开开关后允许访问内网自建网关",
                response.status_code == 200 and len(response.json()["model_ids"]) == len(MODELS),
                f"HTTP {response.status_code}",
            )

            # ---- 旧签名兼容方法 ----
            response = client.get("/api/llm-config", headers=headers)
            body = response.json()
            check(
                "配置回读保持为字符串地址（无 HttpUrl 序列化问题）",
                body["llm_provider_url"] == upstream_base,
                str(body.get("llm_provider_url")),
            )
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=10)
        except subprocess.TimeoutExpired:
            backend.kill()
        backend_log.close()
        upstream.shutdown()
        db_path.unlink(missing_ok=True)

    failed = [item for item in _checks if not item[1]]
    print()
    print(f"共 {len(_checks)} 项检查，通过 {len(_checks) - len(failed)} 项，失败 {len(failed)} 项")
    for name, _, detail in failed:
        print(f"  FAILED: {name} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

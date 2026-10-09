# AIMETA P=纯页面配置验证脚本|R=无env密钥下的页面配置流程|NR=不含docker|E=e2e_page_config|X=internal|A=可执行脚本|D=httpx,uvicorn|S=net,db|RD=./README.ai
"""验证「完全不配 env 里的 API Key，仅通过页面配置」是否可行。

模拟一个真实用户的最小部署：

1. 环境里**不提供** OPENAI_API_KEY / OPENAI_MODEL_NAME 等任何 LLM 变量；
2. 启动后端，确认服务正常起得来（不会因缺 Key 崩溃）；
3. 管理员登录，确认后台「系统配置」里能看到/写入 llm.* 配置项；
4. 通过管理端接口写入 llm.api_key / llm.base_url / llm.model，再读回确认生效；
5. 确认普通用户在个人设置里配置自己的 Key 的通道也可用（LLM 配置 CRUD）。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_backend(port: int, db_path: Path, log_path: Path) -> tuple[subprocess.Popen, object]:
    # 关键：这里刻意不设置任何 OPENAI_* / EMBEDDING_* 变量
    env = {
        **os.environ,
        "SECRET_KEY": "page-config-secret-0123456789",
        "DB_PROVIDER": "sqlite",
        "SQLITE_DB_PATH": str(db_path),
        "ADMIN_DEFAULT_USERNAME": "pageadmin",
        "ADMIN_DEFAULT_PASSWORD": "PagePassword123!",
        "ADMIN_DEFAULT_EMAIL": "page@example.com",
        "ENVIRONMENT": "production",
        "DEBUG": "false",
        "LOGGING_LEVEL": "WARNING",
    }
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_API_BASE_URL",
        "OPENAI_MODEL_NAME",
        "EMBEDDING_API_KEY",
        "EMBEDDING_BASE_URL",
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
        "NO_PROXY", "no_proxy",
    ):
        env.pop(key, None)

    log_file = log_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(BACKEND_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return process, log_file


def wait_health(client: httpx.Client, timeout: float = 90.0) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            response = client.get("/health", timeout=3.0)
            if response.status_code == 200:
                return True, ""
            last = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    return False, last


def main() -> int:
    port = free_port()
    db_path = Path("/tmp/arboris_page_config.db")
    log_path = Path("/tmp/arboris_page_config.log")
    db_path.unlink(missing_ok=True)
    log_path.unlink(missing_ok=True)

    backend, log_file = start_backend(port, db_path, log_path)
    base = f"http://127.0.0.1:{port}"

    try:
        with httpx.Client(base_url=base, timeout=30.0, trust_env=False) as client:
            ok, err = wait_health(client)
            if not ok:
                print(f"后端启动失败（{err}），日志：")
                log_file.flush()
                print(log_path.read_text(encoding="utf-8", errors="ignore")[-2500:])
                return 1
            check("未配置任何 LLM 环境变量时后端仍能正常启动", True)

            response = client.post("/api/auth/token",
                                   data={"username": "pageadmin", "password": "PagePassword123!"})
            check("管理员登录成功", response.status_code == 200, f"HTTP {response.status_code}")
            if response.status_code != 200:
                return 1
            headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

            # ---- 登录页/设置页需要的公开选项 ----
            options = client.get("/api/auth/options")
            check("登录页可用（/api/auth/options 正常）", options.status_code == 200)

            # ---- 管理端系统配置：确认 llm.* 可通过页面读写 ----
            response = client.get("/api/admin/system-configs", headers=headers)
            check("管理员可读取系统配置列表", response.status_code == 200, f"HTTP {response.status_code}")
            configs = {item["key"]: item for item in response.json()}
            check(
                "未提供 env 时 llm.api_key 不在初始配置中（符合预期）",
                "llm.api_key" not in configs,
                f"当前 llm.* 键: {sorted(k for k in configs if k.startswith('llm.'))}",
            )

            # 模拟管理员在页面上新增/修改 LLM 配置。
            # 注意：管理端的 PUT /system-configs/{key} 需要 body 里同时带 key
            # （前端 AdminAPI.upsertSystemConfig 就是发 { key, value, description }）。
            for key, value in (
                ("llm.api_key", "sk-set-from-admin-page"),
                ("llm.base_url", "https://api.deepseek.com/v1"),
                ("llm.model", "deepseek-chat"),
            ):
                put = client.put(
                    f"/api/admin/system-configs/{key}",
                    json={"key": key, "value": value, "description": "页面配置"},
                    headers=headers,
                )
                if put.status_code not in (200, 201):
                    check(f"写入 {key}", False, f"HTTP {put.status_code} {put.text[:160]}")
                    break
            else:
                check("管理员可在页面上写入 llm.api_key / llm.base_url / llm.model", True)

            response = client.get("/api/admin/system-configs", headers=headers)
            after = {item["key"]: item["value"] for item in response.json()}
            check(
                "写入的 LLM 配置可被读回（页面配置生效）",
                after.get("llm.model") == "deepseek-chat"
                and after.get("llm.base_url") == "https://api.deepseek.com/v1"
                and after.get("llm.api_key") == "sk-set-from-admin-page",
                f"model={after.get('llm.model')} base_url={after.get('llm.base_url')}",
            )

            # ---- 个人设置：普通用户自配 Key ----
            response = client.put(
                "/api/llm-config",
                json={
                    "llm_provider_url": "api.siliconflow.cn/v1",
                    "llm_provider_api_key": "sk-user-own-key",
                    "llm_provider_model": "deepseek-ai/DeepSeek-V3",
                },
                headers=headers,
            )
            check("用户可在「个人设置」保存自己的 LLM 配置", response.status_code == 200,
                  f"HTTP {response.status_code}")
            body = response.json()
            check(
                "地址被自动归一化（api.siliconflow.cn/v1 -> https://…）",
                body.get("llm_provider_url") == "https://api.siliconflow.cn/v1",
                str(body.get("llm_provider_url")),
            )

            # ---- 新增的供应商标识与模型发现接口，在部署环境下可用 ----
            response = client.get("/api/llm-config/providers", headers=headers)
            check("供应商预设接口可用", response.status_code == 200 and len(response.json()) >= 15,
                  f"{len(response.json())} 个预设")

            response = client.get("/api/llm-config/provider",
                                  params={"base_url": "https://api.siliconflow.cn/v1"},
                                  headers=headers)
            check("地址识别接口可用", response.json().get("id") == "siliconflow",
                  str(response.json().get("id")))

            # 默认策略：内网地址应被拦截（部署到容器后 Ollama 场景需要开关）
            response = client.post("/api/llm-config/models",
                                   json={"llm_provider_url": "http://host.docker.internal:11434",
                                         "llm_provider_api_key": "x"},
                                   headers=headers)
            detail = response.json().get("detail", {})
            check(
                "默认拦截内网地址，且给出开启开关的提示",
                response.status_code == 403
                and detail.get("error") == "LocalEndpointBlockedError"
                and "ALLOW_PRIVATE_LLM_ENDPOINTS" in (detail.get("hint") or ""),
                f"HTTP {response.status_code}",
            )

            # ---- 健康检查端点（docker healthcheck 依赖）----
            for path in ("/health", "/api/health"):
                r = client.get(path)
                check(f"healthcheck 路径 {path} 可用", r.status_code == 200)
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=10)
        except subprocess.TimeoutExpired:
            backend.kill()
        log_file.close()
        db_path.unlink(missing_ok=True)

    failed = [c for c in _checks if not c[1]]
    print()
    print(f"共 {len(_checks)} 项检查，通过 {len(_checks) - len(failed)} 项，失败 {len(failed)} 项")
    for name, _, detail in failed:
        print(f"  FAILED: {name} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

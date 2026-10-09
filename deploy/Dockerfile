# ============================================
# 第一阶段：构建前端静态资源
# ============================================
FROM node:20-slim AS frontend-builder

# npm 源可覆盖：默认官方源；国内加速设 NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY="https://registry.npmjs.org"

WORKDIR /frontend

RUN npm config set registry "${NPM_REGISTRY}"

# 复制前端依赖文件
COPY frontend/package*.json ./

# 只用 npm ci：它按 package-lock.json 做可复现安装。
# 这里原本同时有 `npm install` 和 `npm ci`，后者会在前者装好之后
# 删掉 node_modules 重装，纯属浪费一层构建时间（且 npm ci 要求干净状态）。
RUN npm ci --prefer-offline --no-audit

# 复制前端源码
COPY frontend/ ./

# 构建前端
RUN npm run build

# ============================================
# 第二阶段：构建最终镜像（后端 + nginx）
# ============================================
FROM python:3.11-slim

# apt / pip 镜像源可覆盖。
# 默认走官方源：第三方镜像虽然快，但会因限流、地域策略或中间代理返回 403，
# 表现为「索引能下、.deb 全部 403 Forbidden」，构建直接失败。
# 需要加速时在 deploy/.env 里设置（docker compose build 会自动读取）：
#   APT_MIRROR=mirrors.aliyun.com
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG APT_MIRROR=""
ARG PIP_INDEX_URL="https://pypi.org/simple"

WORKDIR /app

# 可选：替换 Debian 源。用 shell 判断而不是 sed 硬替换，避免镜像里
# debian.sources 格式变化时静默改错。
RUN if [ -n "${APT_MIRROR}" ]; then \
        echo "==> 使用 apt 镜像: ${APT_MIRROR}"; \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" \
            /etc/apt/sources.list.d/debian.sources; \
        cat /etc/apt/sources.list.d/debian.sources; \
    else \
        echo "==> 使用 Debian 官方源"; \
    fi

# 安装系统依赖：nginx、supervisor、curl、mysql客户端等。
# 注意这里用 `;` 而不是 `&&` 连接两次 update：
# 写成 `apt-get update || (sleep 5 && apt-get update) && apt-get install ...`
# 会解析成 `A || ((B) && C)`，一旦第一次 update 成功，install 反而不会执行。
RUN apt-get update \
        || { echo "apt-get update 失败，5 秒后重试"; sleep 5; apt-get update; } \
    ; apt-get install -y --no-install-recommends \
        gcc \
        default-libmysqlclient-dev \
        pkg-config \
        nginx \
        supervisor \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 配置 pip 镜像源
RUN pip config set global.index-url "${PIP_INDEX_URL}"

# 复制后端依赖文件
COPY backend/requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端应用代码
COPY backend/ ./

# 清理可能被带入的 SQLite 数据文件，确保首次启动时根据环境变量初始化管理员密码
RUN rm -rf /app/storage && mkdir -p /app/storage

# 从前端构建阶段复制静态资源到 nginx 默认目录
COPY --from=frontend-builder /frontend/dist /usr/share/nginx/html

# 复制部署配置
COPY deploy/nginx.conf /etc/nginx/sites-available/default
COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY deploy/docker-entrypoint.sh /app/docker-entrypoint.sh

# 允许入口脚本在启动时修正宿主机挂载目录权限
RUN chmod +x /app/docker-entrypoint.sh

# 创建非 root 用户（供 supervisor 使用）
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# 暴露端口（nginx 80端口）
EXPOSE 80

# 使用 supervisor 启动 nginx 和 uvicorn
# 注意：容器以 root 启动，supervisor 会根据配置降权运行各个进程
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

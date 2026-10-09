# AIMETA P=测试配置_环境准备|R=环境变量注入|NR=不含测试用例|E=conftest|X=internal|A=pytest配置|D=pytest|S=none|RD=./README.ai
"""pytest 全局配置：在导入应用模块前准备好必需的环境变量。"""

import os
import sys
from pathlib import Path

# 让测试可以直接 import app.*
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Settings 要求 SECRET_KEY 必填；测试使用固定值，避免依赖外部 .env
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-model-discovery")
os.environ.setdefault("DB_PROVIDER", "sqlite")
os.environ.setdefault("LOGGING_LEVEL", "WARNING")

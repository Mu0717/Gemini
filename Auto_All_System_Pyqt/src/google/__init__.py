"""
@file __init__.py
@brief 谷歌业务模块包
@details 包含谷歌账号自动化相关的前端和后端模块
         使用 pkgutil.extend_path 使本地 google 包与 pip 安装的 google 命名空间包共存
"""

# 关键：使用 pkgutil.extend_path 扩展命名空间，解决与 pip google 包的冲突
import pkgutil
__path__ = pkgutil.extend_path(__path__, __name__)

from . import backend
from . import frontend

__all__ = ['backend', 'frontend']

"""
配置文件加载工具

支持功能：
1. YAML 配置文件加载
2. 环境变量替换（${VAR_NAME} 格式）
"""

import os
import yaml
from typing import Any, Dict
from pathlib import Path
from loguru import logger as log


def _process_env_variables(config: Any) -> Any:
    """
    递归处理配置中的环境变量替换
    
    支持格式：${VAR_NAME} 或 ${VAR_NAME:default_value}
    
    Args:
        config: 配置数据（可以是 dict、list、str 等）
        
    Returns:
        处理后的配置数据
    """
    if isinstance(config, dict):
        return {key: _process_env_variables(value) for key, value in config.items()}
    elif isinstance(config, list):
        return [_process_env_variables(item) for item in config]
    elif isinstance(config, str):
        # 支持 ${VAR_NAME} 格式
        if config.startswith("${") and config.endswith("}"):
            env_expr = config[2:-1]  # 去掉 ${ 和 }
            
            # 支持默认值：${VAR_NAME:default_value}
            if ':' in env_expr:
                env_var, default_value = env_expr.split(':', 1)
                return os.getenv(env_var.strip(), default_value.strip())
            else:
                env_value = os.getenv(env_expr)
                if env_value is None:
                    log.warning(f"环境变量 {env_expr} 未设置，使用原始值: {config}")
                    return config
                return env_value
        
        return config
    else:
        return config


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
        
    Raises:
        FileNotFoundError: 配置文件不存在
        yaml.YAMLError: YAML 解析错误
    """
    config_file = Path(f"config/{config_path}")
    
    if not config_file.exists():
        raise FileNotFoundError(f"配置文件未找到: {config_file}")
    
    try:
        with open(config_file, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file) or {}
        
        # 处理环境变量替换
        config = _process_env_variables(config)
        
        log.info(f"✅ 配置文件加载成功: {config_file}")
        return config
        
    except yaml.YAMLError as e:
        log.error(f"❌ YAML 配置文件解析错误: {e}")
        raise
    except Exception as e:
        log.error(f"❌ 加载配置文件时发生错误: {e}")
        raise


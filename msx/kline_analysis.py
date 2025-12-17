"""
K线数据分析工具

提供基于线性回归的K线斜率计算和方向判断功能
"""

import traceback
from typing import Optional, Tuple
from loguru import logger as log
import pandas as pd
import numpy as np
from scipy import stats


def calculate_direction(
    df: pd.DataFrame,
    threshold: float = 0.0001,
    min_klines: int = 60,
    close_column: str = "close",
    current_direction: Optional[str] = None
) -> Tuple[float, str, Optional[str]]:
    """
    根据K线DataFrame使用线性回归计算斜率，并返回多空方向
    
    Args:
        df: K线数据DataFrame，必须包含收盘价列（默认为 'close'）
            支持列名：'close' 或 'c'
        threshold: 斜率阈值，绝对值小于此值视为横盘（默认 0.0001，即 0.01%）
        min_klines: 最少需要的K线数量（默认 10）
        close_column: 收盘价列名，默认为 'close'，如果不存在则尝试 'c'
        current_direction: 当前方向，当斜率在阈值范围内时保持此方向（可选）
                          如果为 None，横盘时默认返回 "long"
    
    Returns:
        Tuple[float, str, Optional[str]]:
            - slope: 归一化斜率值（正数表示上升，负数表示下降）
            - direction: 方向 "long"（做多）或 "short"（做空）
            - error: 错误信息，如果计算成功则为 None
    
    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     'close': [100.0, 101.0, 102.0, 103.0, 104.0],
        ...     'timestamp': [1000, 2000, 3000, 4000, 5000]
        ... })
        >>> slope, direction, error = calculate_direction(df, min_klines=5)
        >>> print(f"斜率: {slope:.6f}, 方向: {direction}")
        斜率: 0.009901, 方向: long
        
        >>> # 横盘时保持原方向
        >>> df_sideways = pd.DataFrame({'close': [100.0, 100.1, 99.9, 100.0, 100.05]})
        >>> slope, direction, error = calculate_direction(df_sideways, current_direction="short", min_klines=5)
        >>> print(f"斜率: {slope:.6f}, 方向: {direction}")  # 方向保持为 "short"
    """
    try:
        # 检查输入数据
        if df is None or df.empty:
            return current_direction
        
        if len(df) < min_klines:
            return current_direction
        
        # 确定收盘价列名（支持 'close' 或 'c'）
        if close_column not in df.columns:
            if 'c' in df.columns:
                close_column = 'c'
            elif 'close' in df.columns:
                close_column = 'close'
            else:
                return current_direction
        
        # 提取收盘价序列，过滤无效值，只取最后 min_klines 条数据
        closes = df[close_column].dropna()
    
        
        # 只取最后 min_klines 条数据（最新的K线数据）
        if len(closes) > min_klines:
            closes = closes.tail(min_klines)
        
        if len(closes) < min_klines:
            return current_direction
        
        # 使用 scipy.stats.linregress 进行线性回归
        # 创建时间索引（0, 1, 2, ..., n-1）
        x = np.arange(len(closes))
        y = closes.values
        
        # 使用 scipy 的线性回归函数
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
        
        # 计算归一化斜率（相对斜率，消除价格绝对值影响）
        y_mean = y.mean()
        normalized_slope = slope / y_mean if y_mean > 0 else 0.0
        
        # 根据斜率判断方向
        if normalized_slope > threshold:
            direction = "long"  # 上升趋势，做多
        elif normalized_slope < -threshold:
            direction = "short"  # 下降趋势，做空
        else:
            # 横盘，保持原方向（如果没有原方向则默认做多）
            direction = current_direction if current_direction in ("long", "short") else "long"
        
        log.debug(
            f"斜率计算完成: 原始斜率={slope:.6f}, "
            f"归一化斜率={normalized_slope:.6f}, "
            f"方向={direction}, "
            f"K线数量={len(closes)}, "
            f"价格范围=[{closes.min():.2f}, {closes.max():.2f}]"
        )
        
        return direction
        
    except Exception as e:
        error_msg = f"计算斜率时发生错误: {str(e)}"
        log.error(error_msg)
        log.error(traceback.format_exc())
        return  current_direction


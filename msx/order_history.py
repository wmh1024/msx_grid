"""
历史订单记录类

功能：
1. 从交易所获取历史订单（通过原始API获取完整数据）
2. 过滤出已成交的订单
3. 按策略名称和日期保存到CSV文件
4. 支持增量更新（避免重复记录）
"""

from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger as log
import pandas as pd


class OrderHistoryRecorder:
    """
    历史订单记录器
    
    功能：
    - 初始化时指定策略名称
    - 每天一个CSV记录文件
    - 从交易所获取历史订单，过滤出已成交的订单
    - 支持增量更新，避免重复记录
    - 包含开平仓信息
    
    使用示例：
        recorder = OrderHistoryRecorder(
            strategy_name="wash_volume",
            exchange=exchange,
            data_dir="data"
        )
        await recorder.record_orders(symbol="NVDA")
    """
    
    def __init__(
        self,
        strategy_name: str,
        data_dir: str = "data",
    ):
        """
        初始化历史订单记录器
        
        Args:
            strategy_name: 策略名称，用于文件命名
            exchange: 交易所实例，用于获取历史订单
            data_dir: 数据保存目录，默认为 "data"
        """
        if not strategy_name or not strategy_name.strip():
            raise ValueError("策略名称不能为空")
        
        self.strategy_name = strategy_name.strip()
        self.data_dir = Path(data_dir)
        self.data=None
        # 确保数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        log.info(f"历史订单记录器初始化: 策略={self.strategy_name}, 数据目录={self.data_dir}")
    
    def _get_today_file_path(self) -> Path:
        """
        获取今天的订单记录文件路径
        
        Returns:
            文件路径，格式：{data_dir}/{strategy_name}_orders_{YYYY-MM-DD}.csv
        """
        today = datetime.now().strftime("%Y-%m-%d")
        filename = f"{self.strategy_name}_orders_{today}.csv"
        return self.data_dir / filename
    
    def _get_date_from_timestamp(self, timestamp: int) -> str:
        """
        从时间戳（毫秒）提取日期字符串
        
        Args:
            timestamp: 毫秒级时间戳
        
        Returns:
            日期字符串，格式：YYYY-MM-DD
        """
        try:
            dt = datetime.fromtimestamp(timestamp / 1000.0)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError) as e:
            log.warning(f"时间戳转换失败: {timestamp}, 错误: {e}")
            return datetime.now().strftime("%Y-%m-%d")
    
    def update_order_history(self, orders: List[Dict]) -> None:
        """
        更新订单历史记录
        
        Args:
            orders: 订单列表（字典格式，已转换为CSV行格式）
        """
        if not orders:
            return
        
        file_path = self._get_today_file_path()
        
        # 加载已有订单数据
        existing_df = self._load_existing_orders(file_path)
        
        # 获取最大时间戳（用于过滤新订单）
        # 如果文件不存在或为空，使用当天0点0分的时间戳（毫秒）
        if not existing_df.empty and 'timestamp' in existing_df.columns:
            max_timestamp = existing_df['timestamp'].max()
        else:
            # 获取当天0点0分的时间戳（毫秒）
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            max_timestamp = int(today.timestamp() * 1000)
        
        # 过滤出新订单（时间戳大于最大时间戳）
        new_orders = [
            order for order in orders
            if int(order.timestamp) > max_timestamp and order.status in ["filled", "executed"]
        ]
        
        if not new_orders:
          #  log.debug(f"无新订单需要更新")
            return
        
        # 转换为 DataFrame
        new_df = pd.DataFrame(new_orders)
        
        # 合并到已有数据
        if existing_df.empty:
            combined_df = new_df
        else:
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        
        # 按时间戳重新排序（从旧到新）
        if 'timestamp' in combined_df.columns:
            combined_df = combined_df.sort_values('timestamp', ascending=True)
        
        # 保存整个 DataFrame 到 CSV（覆盖模式）
        try:
            combined_df.to_csv(file_path, index=False, encoding='utf-8-sig')
            log.info(f"更新订单历史: 新增 {len(new_orders)} 条订单，总计 {len(combined_df)} 条")
        except Exception as e:
            log.error(f"保存订单失败: {file_path}, 错误: {e}")
            raise
    
    def _load_existing_orders(self, file_path: Path) -> pd.DataFrame:
        """
        加载已存在的订单数据（使用 pandas）
        
        Args:
            file_path: 文件路径
        
        Returns:
            DataFrame，如果文件不存在则返回空 DataFrame
        """
        if not file_path.exists():
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            # 确保 timestamp 是数值类型
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce').fillna(0).astype(int)
            return df
        except Exception as e:
            log.warning(f"读取已有订单数据失败: {file_path}, 错误: {e}")
            return pd.DataFrame()
    
   
    def get_today_file_path(self) -> Path:
        """
        获取今天的订单记录文件路径（公共方法）
        
        Returns:
            文件路径
        """
        return self._get_today_file_path()
    
    def get_today(self) -> Dict:
        """
        获取今天的订单记录
        """
        msg={
            "total_volume":0.0,
            "realized_pnl":0.0,
            "total_fee":0.0,
            "ratio_value":0.0,
        }
        file_path = self._get_today_file_path()
        if file_path.exists():
            existing_df = self._load_existing_orders(file_path)
            msg["total_volume"]=existing_df["amount"].sum()
            msg["realized_pnl"]=existing_df["pnl"].sum()
            msg["total_fee"]=existing_df["fee"].sum()
            msg["ratio_value"]=(msg["total_fee"]-msg["realized_pnl"])/msg["total_volume"]
            return msg
        else:
            return None
  


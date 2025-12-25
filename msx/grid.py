"""
简单网格策略框架

功能：
1. 同时只挂一个买单和一个卖单
2. 订单成交后自动重新挂单
3. 使用百分比网格间距
4. 持仓总金额限制
"""

# 版本号管理
# 规则：每次修改代码时，将版本号最后一位数字增加1
# 例如：1.0.1 -> 1.0.2, 1.0.9 -> 1.0.10, 1.9.9 -> 1.9.10
VERSION = "1.1.0"  # 支持多 symbol 管理

# from tkinter import NO  # 未使用的导入，已注释
from ast import List
import asyncio
import traceback
from typing import Dict, Optional, Any
from loguru import logger as log
from .exchange import MsxExchange
from .models import OrderInfo, Position
from datetime import datetime, timedelta
import requests
from pytz import timezone
import csv
import os
import json
from pathlib import Path


class GridStrategy:
    """
    简单网格策略
    
    参数：
        exchange: MsxExchange 实例
        redis: Redis 实例（可选，用于数据持久化）
    """
    
    def __init__(
        self,
        exchange: MsxExchange,
        redis=None,
    ):
        self.exchange = exchange # 交易所实例
        self.redis = redis  # Redis 实例（可选，用于数据持久化）
        
        # 多 symbol 策略数据字典，key 为 symbol，value 为策略数据字典
        self.symbols: Dict[str, Dict[str, Any]] = {}
        
        # 全局运行任务引用（用于管理主循环）
        self._run_task: Optional[asyncio.Task] = None
        
        # 交易状态缓存（用于美股交易时段判断，所有 symbol 共享）
        self._trading_status_cache = {
            "is_trade": None,  # 当前交易状态
            "start_trade_time": None,  # 下次交易开始时间（时间戳）
            "last_update_time": None,  # 上次更新时间（时间戳）
        }
        
        # 以下字段已迁移到 self.symbols[symbol] 中，保留注释以便参考
        # self.symbol: Optional[str] = None  # 交易币种
        # self.min_price: Optional[float] = None  # 最低价格
        # self.max_price: Optional[float] = None  # 最高价格
        # self.direction: Optional[str] = None  # "long" 或 "short"
        # self.grid_spacing: Optional[float] = None  # 网格间距，0.01 表示 1%
        # self.investment_amount: Optional[float] = None  # 投入资金
        # self.leverage: Optional[float] = None  # 杠杆倍数
        # self.total_capital: Optional[float] = None  # 总资金 = 投入资金 * 杠杆倍数
        # self.asset_type: Optional[str] = None  # 资产类型："crypto"（加密货币）或 "stock"（股票）
        # self.market_type: Optional[str] = None  # 市场类型："spot"（现货）或 "contract"（合约）
        # self.co_type: Optional[int] = None  # 合约类型（根据 asset_type 和 market_type 计算）
        # self.current_price: Optional[float] = None  # 当前价格
        # self.start_price: Optional[float] = None  # 启动价格
        # self.buy_order = None  # 买单
        # self.sell_order = None  # 卖单
        # self.position = Position()  # 持仓
        # self.his_order = []  # 历史订单
        # self._status = False  # 运行状态
        # self._initialized = False  # 初始化状态
        # self.last_filled_time = 0  # 最后成交时间戳
        # self.stats = {...}  # 统计信息
        
        log.info("网格策略实例已创建（支持多 symbol 管理）")
        # 启动主循环协程（run 方法中会先加载策略，然后进入主循环）
        self._run_task = asyncio.create_task(self.run())
    
    def _create_symbol_data(self) -> Dict[str, Any]:
        """
        创建新 symbol 的初始数据结构模板
        
        Returns:
            Dict[str, Any]: 包含所有必需字段的初始策略数据字典
        """
        return {
            # 基础参数
            "symbol": None,                    # 交易对
            "min_price": None,                 # 最低价格
            "max_price": None,                 # 最高价格
            "direction": None,                 # "long" 或 "short"
            "grid_spacing": None,               # 网格间距，0.01 表示 1%
            "investment_amount": None,          # 投入资金
            "leverage": None,                   # 杠杆倍数
            "total_capital": None,              # 总资金 = 投入资金 * 杠杆倍数
            "asset_type": None,                # 资产类型："crypto"（加密货币）或 "stock"（股票）
            "market_type": None,               # 市场类型："spot"（现货）或 "contract"（合约）
            "co_type": None,                   # 合约类型（根据 asset_type 和 market_type 计算）
            
            # 价格信息
            "current_price": None,             # 当前价格
            "start_price": None,               # 启动价格
            
            # 订单信息
            "buy_order": None,                  # 买单（OrderInfo 对象）
            "sell_order": None,                # 卖单（OrderInfo 对象）
            
            # 持仓信息
            "position": Position(),             # 持仓对象
            
            # 历史订单
            "his_order": [],                   # 历史订单列表
            
            # 状态标志
            "_status": False,                  # 运行状态
            "_initialized": False,             # 初始化状态
            "_run_task": None,                  # 运行任务（如果需要独立任务）
            
            # 统计信息
            "stats": {
                "buy_filled_count": 0,         # 买单成交次数
                "sell_filled_count": 0,        # 卖单成交次数
                "complete_cycles": 0,           # 完整周期（一买一卖）
                "realized_pnl": 0.0,           # 已实现盈亏
                "total_fees": 0.0,             # 总手续费
                "initial_balance": 0.0,        # 初始余额
                "start_time": None,            # 开始时间
                "total_trade_amount": 0.0,     # 累计成交金额
                "invited": "",                 # 邀请码
                "co_type": None,               # 合约类型
            },
            
            # 其他
            "last_filled_time": 0,             # 最后成交时间戳
            "each_order_size": None,            # 每单持仓数量
            "min_order_size": 10,               # 最小订单金额
        }
    
    def _fetch_trading_status_from_api(self) -> Optional[Dict[str, Any]]:
        """
        从API获取交易状态
        
        使用API接口：https://api9528mystks.mystonks.org/api/v1/stock/isTrade
        
        Returns:
            Optional[Dict[str, Any]]: 
                - 成功时返回 {"is_trade": bool, "start_trade_time": int, "code": 0}
                - code为6005（休市中）时返回 {"code": 6005}
                - 失败时返回 None
        """
        try:
            api_url = "https://api9528mystks.mystonks.org/api/v1/stock/isTrade"
            response = requests.get(api_url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                api_code = data.get("code")
                
                # 检查是否为休市中（code: 6005）
                if api_code == 6005:
                    log.info(f"市场休市中: {data.get('msg', 'unknown')}")
                    return {"code": 6005}
                
                # 检查API返回格式（正常情况 code == 0）
                if data.get("success") and api_code == 0:
                    trade_data = data.get("data", {})
                    is_trade = trade_data.get("isTrade", False)
                    start_trade_time = trade_data.get("startTradeTime")
                    
                    return {
                        "is_trade": is_trade,
                        "start_trade_time": start_trade_time,
                        "code": 0
                    }
                else:
                    log.warning(f"API返回异常: code={api_code}, msg={data.get('msg', 'unknown')}")
                    return None
            else:
                log.warning(f"API请求失败，状态码: {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            log.warning(f"API请求异常: {e}")
            return None
        except Exception as e:
            log.error(f"获取交易状态失败: {e}")
            return None
    
    def is_us_stock_trading_hours(self) -> bool:
        """
        判断当前是否在美股交易时段
        
        注意：此方法用于检查美股交易时段，所有 symbol 共享同一个交易状态缓存
        调用此方法前，应该已经确认是股票合约（co_type == 1）
        
        使用API接口获取交易状态：https://api9528mystks.mystonks.org/api/v1/stock/isTrade
        使用缓存机制，在未超过startTradeTime之前不重复请求API
        
        Returns:
            bool: True 表示在交易时段内，False 表示不在交易时段
        """
        # 注意：此方法不再检查 co_type，因为调用者应该在调用前已经检查
        # 所有 symbol 共享同一个交易状态缓存
        
        try:
            current_time = int(datetime.now().timestamp())
            
            # 检查缓存是否有效（当前时间未超过startTradeTime）
            if (self._trading_status_cache.get("is_trade") is not None and 
                self._trading_status_cache.get("start_trade_time") is not None and
                current_time < self._trading_status_cache["last_update_time"]):
                return self._trading_status_cache["is_trade"]
            
            # 需要重新请求API
            api_result = self._fetch_trading_status_from_api()
            
            if api_result:
        
                # 正常返回数据
                is_trade = api_result.get("is_trade", False)
                start_trade_time = api_result.get("start_trade_time")
                
                # 更新缓存
                self._trading_status_cache["is_trade"] = is_trade
                self._trading_status_cache["start_trade_time"] = start_trade_time
                # 设置last_update_time为当前时间+1小时（3600秒）
                if is_trade:
                    self._trading_status_cache["last_update_time"] = current_time + 3600
                else:
                    self._trading_status_cache["last_update_time"] = start_trade_time 
                
                log.debug(f"交易状态已更新: isTrade={is_trade}, startTradeTime={start_trade_time}")
                return is_trade
            else:
                # API请求失败时，如果有缓存，使用缓存；否则回退到简单的时间检查
                if self._trading_status_cache.get("is_trade") is not None:
                    return self._trading_status_cache["is_trade"]
                return self._fallback_trading_hours_check()
           
        except Exception as e:
            log.error(f"判断美股交易时段失败: {e}")
            # 出错时，如果有缓存，使用缓存；否则默认返回 True，避免阻止交易
            if self._trading_status_cache["is_trade"] is not None:
                return self._trading_status_cache["is_trade"]
            return True
    
    def _fallback_trading_hours_check(self) -> bool:
        """
        回退方案：使用简单的时间检查（仅检查周末和交易时间）
        
        Returns:
            bool: True 表示在交易时段内，False 表示不在交易时段
        """
        try:
            # 获取美东时区（自动处理夏令时）
            eastern = timezone('US/Eastern')
            # 获取当前美东时间
            now_eastern = datetime.now(eastern)
            
            # 检查是否为工作日（周一到周五，weekday() 返回 0-4）
            if now_eastern.weekday() >= 5:  # 5=周六，6=周日
                return False
            
            # 检查时间是否在 9:30 AM - 4:00 PM 之间
            current_time = now_eastern.time()
            market_open = datetime.strptime("09:30", "%H:%M").time()
            market_close = datetime.strptime("16:00", "%H:%M").time()
            
            return market_open <= current_time <= market_close
        except Exception as e:
            log.error(f"回退时间检查失败: {e}")
            # 出错时默认返回 True，避免阻止交易
            return True
    
    async def _init_(self, symbol: str) -> None:
        """
        初始化持仓和订单（支持多 symbol）
        
        参数：
            symbol: 交易对符号
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return
        
        symbol_data = self.symbols[symbol]
        
        log.info(f"网格策略初始化: {symbol}, 方向={symbol_data['direction']}, "
                f"价格范围=[{symbol_data['min_price']}, {symbol_data['max_price']}], "
                f"网格间距={symbol_data['grid_spacing']*100}%, 持仓总金额={symbol_data['investment_amount']}")
        
        # 注意：交易时段判断已在 run 方法中完成，这里直接执行初始化逻辑
        # ========== 步骤1: 清理历史挂单 ==========
        # 注意：fetch_orders 可能返回 None，这里需要做空值保护
        orders = await self.exchange.fetch_orders(symbol)
        log.info(
            f"初始化持仓: {symbol}, size={symbol_data['position'].size}, "
            f"amount={symbol_data['position'].amount}"
        )
        if not orders:
            # 没有挂单或获取失败时，直接跳过撤单逻辑，避免 NoneType 异常
            log.info(f"撤消所有挂单: {symbol}, 0（无挂单或获取失败）")
        else:
            log.info(f"撤消所有挂单: {symbol}, {len(orders)}")
            for order in orders:
                try:
                    log.info(f"撤消挂单: {symbol}, {order.id}")
                    await self.exchange.cancel_order(order.id)
                except Exception as e:
                    log.error(f"撤消挂单失败: {symbol}, order_id={getattr(order, 'id', None)}, error={e}")
            log.info(f"撤消所有挂单完成: {symbol}")

        # ========== 步骤2: 获取价格和持仓信息 ==========
        ticker = await self.exchange.fetch_ticker(symbol)
        if ticker:
            last_price = ticker.get("last")
            if last_price is not None:
                symbol_data["current_price"] = last_price
        
        # 如果通过行情未能获取到当前价格，初始化阶段不允许跳过，
        # 使用配置的价格区间中位数作为回退方案，确保后续逻辑可以继续。
        if symbol_data.get("current_price") is None:
            min_cfg = symbol_data.get("min_price")
            max_cfg = symbol_data.get("max_price")
            if min_cfg is not None and max_cfg is not None and max_cfg > min_cfg:
                fallback_price = (min_cfg + max_cfg) / 2
                symbol_data["current_price"] = fallback_price
                log.warning(
                    f"无法从行情获取当前价格，使用价格区间中位数作为回退: "
                    f"{symbol}, 区间=[{min_cfg}, {max_cfg}], 中位数={fallback_price}"
                )
            else:
                raise ValueError(f"初始化阶段无法获取当前价格且价格区间无效: {symbol}")

        # 记录启动价格（仅首次）
        if symbol_data["start_price"] is None:
            symbol_data["start_price"] = symbol_data["current_price"]
            log.info(f"策略启动价格已记录: {symbol}, {symbol_data['start_price']}")
        
        positions = await self.exchange.fetch_positions(symbol)
        has_position = False
        if positions and len(positions) > 0:
            pos = positions[0]
            symbol_data["position"] = pos
            has_position = pos.size > 0
        
        # ========== 步骤3: 处理建仓逻辑 ==========
        position_built = False
        if has_position:
            # 已有持仓，无需建仓
            position_built = True
            log.info(f"检测到已有持仓，跳过建仓操作: {symbol}")
        else:
            log.info(f"开始执行初始建仓操作: {symbol}")
            await self._initial_build_position(symbol)
            position_built = True
            log.info(f"初始建仓完成: {symbol}")
            # 持久化策略信息
            await self._persist_strategy_info(symbol)
            
        # ========== 步骤4: 计算每单持仓数量 ==========
        total_capital = symbol_data["total_capital"]
        if total_capital is None or total_capital <= 0:
            raise ValueError(f"总资金未正确初始化: {symbol}, {total_capital}")
        min_price = symbol_data["min_price"]
        max_price = symbol_data["max_price"]
        grid_spacing = symbol_data["grid_spacing"]
        avg_price = (min_price + max_price) / 2
        price_range = max_price - min_price
        if price_range > 0 and avg_price > 0:
            each_order_size = total_capital * grid_spacing / price_range
        else:
            each_order_size = 0
        symbol_data["each_order_size"] = each_order_size
        
        min_order_size = symbol_data.get("min_order_size", 10)
        if each_order_size * min_price < min_order_size:
            raise ValueError(f"每单持仓金额小于最小订单金额，无法建仓，请调整参数: {symbol}")
        log.info(f"每单持仓数量: {symbol}, {each_order_size:.4f} (平均价格={avg_price:.2f}, 价格范围={price_range:.2f}, 网格间距={grid_spacing*100:.2f}%)")
        
        # ========== 步骤5: 初始化历史订单时间戳 ==========
        his_order = await self.exchange.fetch_his_order(symbol)
        if his_order:
            filled_orders = [o for o in his_order if o.status in ["filled", "executed"] and o.timestamp]
            if filled_orders:
                max_timestamp = max(o.timestamp for o in filled_orders)
                symbol_data["last_filled_time"] = max_timestamp
                log.info(f"初始化 last_filled_time: {symbol}, {symbol_data['last_filled_time']} (最新已成交订单时间戳)")
            else:
                symbol_data["last_filled_time"] = 0
                log.info(f"初始化 last_filled_time: {symbol}, 0 (无已成交订单)")
        else:
            symbol_data["last_filled_time"] = 0
            log.info(f"初始化 last_filled_time: {symbol}, 0 (无历史订单)")
        
        # ========== 步骤6: 处理网格订单创建逻辑 ==========
        # 初始化阶段不允许跳过网格订单创建，如果仍然无法得到价格则抛出异常
        current_price = symbol_data.get("current_price")
        if current_price is None:
            raise ValueError(f"初始化阶段当前价格为空，无法创建网格订单: {symbol}")
        elif each_order_size <= 0:
            log.warning(f"每单持仓数量为 0，跳过网格订单创建: {symbol}")
        else:
            log.info(f"开始创建网格订单: {symbol}")
            await self._place_grid_orders(symbol, current_price, each_order_size)
            await asyncio.sleep(2)
            log.info(f"网格订单创建完成: {symbol}")
    
        # ========== 步骤7: 统一设置初始化状态 ==========
        # 只有在建仓成功且创建网格订单成功时，才标记为已完成初始化
        if position_built:
            symbol_data["_initialized"] = True
            log.info(f"初始化完成：建仓和创建网格订单均已完成: {symbol}")
            await self._persist_strategy_info(symbol)
        else:
            symbol_data["_initialized"] = False
            log.warning(f"初始化未完成：建仓失败: {symbol}")
        
    async def run(self) -> None:
        """
        运行策略主循环（支持多 symbol）
        
        流程：
        1. 等待交易所认证成功
        2. 加载策略（从文件加载已保存的策略）
        3. 进入主循环：
           - 遍历所有运行中的策略
           - 对于股票策略，检查是否在交易时段
           - 执行初始化（如果需要）
           - 执行订单检查和处理
        """
        try:
            # ========== 步骤1: 等待交易所认证成功 ==========
            log.info("等待交易所认证成功...")
            while not self.exchange.auth_status:
                await asyncio.sleep(1)
            await asyncio.sleep(2)  # 等待认证稳定
            log.info("交易所认证成功，开始加载策略")
            
            # ========== 步骤2: 加载策略（从文件加载已保存的策略） ==========
            await self.load_strategy()
            log.info("策略加载完成，进入主循环")
            
            # ========== 步骤3: 设置所有运行中策略的统计信息开始时间 ==========
            for symbol, symbol_data in self.symbols.items():
                if symbol_data.get("_status", False) and symbol_data["stats"].get("start_time") is None:
                    symbol_data["stats"]["start_time"] = datetime.now()
            
            # ========== 步骤4: 主循环：只要有运行中的策略就继续 ==========
            while True:
                # 遍历所有 symbol
                for symbol in list(self.symbols.keys()):
                    symbol_data = self.symbols[symbol]
                    
                    # 跳过未运行的策略
                    if symbol_data.get("_status"):
                        
                    
                        try:
                            # ========== 步骤4.1: 检查交易时段状态（如果是股票） ==========
                            co_type = symbol_data.get("co_type")
                            is_trading = True  # 默认可以交易（加密货币或现货）
                            
                            if co_type == 1:  # 股票合约，需要检查交易时段
                                is_trading = self.is_us_stock_trading_hours()
                            
                            if is_trading:
                                # ========== 步骤4.2: 在交易时段，执行初始化（如果需要） ==========
                                if not symbol_data.get("_initialized", False):
                                    log.info(f"策略 {symbol} 未初始化，开始初始化...")
                                    await self._init_(symbol)
                                
                                # ========== 步骤4.3: 在交易时段，执行正常的交易检查 ==========
                                await self.check_order(symbol)
                           # else:
                                # ========== 步骤4.4: 不在交易时段，跳过交易操作 ==========
                                # 休市时不需要执行任何操作，只需等待
                             #  log.debug(f"策略 {symbol} 不在交易时段，跳过交易操作")
                        
                        except Exception as e:
                            # 某个 symbol 出错不应影响其他 symbol
                            log.error(f"处理 {symbol} 策略时出错: {e}")
                            log.error(traceback.format_exc())
                            # 继续处理下一个 symbol
                            
                
                # ========== 步骤5: 无论是否在交易时段，都需要休眠以避免阻塞事件循环 ==========
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            log.info("主循环被取消")
            raise
        except Exception as e:
            log.error(f"主循环异常退出: {e}")
            log.error(traceback.format_exc())
        finally:
            # 循环退出时，记录日志
            running_count = sum(1 for s in self.symbols.values() if s.get("_status", False))
            if running_count == 0:
                log.info("所有网格策略运行循环已退出")
            else:
                log.info(f"网格策略运行循环已退出，仍有 {running_count} 个策略在运行")


    async def check_order(self, symbol: str) -> None:
        """
        检查订单状态并处理成交订单（支持多 symbol）
        
        参数：
            symbol: 交易对符号
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return
        
        symbol_data = self.symbols[symbol]
        
        # 更新价格
        ticker = await self.exchange.fetch_ticker(symbol)
        if ticker:
            symbol_data["current_price"] = ticker.get("last")
        
        # 先更新持仓信息（无论是否有历史订单，都需要更新持仓）
        try:
            positions = await self.exchange.fetch_positions(symbol)
            if positions and len(positions) > 0:
                pos = positions[0]  # fetch_positions 已经按 symbol 过滤，取第一个
                # 更新持仓信息
                symbol_data["position"].id = pos.id
                symbol_data["position"].size = pos.size
                symbol_data["position"].amount = pos.amount
                symbol_data["position"].entryPrice = pos.entryPrice
                symbol_data["position"].unrealizedPnl = pos.unrealizedPnl
                symbol_data["position"].side = pos.side
                symbol_data["position"].liquidationPrice = pos.liquidationPrice
                symbol_data["position"].timestamp = pos.timestamp
        except Exception as e:
            log.error(f"更新持仓信息失败: {symbol}, {e}")
            log.error(traceback.format_exc())
        
        orders = await self.exchange.fetch_orders(symbol)
        if orders is None:
            log.error(f"获取订单失败: {symbol}")
            return
        
        # 检查订单是否已成交（订单ID不在当前订单列表中表示已成交）
        order_ids = {o.id for o in orders if o.id}
        buy_order = symbol_data.get("buy_order")
        sell_order = symbol_data.get("sell_order")
        buy_filled = buy_order is not None and buy_order.id not in order_ids if buy_order else False
        sell_filled = sell_order is not None and sell_order.id not in order_ids if sell_order else False
        
        # 根据成交情况处理
        if buy_filled and sell_filled:
            # 两个订单都成交，使用历史订单价格重新挂单
            his_orders = await self.exchange.fetch_his_order(symbol)
            if his_orders:
                last_order = his_orders[0]
                await self._place_grid_orders(symbol, last_order.price, last_order.volume)
        elif buy_filled and buy_order:
            # 买单成交，取消卖单并重新挂单
            if sell_order and sell_order.id:
                await self.exchange.cancel_order(sell_order.id)
            await self._place_grid_orders(symbol, buy_order.price, buy_order.volume)
        elif sell_filled and sell_order:
            # 卖单成交，取消买单并重新挂单
            if buy_order and buy_order.id:
                await self.exchange.cancel_order(buy_order.id)
            await self._place_grid_orders(symbol, sell_order.price, sell_order.volume)
        
        await self.process_order_statistics(symbol)


    
    # 以下方法已废弃：当前设计每个 symbol 只有一个买单和一个卖单，不再需要此方法
    # async def _cancel_extra_orders(self) -> None:
    #     """
    #     撤销多余订单，防止占用资金
    #     
    #     逻辑：
    #     1. 买单列表：只保留价格最高的一个档位（相同价格的订单），其余撤单
    #     2. 卖单列表：只保留价格最低的一个档位（相同价格的订单），其余撤单
    #     """
    #     pass  # 已废弃

    async def process_order_statistics(self, symbol: str) -> None:
        """
        处理订单统计：记录已成交订单并缓存到 symbol_data["his_order"]，用于后续统计计算。（支持多 symbol）
        
        参数：
            symbol: 交易对符号
        
        当前实现（占位版本）：
        - 从交易所获取历史订单
        - 过滤出「新成交」订单（timestamp 大于 last_filled_time）
        - 将简化后的成交记录追加到 symbol_data["his_order"] 列表
        - 更新 last_filled_time，避免重复统计
        
        后续可以基于 symbol_data["his_order"] 计算：
        - 总盈亏 / 网格收益
        - 网格次数 / 完整周期数
        - 年化收益等
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return
        
        symbol_data = self.symbols[symbol]
        
        try:
            his_orders = await self.exchange.fetch_his_order(symbol)
        except Exception as e:
            log.error(f"获取历史订单失败: {symbol}, {e}")
            log.error(traceback.format_exc())
            return

        if not his_orders:
            return

        # 只保留成交状态且时间戳存在的订单
        filled_orders = [
            o for o in his_orders
            if getattr(o, "status", None) in ["filled", "executed"] and getattr(o, "timestamp", None)
        ]
        if not filled_orders:
            return

        # 只处理「新」成交订单（时间戳大于 last_filled_time）
        last_filled_time = symbol_data.get("last_filled_time", 0)
        new_filled = [o for o in filled_orders if o.timestamp > last_filled_time]
        if not new_filled:
            return

        # 按时间排序，方便后续统计
        new_filled.sort(key=lambda o: o.timestamp)

        # 将成交记录转换为简化结构并缓存到 self.his_order
        his_order = symbol_data["his_order"]
        position = symbol_data["position"]
        
        for o in new_filled:
            # 确定持仓ID：
            # 1. 优先从当前持仓获取 pos_id
            # 2. 如果持仓为空，则从平仓订单中获取 pos_id
            pos_id = None
            if position.id:  # 优先使用当前持仓ID
                pos_id = position.id
            elif o.open_type == 2 and o.posId:  # 持仓为空时，从平仓订单中获取
                pos_id = o.posId
            elif o.posId:  # 如果订单中包含posId，也使用
                pos_id = o.posId
            
            record = {
                "order_id": getattr(o, "id", ""),
                "symbol": getattr(o, "symbol", symbol),
                "side": getattr(o, "side", None),            # 买/卖
                "type": getattr(o, "type", None),            # 开仓/平仓等
                "open_type": getattr(o, "open_type", 1),     # 开仓类型，1=开仓，2=平仓
                "price": float(getattr(o, "price", 0.0) or 0.0),
                "volume": float(getattr(o, "volume", 0.0) or 0.0),
                "pnl": float(getattr(o, "pnl", 0.0) or 0.0),  # 单笔盈亏（如果有）
                "fee": float(getattr(o, "fee", 0.0) or 0.0),
                "timestamp": o.timestamp,
                "status": o.status,
                "pos_id": pos_id,  # 持仓ID
                "avg_price": float(getattr(o, "avgPrice", 0.0) or 0.0),  # 成交均价
            }
            his_order.append(record)
            
            # 持久化到CSV文件
            if pos_id:
                self._persist_order_to_csv(symbol, record, pos_id)
            else:
                log.warning(f"订单 {record['order_id']} 无法确定持仓ID，跳过CSV持久化: {symbol}")

        # 更新 last_filled_time，避免重复处理
        if his_order:
            max_ts = max(o["timestamp"] for o in his_order if o.get("timestamp"))
            symbol_data["last_filled_time"] = max(last_filled_time, max_ts)

    def _load_orders_from_csv(self, symbol: str, pos_id: int) -> tuple[list[dict[str, Any]], int]:
        """
        从CSV文件加载历史订单记录（支持多 symbol）
        
        参数：
            symbol: 交易对符号
            pos_id: 持仓ID
        
        文件命名：{pos_id}_orders.csv
        存储位置：项目根目录的 data/orders/ 目录
        
        返回：
            tuple[list[dict], int]: (订单记录列表, 最大时间戳)
        """
        records = []
        max_timestamp = 0
        
        try:
            # 确定存储目录
            base_dir = Path(__file__).resolve().parent.parent
            orders_dir = base_dir / "data" / "orders"
            
            if not orders_dir.exists():
                log.debug(f"订单目录不存在，无法加载历史订单: {symbol}, pos_id={pos_id}")
                return records, max_timestamp
            
            # 确定文件名
            filename = f"{pos_id}_orders.csv"
            filepath = orders_dir / filename
            
            if not filepath.exists():
                log.debug(f"历史订单文件不存在: {filepath}，跳过加载: {symbol}")
                return records, max_timestamp
            
            # 读取CSV文件
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    try:
                        # 解析订单记录
                        record = {
                            "order_id": row.get("order_id", ""),
                            "symbol": row.get("symbol", symbol),
                            "side": row.get("side", ""),
                            "open_type": int(row.get("open_type", 1)),
                            "price": float(row.get("price", 0.0) or 0.0),
                            "volume": float(row.get("volume", 0.0) or 0.0),
                            "pnl": float(row.get("pnl", 0.0) or 0.0),
                            "fee": float(row.get("fee", 0.0) or 0.0),
                            "timestamp": int(row.get("timestamp", 0) or 0),
                            "status": row.get("status", ""),
                            "pos_id": int(row.get("pos_id", pos_id) or pos_id),
                            "avg_price": float(row.get("avg_price", 0.0) or 0.0),
                        }
                        
                        # 验证记录有效性
                        if record["timestamp"] > 0:
                            records.append(record)
                            # 更新最大时间戳
                            if record["timestamp"] > max_timestamp:
                                max_timestamp = record["timestamp"]
                    except (ValueError, TypeError) as e:
                        log.warning(f"解析CSV订单记录失败，跳过: {symbol}, row={row}, error={e}")
                        continue
            
            # 按时间戳排序（确保顺序正确）
            records.sort(key=lambda o: o.get("timestamp", 0))
            
            if len(records) > 0:
                log.info(f"从CSV加载历史订单: {symbol}, pos_id={pos_id}, 加载了 {len(records)} 条记录，max_timestamp={max_timestamp}")
            else:
                log.debug(f"CSV文件中无有效订单记录: {symbol}, pos_id={pos_id}")
            
        except Exception as e:
            log.error(f"从CSV加载历史订单失败: {symbol}, pos_id={pos_id}, {e}")
            log.error(traceback.format_exc())
        
        return records, max_timestamp
    
    def _persist_order_to_csv(self, symbol: str, order_record: dict, pos_id: int) -> None:
        """
        将订单记录持久化到CSV文件（支持多 symbol）
        
        参数：
            symbol: 交易对符号
            order_record: 订单记录字典
            pos_id: 持仓ID
        
        文件命名：{pos_id}_orders.csv
        存储位置：项目根目录的 data/orders/ 目录
        """
        try:
            # 确定存储目录
            base_dir = Path(__file__).resolve().parent.parent
            orders_dir = base_dir / "data" / "orders"
            orders_dir.mkdir(parents=True, exist_ok=True)
            
            # 确定文件名
            filename = f"{pos_id}_orders.csv"
            filepath = orders_dir / filename
            
            # CSV列名
            fieldnames = [
                "order_id", "symbol", "side", "open_type", "price", "volume",
                "pnl", "fee", "timestamp", "status", "pos_id", "avg_price"
            ]
            
            # 判断文件是否存在，决定是否写入表头
            file_exists = filepath.exists()
            
            # 过滤 order_record，只保留 fieldnames 中定义的字段
            filtered_record = {k: v for k, v in order_record.items() if k in fieldnames}
            
            # 追加写入CSV文件
            with open(filepath, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                # 如果文件不存在，写入表头
                if not file_exists:
                    writer.writeheader()
                
                # 写入订单记录（只包含 fieldnames 中定义的字段）
                writer.writerow(filtered_record)
            
            log.debug(f"订单 {order_record['order_id']} 已持久化到 {filepath}")
            
        except Exception as e:
            log.error(f"持久化订单到CSV失败: {e}")
            log.error(traceback.format_exc())

    async def _persist_strategy_info(self, symbol: str) -> None:
        """
        将策略参数持久化到JSON文件（支持多 symbol）
        
        参数：
            symbol: 交易对符号
        
        文件命名：{pos_id}.json
        存储位置：项目根目录的 data/ 目录
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return
        
        symbol_data = self.symbols[symbol]
        
        try:
            # 获取持仓ID
            pos_id = None
            position = symbol_data.get("position", Position())
            if position and position.id:
                pos_id = position.id
            else:
                # 尝试从持仓中获取
                positions = await self.exchange.fetch_positions(symbol)
                if positions and len(positions) > 0:
                    pos = positions[0]
                    if pos.id:
                        pos_id = pos.id
                        position.id = pos.id
            
            if not pos_id:
                log.warning(f"无法获取持仓ID，跳过策略信息持久化: {symbol}")
                return
            
            # 确定存储目录
            base_dir = Path(__file__).resolve().parent.parent
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            
            # 确定文件名
            filename = f"{pos_id}.json"
            filepath = data_dir / filename
            if not filepath.exists():
                # 构建策略参数字典
                strategy_info = {
                    "pos_id": pos_id,
                    "symbol": symbol,
                    "min_price": symbol_data.get("min_price"),
                    "max_price": symbol_data.get("max_price"),
                    "direction": symbol_data.get("direction"),
                    "grid_spacing": symbol_data.get("grid_spacing"),
                    "investment_amount": symbol_data.get("investment_amount"),
                    "leverage": symbol_data.get("leverage"),
                    "total_capital": symbol_data.get("total_capital"),
                    "asset_type": symbol_data.get("asset_type"),
                    "market_type": symbol_data.get("market_type"),
                    "co_type": symbol_data.get("co_type"),
                    "start_price": symbol_data.get("start_price"),
                    "each_order_size": symbol_data.get("each_order_size"),
                    "last_filled_time": symbol_data.get("last_filled_time", 0),
                    "saved_at": datetime.now().isoformat(),
                }
                
                # 写入JSON文件
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(strategy_info, f, indent=2, ensure_ascii=False)
                
                log.info(f"策略信息已持久化到 {filepath}: {symbol}")
            
        except Exception as e:
            log.error(f"持久化策略信息失败: {e}")
            log.error(traceback.format_exc())

    async def load_strategy(self) -> int:
        """
        从策略文件中加载所有策略参数（支持多 symbol）
        
        流程：
        1. 获取所有持仓（从交易所）
        2. 遍历持仓，根据 pos_id 查找对应的策略文件 {pos_id}.json
        3. 如果策略文件存在，加载并添加到 self.symbols
        4. 自动启动所有加载的策略（设置 _status = True）
        
        注意：此方法不再负责启动主循环，主循环已在 __init__ 中通过 run() 方法启动
        
        Returns:
            int: 成功加载的策略数量
        """
        try:
            # ========== 步骤1: 获取所有持仓 ==========
            all_positions = await self.exchange.fetch_positions()
            if not all_positions:
                log.info("未找到任何持仓，无法加载策略")
                return 0
            
            # 过滤出有持仓的记录（size > 0）
            valid_positions = [pos for pos in all_positions if pos.id and pos.size > 0]
            if not valid_positions:
                log.info("未找到有效持仓（size > 0），无法加载策略")
                return 0
            
            log.info(f"找到 {len(valid_positions)} 个有效持仓，开始加载策略")
            
            # ========== 步骤2: 确定策略文件目录 ==========
            base_dir = Path(__file__).resolve().parent.parent
            data_dir = base_dir / "data"
            
            if not data_dir.exists():
                log.info("data 目录不存在，无法加载策略")
                return 0
            
            # ========== 步骤3: 遍历持仓，加载对应的策略文件 ==========
            loaded_count = 0
            for position in valid_positions:
                pos_id = position.id
                if not pos_id:
                    log.warning(f"持仓缺少 pos_id，跳过: {position}")
                    continue
                
                # 构建策略文件路径
                strategy_file = data_dir / f"{pos_id}.json"
                
                if not strategy_file.exists():
                    log.warning(f"策略文件不存在: {strategy_file}，持仓 pos_id={pos_id}，跳过")
                    continue
                
                try:
                    # 读取策略文件
                    with open(strategy_file, 'r', encoding='utf-8') as f:
                        strategy_info = json.load(f)
                    
                    # 验证策略文件格式
                    if not isinstance(strategy_info, dict):
                        log.warning(f"策略文件格式错误: {strategy_file}")
                        continue
                    
                    # 验证必需参数
                    required_keys = ["symbol", "min_price", "max_price", "direction", 
                                   "grid_spacing", "investment_amount", "leverage"]
                    if not all(key in strategy_info for key in required_keys):
                        log.warning(f"策略文件缺少必需参数: {strategy_file}")
                        continue
                    
                    symbol = strategy_info.get("symbol", "").strip().upper()
                    if not symbol:
                        log.warning(f"策略文件缺少 symbol: {strategy_file}")
                        continue
                    
                    # 验证策略文件中的 pos_id 是否与持仓的 pos_id 匹配
                    file_pos_id = strategy_info.get("pos_id")
                    if file_pos_id and file_pos_id != pos_id:
                        log.warning(f"策略文件中的 pos_id ({file_pos_id}) 与持仓 pos_id ({pos_id}) 不匹配，跳过: {strategy_file}")
                        continue
                    
                    # 检查 symbol 是否已存在（避免重复加载）
                    if symbol in self.symbols:
                        log.warning(f"策略 {symbol} 已存在，跳过加载: {strategy_file}")
                        continue
                    
                    # 创建策略数据
                    symbol_data = self._create_symbol_data()
                    
                    # 填充策略数据
                    symbol_data["symbol"] = symbol
                    symbol_data["min_price"] = strategy_info.get("min_price")
                    symbol_data["max_price"] = strategy_info.get("max_price")
                    symbol_data["direction"] = strategy_info.get("direction")
                    symbol_data["grid_spacing"] = strategy_info.get("grid_spacing")
                    symbol_data["investment_amount"] = strategy_info.get("investment_amount")
                    symbol_data["leverage"] = strategy_info.get("leverage")
                    symbol_data["total_capital"] = strategy_info.get("total_capital")
                    symbol_data["asset_type"] = strategy_info.get("asset_type", "crypto")
                    symbol_data["market_type"] = strategy_info.get("market_type", "contract")
                    symbol_data["co_type"] = strategy_info.get("co_type")
                    symbol_data["start_price"] = strategy_info.get("start_price")
                    symbol_data["each_order_size"] = strategy_info.get("each_order_size")
                    symbol_data["last_filled_time"] = strategy_info.get("last_filled_time", 0)
                    
                    # 更新持仓信息（从实际持仓中获取）
                    symbol_data["position"].id = position.id
                    symbol_data["position"].size = position.size
                    symbol_data["position"].amount = position.amount
                    symbol_data["position"].entryPrice = position.entryPrice
                    symbol_data["position"].unrealizedPnl = position.unrealizedPnl
                    symbol_data["position"].side = position.side
                    symbol_data["position"].liquidationPrice = position.liquidationPrice
                    symbol_data["position"].timestamp = position.timestamp
                    
                    # ========== 步骤4: 从CSV文件加载历史订单记录 ==========
                    his_orders, max_timestamp = self._load_orders_from_csv(symbol, pos_id)
                    symbol_data["his_order"] = his_orders
                    # 更新 last_filled_time（使用CSV中的最大时间戳和JSON中的时间戳的较大值）
                    if max_timestamp > symbol_data.get("last_filled_time", 0):
                        symbol_data["last_filled_time"] = max_timestamp
                    
                    # 添加到字典
                    self.symbols[symbol] = symbol_data
                    loaded_count += 1
                    
                    log.info(f"策略已加载: {symbol}, 文件={strategy_file.name}, pos_id={pos_id}, size={position.size}, 历史订单数={len(symbol_data['his_order'])}")
                    
                    # 自动启动策略
                    self.symbols[symbol]["_status"] = True
                    log.info(f"策略已自动启动: {symbol}")
                    
                except json.JSONDecodeError as e:
                    log.error(f"策略文件JSON格式错误: {strategy_file}, {e}")
                    continue
                except Exception as e:
                    log.error(f"加载策略数据失败: {strategy_file}, {e}")
                    log.error(traceback.format_exc())
                    continue
            
            log.info(f"策略加载完成: 共加载 {loaded_count} 个策略")
            
            # 调试：输出已加载的策略信息
            if loaded_count > 0:
                log.info(f"已加载的策略列表: {list(self.symbols.keys())}")
                for symbol, data in self.symbols.items():
                    log.info(f"策略 {symbol}: _status={data.get('_status')}, _initialized={data.get('_initialized')}, pos_id={data.get('position').id}")
            
            return loaded_count
                
        except Exception as e:
            log.error(f"加载策略参数失败: {e}")
            log.error(traceback.format_exc())
            return 0

    async def _place_grid_orders(self, symbol: str, filled_price: float, order_volume: float) -> None:
        """
        在成交价格两边同时布单（买单和卖单）（支持多 symbol）
        
        参数：
            symbol: 交易对符号
            filled_price: 成交价格
            order_volume: 订单数量（用于计算新订单数量）
        
        逻辑：
            1. 计算新订单价格：
               - 新买单价格 = filled_price * (1 - grid_spacing)
               - 新卖单价格 = filled_price * (1 + grid_spacing)
            2. 根据策略方向决定开仓/平仓：
               - long（做多）：买单=开仓(1)，卖单=平仓(2)
               - short（做空）：卖单=开仓(1)，买单=平仓(2)
            3. 挂新买单（如果价格在范围内）
            4. 挂新卖单（如果价格在范围内且有持仓）
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return
        
        symbol_data = self.symbols[symbol]
        grid_spacing = symbol_data.get("grid_spacing")
        direction = symbol_data.get("direction")
        min_price = symbol_data.get("min_price")
        max_price = symbol_data.get("max_price")
        position = symbol_data.get("position", Position())
        
        # 参数有效性检查，避免 NoneType 运算错误
        if filled_price is None:
            log.warning(f"filled_price 为空，无法创建网格订单: {symbol}")
            return
        if grid_spacing is None:
            log.warning(f"grid_spacing 未初始化，无法创建网格订单: {symbol}")
            return
        if min_price is None or max_price is None:
            log.warning(f"价格区间未初始化，无法创建网格订单: {symbol}")
            return
        if order_volume is None or order_volume <= 0:
            log.warning(f"订单数量无效（{order_volume}），无法创建网格订单: {symbol}")
            return
        
        # 计算新订单价格
        new_buy_price = filled_price * (1 - grid_spacing)
        new_sell_price = filled_price * (1 + grid_spacing)
        
        # 根据策略方向决定开仓/平仓类型
        if direction == "long":
            # 做多：买单=开仓，卖单=平仓
            buy_open_type = 1  # 开仓
            sell_open_type = 2  # 平仓
        else:  # short
            # 做空：卖单=开仓，买单=平仓
            buy_open_type = 2  # 平仓
            sell_open_type = 1  # 开仓
        side = "buy" if direction == "long" else "sell"
        
        # 挂新买单（检查是否已存在相同价格的订单）
        if new_buy_price >= min_price:
            new_buy_order = await self._execute_order(
                symbol=symbol,
                side=side,
                volume=order_volume,
                open_type=buy_open_type,
                price=new_buy_price,
                order_type="limit",
                operation_name="挂买单",
                update_order_info=True
            )
            if new_buy_order:
                symbol_data["buy_order"] = new_buy_order
                log.info(f"挂买单: {symbol}, 价格={new_buy_price:.2f}, 数量={order_volume:.4f}, 类型={'开仓' if buy_open_type == 1 else '平仓'}")
            else:
                log.debug(f"买单价格 {new_buy_price:.2f} 挂单失败: {symbol}")
        
        # 挂新卖单（检查是否已存在相同价格的订单）
        if new_sell_price <= max_price and position.size > 0:
            sell_volume = min(position.size, order_volume)
            new_sell_order = await self._execute_order(
                symbol=symbol,
                side=side,
                volume=sell_volume,
                open_type=sell_open_type,
                price=new_sell_price,
                order_type="limit",
                operation_name="挂卖单",
                update_order_info=True
            )
            if new_sell_order:
                symbol_data["sell_order"] = new_sell_order
                log.info(f"挂卖单: {symbol}, 价格={new_sell_price:.2f}, 数量={sell_volume:.4f}, 类型={'开仓' if sell_open_type == 1 else '平仓'}")
            else:
                log.debug(f"卖单价格 {new_sell_price:.2f} 挂单失败: {symbol}")
        else:
            log.debug(f"卖单错误：{symbol}, {new_sell_price}，最大价格：{max_price}，持仓大小：{position.size}")

    async def _initial_build_position(self, symbol: str) -> None:
        """
        执行初始建仓（合并了计算比例、数量和建仓逻辑）（支持多 symbol）
        
        参数：
            symbol: 交易对符号
        
        公式说明：
        1. 计算价格位置比例：position_ratio = (current_price - min_price) / (max_price - min_price)
           - position_ratio 在 0-1 之间
           - 0 表示价格在最低价，1 表示价格在最高价
        
        2. 根据策略方向计算初始持仓比例：
           - long（做多）：initial_ratio = 1 - position_ratio（价格越低，持仓比例越高）
           - short（做空）：initial_ratio = position_ratio（价格越高，持仓比例越高）
        
        3. 计算初始持仓数量：
           - initial_amount = investment_amount * initial_ratio
           - volume = initial_amount / current_price
        
        建仓逻辑：
        - 如果当前已有持仓，且方向一致，检查数量是否需要调整（仅支持加仓）
        - 如果当前无持仓，根据公式计算并建仓
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return
        
        symbol_data = self.symbols[symbol]
        current_price = symbol_data.get("current_price")
        min_price = symbol_data["min_price"]
        max_price = symbol_data["max_price"]
        direction = symbol_data["direction"]
        total_capital = symbol_data["total_capital"]
        position = symbol_data["position"]
        
        if current_price is None:
            log.warning(f"当前价格为空，无法计算初始持仓: {symbol}")
            return
        
        # 确保价格在范围内
        current_price = max(min_price, min(current_price, max_price))
        
        # 计算价格位置比例
        price_range = max_price - min_price
        if price_range <= 0 or current_price <= 0:
            log.warning(f"价格范围无效或当前价格为0，无法计算初始持仓: {symbol}")
            return
        
        position_ratio = (current_price - min_price) / price_range
        
        # 根据策略方向计算初始持仓比例
        if direction == "long":
            initial_ratio = 1.0 - position_ratio  # 做多：价格越低，持仓比例越高
        else:  # short
            initial_ratio = position_ratio  # 做空：价格越高，持仓比例越高
        
        initial_ratio = max(0.0, min(1.0, initial_ratio))
        
        # 计算初始持仓金额和数量
        if total_capital is None or total_capital <= 0:
            raise ValueError(f"总资金未正确初始化: {symbol}, {total_capital}")
        initial_amount = total_capital * initial_ratio
        target_volume = initial_amount / current_price
        
        log.info(f"初始持仓计算: {symbol}, 当前价格={current_price:.2f}, "
                f"位置比例={position_ratio:.2%}, "
                f"持仓比例={initial_ratio:.2%}, "
                f"持仓金额={initial_amount:.2f}, "
                f"持仓数量={target_volume:.4f}")
        
        if target_volume <= 0:
            log.info(f"计算出的初始持仓数量为0，不进行建仓: {symbol}")
            return
        
        # 如果已有持仓，检查是否需要调整
        if position.size == 0:
            # 无持仓，直接建仓
            side = "buy" if direction == "long" else "sell"
            await self._execute_order(symbol, side, target_volume, open_type=1, order_type="market", operation_name="建仓")
        await self._update_position(symbol)


    async def _execute_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        open_type: int = None,
        price: float = None,
        order_type: str = "limit",
        operation_name: str = "",
        update_order_info: bool = False,
    ) -> Optional[OrderInfo]:
        """
        执行订单（统一方法，用于建仓、加仓、减仓、平仓、挂限价单）（支持多 symbol）
        
        参数：
            symbol: 交易对符号
            side: 订单方向，"buy" 或 "sell"
            volume: 订单数量
            open_type: 开仓类型，1=开仓，2=平仓（限价单时可为None）
            price: 订单价格（限价单时必填，市价单时为None）
            order_type: 订单类型，"market"（市价单）或 "limit"（限价单）
            operation_name: 操作名称（用于日志），如 "建仓"、"加仓"、"挂买单"、"挂卖单"
            update_order_info: 是否更新订单信息（限价单时设为True，更新buy_order或sell_order）
        
        返回：
            Optional[OrderInfo]: 订单信息对象（成功时返回），失败时返回 None
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return None
        
        symbol_data = self.symbols[symbol]
        
        if volume <= 0:
            log.warning(f"{operation_name}数量为0，跳过: {symbol}")
            return None
        
        # 限价单需要价格
        if order_type == "limit" and price is None:
            log.error(f"{operation_name}限价单需要价格参数: {symbol}")
            return None
        try:
            # 构建订单参数（统一使用 create_order）
            order_params = {
                "symbol": symbol,
                "side": side,
                "vol": volume,  # create_order 使用 vol 参数
                "order_type": order_type,  # "market" 或 "limit"
            }
            
            # 限价单需要价格
            if order_type == "limit" and price is not None:
                order_params["price"] = price
            
            # 开仓类型（合约市场时需要）
            market_type = symbol_data["market_type"]
            co_type = symbol_data.get("co_type")
            leverage = symbol_data.get("leverage")
            
            if open_type is not None and market_type == "contract":
                order_params["open_type"] = open_type
                if co_type is not None:
                    order_params["co_type"] = co_type
                # 合约下单时传递杠杆倍数
                if leverage is not None:
                    try:
                        order_params["leverage"] = int(leverage)
                    except (TypeError, ValueError):
                        log.warning(f"{operation_name} 使用的杠杆倍数无效: {symbol}, {leverage}，将不传递 leverage 参数")
            
            # 平仓时需要传递 posId
            position = symbol_data["position"]
            if open_type == 2 and position.id is not None:
                order_params["posId"] = position.id
            
            # 统一使用 create_order（支持限价单和市价单）
            # create_order 现在返回 OrderInfo 对象
            order_info = await self.exchange.create_order(**order_params)
            
            # 处理响应（order_info 是 OrderInfo 对象）
            if isinstance(order_info, OrderInfo):
                # 判断订单是否创建成功：
                # 检查是否为休市中（code: 6005）
                if order_info.code == 6005:
                    self._trading_status_cache["last_update_time"] = 0
                    self._trading_status_cache["is_trade"] = False
                    log.debug(f"市场休市中，已重置缓存时间: {symbol}")
                return order_info
               
            else:
                log.error(f"{operation_name}失败: 响应格式错误，期望 OrderInfo 对象")
                log.error(f"响应数据: {order_info}")
                return None
                
        except Exception as e:
            log.error(f"{operation_name}异常: {e}")
            log.error(traceback.format_exc())
            return None
    
    async def _update_position(self, symbol: str) -> None:
        """
        更新持仓信息（从交易所获取最新持仓数据）（支持多 symbol）
        
        参数：
            symbol: 交易对符号
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return
        
        symbol_data = self.symbols[symbol]
        
        try:
            positions = await self.exchange.fetch_positions(symbol)
            # fetch_positions 传入 symbol 时，总是返回至少一个 Position 对象（如果没有持仓，返回 size=0 的对象）
            if positions and isinstance(positions, list) and len(positions) > 0:
                pos = positions[0]  # fetch_positions 已经按 symbol 过滤，取第一个
                position = symbol_data["position"]
                position.id = pos.id
                position.size = pos.size
                position.side = pos.side
                position.entryPrice = pos.entryPrice
                position.unrealizedPnl = pos.unrealizedPnl
                position.liquidationPrice = pos.liquidationPrice
                position.amount = pos.amount
                position.timestamp = pos.timestamp
        except Exception as e:
            log.error(f"更新持仓信息异常: {symbol}, {e}")

    
   
    
    async def start(
        self,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        启动策略（支持多 symbol）
        
        参数：
            params: 参数字典，包含以下键：
                - symbol: 交易币种 (必需)
                - min_price: 最低价格 (必需)
                - max_price: 最高价格 (必需)
                - direction: 交易方向，"long" 或 "short" (必需)
                - grid_spacing: 网格间距（百分比，如 0.01 表示 1%）(必需)
                - investment_amount: 持仓总金额（最大持仓金额）(必需)
                - leverage: 杠杆倍数 (必需)
                - asset_type: 资产类型，"crypto"（加密货币）或 "stock"（股票），默认 "crypto"
                - market_type: 市场类型，"spot"（现货）或 "contract"（合约），默认 "contract"
                - co_type: 合约类型，可选
        
        返回：
            Dict[str, Any]: 包含 status 和 message 的字典
                - status: "success" 或 "failed"
                - message: 状态消息
        """
        try:
            # 依次检查必需参数
            required_params = ["symbol", "min_price", "max_price", "direction", "grid_spacing", "investment_amount", "leverage"]
            missing_params = [p for p in required_params if p not in params]
            if missing_params:
                raise ValueError(f"缺少必需参数: {', '.join(missing_params)}")
            
            # 提取参数
            symbol = params.get("symbol")
            min_price = params.get("min_price")
            max_price = params.get("max_price")
            direction = params.get("direction")
            grid_spacing = params.get("grid_spacing")
            investment_amount = params.get("investment_amount")
            leverage = params.get("leverage")
            asset_type = params.get("asset_type", "crypto")
            market_type = params.get("market_type", "contract")
            
            # 依次检查参数合法性
            # 1. 检查 symbol
            if not symbol or not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("symbol 必须是非空字符串")
            symbol = symbol.strip().upper()
            
            # 检查 symbol 是否已存在
            if symbol in self.symbols:
                raise ValueError(f"策略 {symbol} 已存在，请先停止现有策略或使用不同的 symbol")
            
            # 2. 检查 min_price
            try:
                min_price = float(min_price)
            except (TypeError, ValueError):
                raise ValueError("min_price 必须是有效的数字")
            if min_price <= 0:
                raise ValueError("min_price 必须大于 0")
            
            # 3. 检查 max_price
            try:
                max_price = float(max_price)
            except (TypeError, ValueError):
                raise ValueError("max_price 必须是有效的数字")
            if max_price <= 0:
                raise ValueError("max_price 必须大于 0")
            
            # 4. 检查价格区间
            if min_price >= max_price:
                raise ValueError("min_price 必须小于 max_price")
            
            # 5. 检查 direction
            if not direction or not isinstance(direction, str):
                raise ValueError("direction 必须是字符串")
            direction = direction.lower()
            if direction not in ["long", "short"]:
                raise ValueError("direction 必须是 'long' 或 'short'")
            
            # 6. 检查 grid_spacing
            try:
                grid_spacing = float(grid_spacing)
            except (TypeError, ValueError):
                raise ValueError("grid_spacing 必须是有效的数字")
            if grid_spacing <= 0 or grid_spacing >= 1:
                raise ValueError("grid_spacing 必须在 0 和 1 之间（例如：0.005 表示 0.5%）")
            
            # 7. 检查 investment_amount
            try:
                investment_amount = float(investment_amount)
            except (TypeError, ValueError):
                raise ValueError("investment_amount 必须是有效的数字")
            if investment_amount <= 0:
                raise ValueError("investment_amount 必须大于 0")
            
            # 8. 检查 leverage
            try:
                leverage = float(leverage)
            except (TypeError, ValueError):
                raise ValueError("leverage 必须是有效的数字")
            if leverage <= 0:
                raise ValueError("leverage 必须大于 0")
            if leverage > 100:
                raise ValueError("leverage 不能超过 100")
            
            # 9. 检查 asset_type
            if asset_type not in ["crypto", "stock"]:
                raise ValueError("asset_type 必须是 'crypto' 或 'stock'")
            
            # 10. 检查 market_type
            if market_type not in ["spot", "contract"]:
                raise ValueError("market_type 必须是 'spot' 或 'contract'")
            
            # 创建新 symbol 的策略数据
            symbol_data = self._create_symbol_data()
            
            # 设置基础参数
            symbol_data["symbol"] = symbol
            symbol_data["min_price"] = min_price
            symbol_data["max_price"] = max_price
            symbol_data["direction"] = direction
            symbol_data["grid_spacing"] = grid_spacing
            symbol_data["investment_amount"] = investment_amount
            symbol_data["leverage"] = float(leverage)
            symbol_data["asset_type"] = asset_type
            symbol_data["market_type"] = market_type
            
            # 计算总资金
            total_capital = investment_amount * leverage
            symbol_data["total_capital"] = total_capital
            
            # 验证关键参数
            if symbol_data["leverage"] is None or symbol_data["leverage"] <= 0:
                raise ValueError(f"杠杆倍数未正确初始化: {symbol_data['leverage']}")
            if symbol_data["investment_amount"] is None or symbol_data["investment_amount"] <= 0:
                raise ValueError(f"投入资金未正确初始化: {symbol_data['investment_amount']}")
            
            # 设置 co_type：优先使用传入的参数，否则根据 asset_type 和 market_type 计算
            co_type_param = params.get("co_type")
            if co_type_param is not None:
                try:
                    co_type_value = int(co_type_param)
                    if co_type_value not in [1, 3]:
                        raise ValueError(f"co_type 参数无效，必须是 1（股票）或 3（加密货币），当前值: {co_type_value}")
                    if market_type != "contract":
                        raise ValueError("co_type 参数仅在合约市场有效")
                    symbol_data["co_type"] = co_type_value
                except (TypeError, ValueError) as e:
                    raise ValueError(f"co_type 参数格式错误: {e}")
            else:
                if asset_type == "stock" and market_type == "contract":
                    symbol_data["co_type"] = 1
                elif asset_type == "crypto" and market_type == "contract":
                    symbol_data["co_type"] = 3
                elif market_type == "spot":
                    symbol_data["co_type"] = None
                else:
                    raise ValueError(f"不支持的资产类型和市场类型组合: asset_type={asset_type}, market_type={market_type}")
            
            # 更新统计信息
            symbol_data["stats"]["co_type"] = symbol_data["co_type"]

            # ========== 初始化：根据网格参数设置杠杆倍数 ==========
            if market_type == "contract" and symbol_data["co_type"] is not None:
                try:
                    set_res = await self.exchange.set_leverage(
                        symbol=symbol,
                        leverage=int(leverage),
                        co_type=int(symbol_data["co_type"]),
                        margin_mode=1,
                    )
                    if not set_res.get("ok"):
                        log.warning(
                            f"设置杠杆失败: symbol={symbol}, leverage={leverage}, "
                            f"code={set_res.get('code')}, msg={set_res.get('msg')}"
                        )
                    else:
                        log.info(
                            f"杠杆设置成功: symbol={symbol}, leverage={leverage}, "
                            f"co_type={symbol_data['co_type']}"
                        )
                except Exception as e:
                    log.error(f"设置杠杆异常: symbol={symbol}, leverage={leverage}, error={e}")
            
            # 资金检查：验证账户可用余额是否足够
            try:
                account_info = await self.exchange.fetch_account()
                free_balance = account_info.get("balance", 0.0)
                
                position_margin = 0.0
                positions = await self.exchange.fetch_positions(symbol)
                if positions and len(positions) > 0:
                    for pos in positions:
                        if pos.size > 0 and pos.raw:
                            raw_data = pos.raw
                            pos_margin = float(raw_data.get("posMargin", 0) or 0)
                            position_margin += pos_margin
                            log.info(f"检测到持仓：symbol={symbol}, size={pos.size}, 保证金={pos_margin:.2f}")
                
                available_balance = free_balance + position_margin
                required_amount = investment_amount
                
                if available_balance < required_amount:
                    margin_info = f"，持仓保证金 ${position_margin:.2f}，" if position_margin > 0 else "，"
                    raise ValueError(
                        f"账户余额不足：可用余额 ${free_balance:.2f}{margin_info}"
                        f"总可用资金 ${available_balance:.2f}，"
                        f"所需保证金 ${required_amount:.2f}（投资额 ${investment_amount:.2f}）"
                    )
                
                margin_info = f"，持仓保证金 ${position_margin:.2f}，" if position_margin > 0 else "，"
                log.info(f"资金检查通过：账户余额 ${free_balance:.2f}{margin_info}"
                        f"总可用资金 ${available_balance:.2f}，所需保证金 ${required_amount:.2f}，"
                        f"总资金 ${total_capital:.2f}（投资额 × 杠杆 {leverage}倍）")
            except ValueError:
                raise
            except Exception as e:
                log.error(f"资金检查失败: {e}")
                raise ValueError(f"无法获取账户余额信息: {str(e)}")
            
            # 将策略数据添加到 self.symbols
            self.symbols[symbol] = symbol_data
            
            log.info(f"网格策略参数设置: {symbol}, 方向={direction}, "
                    f"价格范围=[{min_price}, {max_price}], "
                    f"网格间距={grid_spacing*100}%, 投入资金={investment_amount}, "
                    f"杠杆倍数={leverage}, 总资金={total_capital}, "
                    f"资产类型={asset_type}, 市场类型={market_type}, co_type={symbol_data['co_type']}")
            
            # 设置运行状态
            self.symbols[symbol]["_status"] = True
            log.info(f"网格策略已启动: {symbol}")
            
            # 注意：主循环已在 __init__ 中通过 run() 方法启动，此处无需重复启动
            
            return {
                "status": "success",
                "message": f"网格策略已启动: {symbol}",
                "params": {
                    "symbol": symbol,
                    "min_price": min_price,
                    "max_price": max_price,
                    "direction": direction,
                    "grid_spacing": grid_spacing,
                    "investment_amount": investment_amount,
                    "leverage": leverage,
                    "total_capital": total_capital,
                    "asset_type": asset_type,
                    "market_type": market_type,
                    "co_type": symbol_data["co_type"],
                }
            }
        except Exception as e:
            log.error(f"启动策略失败: {e}")
            log.error(traceback.format_exc())
            return {
                "status": "failed",
                "message": str(e)
            }
    
    async def stop(self, symbol: Optional[str] = None) -> None:
        """
        停止策略（支持多 symbol）
        
        参数：
            symbol: 可选，指定要停止的 symbol。如果为 None，则停止所有 symbol
        
        行为：
        1. 将运行标志 `_status` 置为 False，停止主循环；
        2. 取消当前策略相关的所有未成交挂单；
        3. 仅清理策略内部状态（订单引用、运行标记等），**不再主动平掉已有持仓**。
        """
        if symbol is None:
            # 停止所有 symbol
            symbols_to_stop = list(self.symbols.keys())
            log.info(f"开始停止所有网格策略: {len(symbols_to_stop)} 个策略")
            
            for sym in symbols_to_stop:
                await self._stop_symbol(sym)
            
            # 如果所有策略都停止了，可以考虑停止主循环
            if not any(s.get("_status", False) for s in self.symbols.values()):
                if self._run_task and not self._run_task.done():
                    self._run_task.cancel()
                    log.info("所有策略已停止，主循环已取消")
        else:
            # 停止指定 symbol
            symbol = symbol.strip().upper()
            if symbol not in self.symbols:
                log.warning(f"策略 {symbol} 不存在，无需停止")
                return
            
            await self._stop_symbol(symbol)
    
    async def _stop_symbol(self, symbol: str) -> None:
        """
        停止指定 symbol 的策略（内部方法）
        
        参数：
            symbol: 要停止的 symbol
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return
        
        symbol_data = self.symbols[symbol]
        
        # 1. 标记策略已停止
        symbol_data["_status"] = False
        log.info(f"开始停止网格策略: {symbol}")

        # 2. 取消所有挂单
        try:
            open_orders = await self.exchange.fetch_orders(symbol)
        except Exception as e:
            log.error(f"获取待取消挂单失败: {symbol}, {e}")
            open_orders = None

        if open_orders:
            for order in open_orders:
                try:
                    if not getattr(order, "id", None):
                        continue
                    await self.exchange.cancel_order(order.id)
                    log.info(f"已取消挂单: symbol={symbol}, order_id={order.id}, price={getattr(order, 'price', None)}, volume={getattr(order, 'volume', None)}")
                except Exception as e:
                    log.error(f"取消挂单失败: symbol={symbol}, order_id={getattr(order, 'id', 'unknown')}, error={e}")

        # 3. 清理内部状态
        symbol_data["buy_order"] = None
        symbol_data["sell_order"] = None
        log.info(f"网格策略已停止并完成清理: {symbol}")
    
    def _calculate_summary(self, symbol: str) -> Dict[str, Any]:
        """
        计算汇总统计数据（支持多 symbol）
        
        参数：
            symbol: 交易对符号
        
        返回：
            Dict[str, Any]: 包含以下字段的统计字典：
            - 总投资
            - 总盈亏（已实现 + 未实现）
            - 网格收益
            - 未实现盈亏
            - 套利年化收益
            - 网格次数

        说明：
        - 这里的计算是一个「合理默认实现」，具体业务规则可以后续再细化。
        - his_order 中的每条记录结构参考 process_order_statistics 中的 record。
        """
        if symbol not in self.symbols:
            log.warning(f"策略 {symbol} 不存在")
            return {}
        
        symbol_data = self.symbols[symbol]
        
        # 投资额使用真实投入资金（不含杠杆放大）
        total_investment = float(symbol_data.get("investment_amount", 0.0) or 0.0)

        # 已实现盈亏：如果 his_order 中有 pnl 字段，则累加
        his_order = symbol_data.get("his_order", [])
        realized_pnl_from_orders = 0.0
        for o in his_order:
            try:
                realized_pnl_from_orders += float(o.get("pnl", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue

        # 未实现盈亏：来自当前持仓（Position 一定有 unrealizedPnl 字段）
        position = symbol_data.get("position", Position())
        unrealized_pnl = float(position.unrealizedPnl or 0.0)

        # 总盈亏 = 已实现 + 未实现
        total_pnl = realized_pnl_from_orders + unrealized_pnl

        # 网格收益：这里先等同于已实现盈亏，后续可根据网格策略细化
        grid_profit = realized_pnl_from_orders

        # 网格次数：先用成交记录条数作为近似值（后续可按平仓次数等更精细的定义）
        grid_count = len(his_order)

        # 套利次数：统计平仓订单数量（open_type=2）
        arbitrage_count = sum(1 for o in his_order if o.get("open_type") == 2)

        # 总成交额：累加所有订单的成交金额
        total_volume = sum(
            float(o.get("price", 0.0) or 0.0) * float(o.get("volume", 0.0) or 0.0)
            for o in his_order
        )

        # 套利年化收益：基于总盈亏 / 总投资 和运行时间简单估算
        annualized_return = 0.0
        stats = symbol_data.get("stats", {})
        start_time = stats.get("start_time")
        if total_investment > 0 and start_time:
            try:
                elapsed = datetime.now() - start_time
                days = max(elapsed.total_seconds() / 86400.0, 1e-6)  # 避免除 0
                simple_return = total_pnl / total_investment  # 总收益率
                annualized_return = simple_return * (365.0 / days) * 100.0  # 转年化百分比
            except Exception as e:
                log.error(f"计算年化收益失败: {symbol}, {e}")

        return {
            "total_investment": total_investment,
            "total_pnl": total_pnl,
            "grid_profit": grid_profit,
            "unrealized_pnl": unrealized_pnl,
            "annualized_return": annualized_return,
            "grid_count": grid_count,
            "arbitrage_count": arbitrage_count,
            "total_volume": total_volume,
        }

    def get_status(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        获取策略状态与汇总指标（支持多 symbol）
        
        参数：
            symbol: 可选，指定要获取的 symbol。如果为 None，返回所有策略的状态列表
        
        返回：
            Dict[str, Any]: 如果 symbol 指定，返回单个策略状态；如果为 None，返回所有策略的状态列表
        """
        if symbol is None:
            # 返回所有策略的状态列表
            strategies = []
         #   log.info(f"获取所有策略状态，当前 symbols 数量: {len(self.symbols)}")
            for sym in self.symbols.keys():
                try:
                    status = self._get_symbol_status(sym)
                    # status 可能是 None 或字典，只有字典才添加到列表
                    if status is not None:
                        strategies.append(status)
                     #   log.info(f"策略 {sym} 状态已添加到列表，running={status.get('running')}")
                    else:
                        log.warning(f"策略 {sym} 状态为 None，未添加到列表")
                except Exception as e:
                    log.error(f"获取策略状态失败: {sym}, {e}")
                    log.error(traceback.format_exc())
                    continue
            
            # 计算汇总统计
            total = len(strategies)
            running = sum(1 for s in strategies if s.get("running", False))
            stopped = total - running
            
            return {
                "strategies": strategies,
                "total": total,
                "running": running,
                "stopped": stopped,
                "connected": self.exchange.connected(),
            }
        else:
            # 返回指定 symbol 的状态
            symbol = symbol.strip().upper()
            return self._get_symbol_status(symbol) or {}
    
    def _get_symbol_status(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 symbol 的策略状态（内部方法）
        
        参数：
            symbol: 交易对符号
        
        返回：
            Optional[Dict[str, Any]]: 策略状态字典，如果 symbol 不存在则返回 None
        """
        if symbol not in self.symbols:
            return None
        
        symbol_data = self.symbols[symbol]
        
        # ==================== 订单信息 ====================
        # 格式化买单（统一使用对象模式）
        buy_order_info = None
        buy_order = symbol_data.get("buy_order")
        if buy_order and isinstance(buy_order, OrderInfo):
            buy_order_info = {
                "order_id": buy_order.id or "",
                "price": buy_order.price,
                "volume": buy_order.volume,
                "status": buy_order.status,
            }
        
        # 格式化卖单（统一使用对象模式）
        sell_order_info = None
        sell_order = symbol_data.get("sell_order")
        if sell_order and isinstance(sell_order, OrderInfo):
            sell_order_info = {
                "order_id": sell_order.id or "",
                "price": sell_order.price,
                "volume": sell_order.volume,
                "status": sell_order.status,
            }

        # ==================== 汇总指标 ====================
        summary = self._calculate_summary(symbol)
        
        # 计算市场状态（是否在交易时段）
        is_trading_hours = True
        co_type = symbol_data.get("co_type")
        if co_type == 1:  # 股票合约
            is_trading_hours = self.is_us_stock_trading_hours()
        
        # 计算已运行时间
        elapsed_time = None
        stats = symbol_data.get("stats", {})
        start_time = stats.get("start_time")
        if start_time:
            try:
                elapsed = datetime.now() - start_time
                total_seconds = int(elapsed.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                if hours > 0:
                    elapsed_time = f"{hours}小时{minutes}分钟"
                elif minutes > 0:
                    elapsed_time = f"{minutes}分钟{seconds}秒"
                else:
                    elapsed_time = f"{seconds}秒"
            except Exception as e:
                log.error(f"计算运行时间失败: {symbol}, {e}")
        
        position = symbol_data.get("position", Position())
        his_order = symbol_data.get("his_order", [])
        
        return {
            # 基本信息
            "symbol": symbol,
            "direction": symbol_data.get("direction"),
            "price_range": [symbol_data.get("min_price"), symbol_data.get("max_price")] if symbol_data.get("min_price") and symbol_data.get("max_price") else None,
            "grid_spacing": symbol_data.get("grid_spacing"),
            "asset_type": symbol_data.get("asset_type"),
            "market_type": symbol_data.get("market_type"),
            "current_price": symbol_data.get("current_price"),
            "start_price": symbol_data.get("start_price"),  # 启动价格
            "leverage": float(symbol_data.get("leverage", 1.0) or 1.0),  # 倍数（从配置参数获取）
            "investment_amount": float(symbol_data.get("investment_amount", 0.0) or 0.0),  # 投资额（不包含杠杆）
            "elapsed_time": elapsed_time,  # 已运行时间

            # 运行与连接状态
            "running": symbol_data.get("_status", False),
            "connected": self.exchange.connected(),
            "is_trading_hours": is_trading_hours,  # 是否在交易时段（仅对美股有效）

            # 汇总指标
            "summary": summary,

            # 订单与持仓明细
            "buy_order": buy_order_info,
            "sell_order": sell_order_info,
            "position": {
                "size": position.size,
                "amount": position.amount,
                "entryPrice": position.entryPrice,
                "unrealizedPnl": position.unrealizedPnl,
                "side": position.side,
            },

            # 历史成交（最近 5 条）
            "his_order": his_order[-5:] if len(his_order) > 0 else [],
        }
    
    async def alert_msg(self, msg: str) -> None:
        """发送报警消息"""
        url = "https://api.day.app/c4FFQEfS8oc3KyXEBhCQBF/网格策略报警/" + msg
        requests.get(url)


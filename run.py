"""
网格策略运行脚本

使用方法:
    python run.py                    # 使用默认配置文件 config.yaml
    python run.py -c config.yaml     # 指定配置文件
"""

import asyncio
import argparse
from backend.grid import GridStrategy
from backend.exchange import MsxExchange
from backend.config_loader import load_config
from loguru import logger as log


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="网格策略运行脚本")
    parser.add_argument(
        "-c", "--config",
        type=str,
        default="config.yaml",
        help="配置文件路径（默认: config.yaml）"
    )
    return parser.parse_args()


async def main():
    """主函数"""
    args = parse_args()
    
    # 加载配置
    config = load_config(args.config)
    grid_config = config.get("grid_strategy", {})
    heads = config.get("heads", [])
    if not grid_config:
        raise ValueError("配置文件中未找到必需的配置段落: grid_strategy")
    
    # 初始化交易所
    log.info("正在初始化交易所连接...")
    exchange = MsxExchange(cdp_url=config.get("cdp_url"))
    await exchange.connect()
    log.info("✅ 交易所连接成功")
    
    # 创建策略实例
    log.info("正在创建网格策略实例...")
    strategy = GridStrategy(exchange=exchange)
    
    # 从配置中提取参数
    symbol = grid_config.get("symbol")
    min_price = grid_config.get("min_price")
    max_price = grid_config.get("max_price")
    direction = grid_config.get("direction")
    grid_spacing = grid_config.get("grid_spacing")
    investment_amount = grid_config.get("investment_amount")
    asset_type = grid_config.get("asset_type", "crypto")  # 默认为加密货币
    market_type = grid_config.get("market_type", "contract")  # 默认为合约
    
    # 启动策略（传入网格参数）
    log.info("正在启动网格策略...")
    await strategy.start(
        symbol=symbol,
        min_price=min_price,
        max_price=max_price,
        direction=direction,
        grid_spacing=grid_spacing,
        investment_amount=investment_amount,
        asset_type=asset_type,
        market_type=market_type,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("用户中断程序")
    except Exception as e:
        log.error(f"程序运行错误: {e}")
        raise
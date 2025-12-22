# 多币种网格支持 - 阶段一任务清单

## 任务概述
改造 `GridStrategy` 类，使其在单个实例内支持管理多个 symbol 的网格策略。

---

## 任务 1：改造 GridStrategy 类数据结构

### 1.1 修改 `__init__` 方法
- [x] 将单 symbol 字段改为 `self.symbols: Dict[str, Dict[str, Any]] = {}` 字典结构
- [x] 保留共享的 `self.exchange` 和 `self.redis` 实例
- [x] 移除或注释掉原有的单 symbol 字段（如 `self.symbol`, `self.min_price` 等）
- [x] 添加类型提示：`from typing import Dict, Any`

### 1.2 定义 symbol 数据结构模板
- [x] 创建 `_create_symbol_data()` 辅助方法，返回新 symbol 的初始数据结构
- [x] 数据结构包含所有必需字段：
  - 基础参数：symbol, min_price, max_price, direction, grid_spacing, investment_amount, leverage, total_capital
  - 市场类型：asset_type, market_type, co_type
  - 价格信息：current_price, start_price
  - 订单信息：buy_order, sell_order
  - 持仓信息：position (Position 对象)
  - 历史订单：his_order (List[Dict])
  - 状态标志：_status, _initialized, _run_task
  - 统计信息：stats (Dict)
  - 其他：last_filled_time, each_order_size, min_order_size

---

## 任务 2：改造核心方法 - start()

### 2.1 修改方法签名和逻辑
- [x] 修改 `start(params)` 方法，支持添加新 symbol
- [x] 从 `params` 中提取 `symbol` 参数
- [x] 检查 `symbol` 是否已存在于 `self.symbols` 中
  - [x] 如果已存在，抛出 `ValueError` 提示策略已存在
  - [x] 或者提供更新选项（根据业务规则决定）

### 2.2 创建新 symbol 策略数据
- [x] 调用 `_create_symbol_data()` 创建初始数据结构
- [x] 验证所有必需参数（min_price, max_price, direction 等）
- [x] 计算 `total_capital = investment_amount * leverage`
- [x] 设置 `co_type`（根据 asset_type 和 market_type）

### 2.3 设置杠杆和资金检查
- [x] 如果是合约市场，调用 `exchange.set_leverage()` 设置杠杆
- [x] 检查账户余额是否足够（考虑已有持仓的保证金）
- [x] 将策略数据添加到 `self.symbols[symbol]`

### 2.4 启动策略运行
- [x] 设置 `self.symbols[symbol]["_status"] = True`
- [x] 如果主循环未运行，启动主循环 `self._run_task`
- [x] 返回成功响应，包含策略信息

---

## 任务 3：改造核心方法 - stop()

### 3.1 修改方法签名
- [x] 修改 `stop(symbol: Optional[str] = None)` 方法
- [x] 如果 `symbol` 为 `None`，停止所有 symbol
- [x] 如果 `symbol` 指定，只停止该 symbol

### 3.2 停止指定 symbol
- [x] 检查 `symbol` 是否存在于 `self.symbols` 中
- [x] 设置 `self.symbols[symbol]["_status"] = False`
- [x] 取消该 symbol 的所有挂单（调用 `exchange.cancel_order()`）
- [x] 清理该 symbol 的订单引用（buy_order, sell_order）

### 3.3 停止所有 symbol
- [x] 遍历 `self.symbols` 中的所有 symbol
- [x] 对每个 symbol 执行停止逻辑
- [x] 如果所有 symbol 都停止，可以考虑停止主循环（可选）

---

## 任务 4：改造核心方法 - run()

### 4.1 修改主循环逻辑
- [x] 修改 `run()` 方法，改为遍历所有 symbol
- [x] 主循环条件：检查是否有运行中的策略（`any(s.get("_status") for s in self.symbols.values())`）
- [x] 或者使用全局运行标志（根据设计决定）

### 4.2 遍历处理每个 symbol
- [x] 使用 `for symbol in list(self.symbols.keys())` 遍历（使用 list 避免迭代时修改字典）
- [x] 跳过未运行的策略（`_status == False`）
- [x] 对每个 symbol 执行：
  - [x] 检查交易时段（如果是股票，调用 `is_us_stock_trading_hours()`）
  - [x] 检查初始化状态，如果未初始化则调用 `_init_(symbol)`
  - [x] 调用 `check_order(symbol)` 检查订单

### 4.3 异常处理
- [x] 使用 try-except 包裹每个 symbol 的处理逻辑
- [x] 某个 symbol 出错不应影响其他 symbol
- [x] 记录错误日志，包含 symbol 信息

---

## 任务 5：改造核心方法 - check_order()

### 5.1 修改方法签名
- [x] 修改 `check_order(symbol: str)` 方法，接收 symbol 参数
- [x] 从 `self.symbols[symbol]` 获取策略数据

### 5.2 更新价格和持仓
- [x] 调用 `exchange.fetch_ticker(symbol)` 获取最新价格
- [x] 更新 `self.symbols[symbol]["current_price"]`
- [x] 调用 `exchange.fetch_positions(symbol)` 更新持仓信息
- [x] 更新 `self.symbols[symbol]["position"]`

### 5.3 检查订单状态
- [x] 调用 `exchange.fetch_orders(symbol)` 获取当前挂单
- [x] 检查 `buy_order` 和 `sell_order` 是否已成交
- [x] 根据成交情况调用 `_place_grid_orders(symbol, ...)` 重新挂单

### 5.4 处理订单统计
- [x] 调用 `process_order_statistics(symbol)` 更新统计信息

---

## 任务 6：改造辅助方法 - _init_()

### 6.1 修改方法签名
- [x] 修改 `_init_(symbol: str)` 方法，接收 symbol 参数
- [x] 从 `self.symbols[symbol]` 获取策略数据

### 6.2 切换交易对
- [x] 调用 `exchange.change_symbol(symbol)` 切换交易对
- [x] 等待认证成功

### 6.3 清理历史挂单
- [x] 检查交易时段（如果是股票）
- [x] 获取所有挂单并撤销

### 6.4 获取价格和持仓
- [x] 获取当前价格，更新 `current_price` 和 `start_price`
- [x] 获取持仓信息，更新 `position`

### 6.5 建仓逻辑
- [x] 如果无持仓，调用 `_initial_build_position(symbol)` 建仓
- [x] 计算 `each_order_size`

### 6.6 创建网格订单
- [x] 调用 `_place_grid_orders(symbol, current_price, each_order_size)`
- [x] 设置 `_initialized = True`
- [x] 持久化策略信息

---

## 任务 7：改造其他辅助方法

### 7.1 _place_grid_orders()
- [x] 修改方法签名：`_place_grid_orders(symbol: str, filled_price: float, order_volume: float)`
- [x] 从 `self.symbols[symbol]` 获取策略数据
- [x] 使用策略数据中的参数创建订单
- [x] 更新 `self.symbols[symbol]["buy_order"]` 和 `self.symbols[symbol]["sell_order"]`

### 7.2 _initial_build_position()
- [x] 修改方法签名：`_initial_build_position(symbol: str)`
- [x] 从 `self.symbols[symbol]` 获取策略数据
- [x] 使用策略数据中的参数计算建仓数量
- [x] 调用 `_execute_order(symbol, ...)` 执行建仓

### 7.3 _execute_order()
- [x] 修改方法签名：`_execute_order(symbol: str, side: str, volume: float, ...)`
- [x] 从 `self.symbols[symbol]` 获取策略数据
- [x] 使用策略数据中的参数（symbol, co_type, leverage 等）创建订单

### 7.4 _update_position()
- [x] 修改方法签名：`_update_position(symbol: str)`
- [x] 从 `self.symbols[symbol]` 获取策略数据
- [x] 更新 `self.symbols[symbol]["position"]`

### 7.5 process_order_statistics()
- [x] 修改方法签名：`process_order_statistics(symbol: str)`
- [x] 从 `self.symbols[symbol]` 获取策略数据
- [x] 更新 `self.symbols[symbol]["his_order"]` 和统计信息

### 7.6 _calculate_summary()
- [x] 修改方法签名：`_calculate_summary(symbol: str)`
- [x] 从 `self.symbols[symbol]` 获取策略数据
- [x] 使用策略数据计算汇总统计

### 7.7 _persist_strategy_info()
- [x] 修改方法签名：`_persist_strategy_info(symbol: str)`
- [x] 从 `self.symbols[symbol]` 获取策略数据
- [x] 使用 `pos_id` 保存策略信息到 JSON 文件

### 7.8 _persist_order_to_csv()
- [x] 修改方法签名：`_persist_order_to_csv(symbol: str, order_record: dict, pos_id: int)`
- [x] 使用 `pos_id` 保存订单到 CSV 文件

---

## 任务 8：改造 get_status() 方法

### 8.1 修改方法签名
- [x] 修改 `get_status(symbol: Optional[str] = None)` 方法
- [x] 如果 `symbol` 为 `None`，返回所有策略的状态列表
- [x] 如果 `symbol` 指定，返回该 symbol 的状态

### 8.2 返回单个 symbol 状态
- [x] 从 `self.symbols[symbol]` 获取策略数据
- [x] 调用 `_calculate_summary(symbol)` 计算汇总
- [x] 格式化返回数据

### 8.3 返回所有 symbol 状态
- [x] 遍历 `self.symbols` 中的所有 symbol
- [x] 对每个 symbol 调用 `_calculate_summary(symbol)`
- [x] 返回策略列表，包含汇总统计

---

## 任务 9：改造 load_strategy() 方法

### 9.1 扫描策略文件
- [x] 扫描 `data/` 目录，查找所有 `*.json` 文件
- [x] 过滤出策略文件（根据文件内容判断）

### 9.2 加载策略数据
- [x] 读取每个 JSON 文件
- [x] 验证文件格式和必需字段
- [x] 提取 `symbol` 字段

### 9.3 处理重复 symbol
- [x] 如果同一 `symbol` 有多个策略文件，选择最新的（根据 `saved_at` 时间戳）
- [x] 记录警告日志

### 9.4 恢复策略状态
- [x] 将策略数据添加到 `self.symbols[symbol]`
- [x] 如果策略之前是运行状态，设置 `_status = True`
- [x] 调用 `start()` 方法恢复策略运行（可选，或等待手动启动）

---

## 任务 10：改造 app.py

### 10.1 保持单实例
- [x] 确认 `app.py` 中保持单个 `GridStrategy` 实例
- [x] 在 `lifespan` 函数中创建实例

### 10.2 修改 API 接口 - /api/start
- [x] 修改 `start_grid()` 接口，从 `params` 中提取 `symbol`
- [x] 调用 `strategy.start(params)` 启动策略
- [x] 返回成功响应

### 10.3 修改 API 接口 - /api/stop
- [x] 修改 `stop_grid()` 接口，支持可选的 `symbol` 参数
- [x] 如果提供 `symbol`，调用 `strategy.stop(symbol)`
- [x] 如果不提供，调用 `strategy.stop()` 停止所有

### 10.4 修改 API 接口 - /api/status
- [x] 修改 `get_status()` 接口，支持可选的 `symbol` 查询参数
- [x] 如果提供 `symbol`，调用 `strategy.get_status(symbol)`
- [x] 如果不提供，调用 `strategy.get_status()` 返回所有策略

---

## 任务 11：实现新的 API 接口

### 11.1 POST /api/strategies
- [x] 创建新接口，接收策略参数
- [x] 调用 `strategy.start(params)` 创建策略
- [x] 返回策略信息（包含 symbol）

### 11.2 GET /api/strategies
- [x] 创建新接口，获取所有策略列表
- [x] 调用 `strategy.get_status()` 获取所有策略
- [x] 返回策略列表和汇总统计

### 11.3 GET /api/strategies/{symbol}
- [x] 创建新接口，获取指定 symbol 的策略状态
- [x] 调用 `strategy.get_status(symbol)` 获取状态
- [x] 返回策略详细信息

### 11.4 POST /api/strategies/{symbol}/stop
- [x] 创建新接口，停止指定 symbol 的策略
- [x] 调用 `strategy.stop(symbol)` 停止策略
- [x] 返回成功响应

### 11.5 DELETE /api/strategies/{symbol}
- [x] 创建新接口，删除指定 symbol 的策略
- [x] 调用 `strategy.stop(symbol)` 停止策略
- [x] 从 `self.symbols` 中移除策略数据
- [x] 返回成功响应

---

## 任务 12：测试和验证

### 12.1 单元测试
- [ ] 测试 `start()` 方法：创建新 symbol 策略
- [ ] 测试 `start()` 方法：重复 symbol 检查
- [ ] 测试 `stop()` 方法：停止指定 symbol
- [ ] 测试 `stop()` 方法：停止所有 symbol
- [ ] 测试 `get_status()` 方法：获取单个和所有策略状态
- [ ] 测试 `load_strategy()` 方法：加载多个策略文件

### 12.2 集成测试
- [ ] 测试创建多个不同 symbol 的策略
- [ ] 测试同时运行多个策略
- [ ] 测试停止部分策略，其他策略继续运行
- [ ] 测试系统重启后自动加载策略

### 12.3 API 接口测试
- [ ] 测试所有 API 接口（/api/start, /api/stop, /api/status, /api/strategies/*）是否正常工作
- [ ] 测试不传 symbol 参数时的默认行为
- [ ] 测试单个策略的场景

### 12.4 错误处理测试
- [ ] 测试重复 symbol 启动时的错误处理
- [ ] 测试停止不存在的 symbol 时的错误处理
- [ ] 测试策略文件损坏时的加载处理
- [ ] 测试某个 symbol 出错不影响其他 symbol

---

## 任务 13：代码清理和优化

### 13.1 代码清理
- [x] 移除或注释掉不再使用的单 symbol 字段
- [x] 更新所有方法的文档字符串，说明 symbol 参数
- [x] 添加类型提示

### 13.2 日志优化
- [x] 在所有关键操作中添加日志，包含 symbol 信息
- [x] 确保日志格式统一，便于追踪问题

### 13.3 性能优化
- [x] 检查主循环的性能，确保多 symbol 时不会阻塞
- [x] 优化字典访问，避免重复查找
- [x] 考虑使用异步并发处理多个 symbol（如果需要）

---

## 完成标准

- [ ] 所有任务项已完成
- [ ] 代码通过单元测试和集成测试
- [ ] 代码审查通过
- [ ] 文档已更新

---

---

## 阶段二：前端核心功能

## 任务 14：创建策略列表视图组件

### 14.1 HTML 结构改造
- [x] 修改 `static/index.html`，将单策略卡片改为策略列表容器
- [x] 创建策略列表容器 `<div id="strategiesList">`
- [x] 创建策略列表项模板（使用 template 或 JavaScript 动态生成）
- [x] 保留统计信息概览区域（后续改造）

### 14.2 策略列表项设计
- [x] 每个列表项显示基本信息：
  - [x] 交易对（symbol）- 大字体，突出显示
  - [x] 方向（做多/做空）- 带颜色标识（做多绿色，做空红色）
  - [x] 杠杆倍数 - 显示为标签
  - [x] 运行状态 - 状态徽章（运行中/已停止）
  - [x] 当前价格 - 实时更新
  - [x] 盈亏情况 - 带颜色显示（盈利绿色，亏损红色）
  - [x] 操作按钮区域（启动/停止/删除/详情）

### 14.3 CSS 样式设计
- [x] 创建策略列表容器样式
- [x] 创建策略列表项卡片样式
- [x] 设计响应式布局（支持移动端）
- [x] 添加悬停效果和过渡动画
- [x] 设计状态徽章样式（运行中/已停止）

### 14.4 JavaScript 列表渲染
- [x] 创建 `renderStrategiesList(strategies)` 函数
- [x] 实现策略列表项模板渲染
- [x] 处理空列表状态（显示提示信息）
- [x] 实现列表项的创建、更新、删除操作

---

## 任务 15：改造统计信息，支持多策略汇总

### 15.1 统计信息数据结构
- [x] 创建 `calculateSummaryStats(strategies)` 函数
- [x] 计算总策略数：`strategies.length`
- [x] 计算运行中策略数：`strategies.filter(s => s.running).length`
- [x] 计算已停止策略数：`strategies.filter(s => !s.running).length`
- [x] 计算总投入资金：所有策略的 `investment_amount` 之和
- [x] 计算总盈亏：所有策略的 `summary.total_pnl` 之和
- [x] 计算总成交额：所有策略的 `summary.total_volume` 之和
- [x] 计算平均收益率：总盈亏 / 总投入资金

### 15.2 HTML 结构改造
- [x] 修改统计信息概览区域
- [x] 添加总策略数指标卡片
- [x] 添加运行中/已停止策略数指标卡片
- [x] 更新总投入资金显示（改为汇总值）
- [x] 更新总盈亏显示（改为汇总值）
- [x] 添加平均收益率指标卡片

### 15.3 统计信息更新逻辑
- [x] 修改 `updateStatistics()` 函数，接收策略列表
- [x] 调用 `calculateSummaryStats()` 计算汇总数据
- [x] 更新所有统计指标卡片
- [x] 处理空策略列表的情况（显示默认值）

### 15.4 实时更新机制
- [x] 在策略列表更新时同步更新统计信息
- [x] 确保统计信息与策略列表数据一致
- [x] 添加统计信息更新动画效果

---

## 任务 16：实现策略详情展开/收起

### 16.1 详情视图设计
- [x] 设计策略详情卡片布局
- [x] 详情内容包含：
  - [x] 策略基本信息（价格区间、网格间距、投资额等）
  - [x] 订单信息（买单、卖单）
  - [x] 持仓信息（持仓数量、持仓均价、未实现盈亏）
  - [x] 历史订单列表（最近 5 条）
  - [x] 统计信息（网格收益、套利次数、年化收益等）

### 16.2 展开/收起交互
- [x] 实现点击策略列表项展开详情
- [x] 添加展开/收起动画效果
- [x] 支持同时展开多个策略详情（或只允许展开一个）
- [x] 添加展开/收起图标指示器

### 16.3 详情数据渲染
- [x] 创建 `renderStrategyDetails(symbol, strategyData)` 函数
- [x] 从策略数据中提取详情信息
- [ ] 格式化显示订单信息、持仓信息等
- [x] 处理数据为空的情况（显示占位符）

### 16.4 详情实时更新
- [ ] 在策略状态更新时，同步更新已展开的详情
- [x] 实现详情内容的平滑更新动画
- [ ] 处理详情展开时策略被删除的情况

---

## 任务 17：实现策略的启动/停止/删除操作

### 17.1 启动策略功能
- [x] 修改启动策略按钮，支持创建新策略
- [x] 实现启动策略表单（复用现有配置表单）
- [ ] 添加 symbol 重复检查（调用 API 检查是否已存在）
- [x] 调用 `POST /api/strategies` 或 `POST /api/start` 创建策略
- [x] 启动成功后刷新策略列表
- [x] 显示启动成功/失败提示

### 17.2 停止策略功能
- [x] 为每个策略列表项添加停止按钮
- [x] 实现停止策略确认对话框
- [x] 调用 `POST /api/strategies/{symbol}/stop` 或 `POST /api/stop?symbol={symbol}` 停止策略
- [x] 停止成功后更新策略状态
- [x] 显示停止成功/失败提示

### 17.3 删除策略功能
- [x] 为每个策略列表项添加删除按钮
- [x] 实现删除策略确认对话框（警告提示）
- [x] 调用 `DELETE /api/strategies/{symbol}` 删除策略
- [x] 删除成功后从列表中移除策略项
- [x] 如果详情已展开，关闭详情视图
- [x] 显示删除成功/失败提示

### 17.4 批量操作（可选）
- [ ] 实现全选/取消全选功能
- [ ] 实现批量停止功能
- [ ] 实现批量删除功能
- [ ] 添加批量操作确认对话框

### 17.5 操作按钮状态管理
- [x] 根据策略运行状态显示/隐藏按钮
- [x] 运行中的策略：显示停止按钮，隐藏启动按钮
- [x] 已停止的策略：显示启动按钮，隐藏停止按钮
- [x] 所有策略：显示删除按钮
- [ ] 添加按钮加载状态（操作进行中时禁用）

---

## 任务 18：实现多策略状态轮询

### 18.1 轮询机制设计
- [x] 创建 `pollStrategiesStatus()` 函数
- [x] 调用 `GET /api/strategies` 获取所有策略状态
- [x] 设置轮询间隔（建议 3-5 秒）
- [x] 实现轮询的启动和停止控制

### 18.2 状态更新逻辑
- [x] 比较新旧策略列表，识别变化
- [x] 新增策略：添加到列表
- [x] 删除策略：从列表移除
- [x] 更新策略：更新列表项数据
- [ ] 实现增量更新，避免全量重新渲染（当前为全量重新渲染）

### 18.3 性能优化
- [ ] 实现防抖/节流机制，避免频繁更新
- [ ] 只在策略数据真正变化时更新 DOM
- [ ] 使用虚拟滚动（如果策略数量很多）
- [ ] 优化列表项渲染性能

### 18.4 错误处理和重试
- [x] 处理轮询请求失败的情况
- [ ] 实现指数退避重试机制
- [x] 显示连接错误提示
- [ ] 在连接恢复后自动恢复轮询

### 18.5 轮询控制
- [x] 页面可见时启动轮询
- [ ] 页面隐藏时暂停轮询（使用 Page Visibility API）
- [x] 页面卸载时清理轮询定时器
- [x] 提供手动刷新按钮

---

## 任务 19：改造现有单策略功能

### 19.1 单策略显示处理
- [ ] 检查现有单策略显示逻辑
- [ ] 如果只有一个策略，在列表中显示（统一使用列表视图）
- [ ] 确保所有功能在新架构下正常工作

### 19.2 配置表单改造
- [ ] 修改策略配置表单，确保支持多策略创建
- [ ] 添加 symbol 输入验证（检查是否已存在）
- [ ] 更新表单提交逻辑，调用新的 API 接口

### 19.3 状态管理改造
- [ ] 将全局 `currentStrategyStatus` 改为 `strategiesList` 数组
- [ ] 更新所有依赖单策略状态的代码
- [ ] 实现策略数据的统一管理（使用对象或 Map）

---

## 注意事项

1. **错误处理**：每个方法都要有完善的错误处理和日志记录
2. **数据一致性**：确保 `self.symbols` 字典中的数据始终一致
3. **线程安全**：如果涉及多线程，注意数据访问的线程安全
4. **性能考虑**：多 symbol 运行时，注意主循环的性能和资源占用
5. **前端性能**：多策略列表渲染时注意性能优化，避免频繁 DOM 操作
6. **用户体验**：确保操作反馈及时，加载状态清晰
7. **响应式设计**：确保多策略列表在不同屏幕尺寸下正常显示


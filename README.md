## MSX 网格交易系统

一个基于 **FastAPI + Playwright + Chrome DevTools** 的单策略网格交易系统，通过复用浏览器登录态直接调用交易所接口，实现 Web 端可视化配置与监控的网格策略。


### 环境准备

#### 1. 系统与 Python

- 推荐环境：
  - macOS / Windows
  - Python **3.10+**

#### 2. 浏览器与 DevTools 调试端口

本项目通过 **Chrome DevTools** 复用浏览器会话，需要：

#### macOS
- 使用自动化脚本方式启动
```bash
#!/bin/bash
open -na "/Applications/Google Chrome.app" --args \
  --user-data-dir="/Users/chrome_data/001" \
  --remote-debugging-port=9222
```

#### Windows
- 使用快捷方式启动
  1. 在桌面右键 → **新建 → 快捷方式**
  2. 目标填写（根据你的安装路径调整）：
     ```text
     "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chrome_data\001"
     ```
  3. 下一步，给快捷方式起一个名字（如：`msx_grid`），完成后双击该快捷方式即可。

3. 在该浏览器窗口中：
   - 打开交易网站https://msx.com
   - 连接钱包，保证正常访问账户
   - 进入合约交易页面（例如合约交易界面），确保页面正常加载一段时间  

4. 确认 `config/config.yaml` 中的 `cdp_url` 与实际端口一致（默认是 `http://localhost:9222`）。

---

### 安装依赖

建议在虚拟环境中安装。

```bash
git clone https://

# 可选：创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

> 说明：`requirements.txt` 中包含 `fastapi` 相关依赖通过框架内传递安装，请保证安装后没有缺失包。如果运行时报缺少 `fastapi` 或 `uvicorn`，手动安装：
>
> ```bash
> pip install "fastapi[all]" uvicorn
> ```

---

### 配置说明

配置文件位于：`config/config.yaml`，示例：

```yaml
cdp_url: http://localhost:9222

```
- **cdp_url**：Chrome DevTools 地址，需与浏览器启动时设置的端口一致。

---

### 启动后端服务

在项目根目录运行：

```bash
python app.py
```

默认会启动一个启用热重载的 Uvicorn 服务：

- 地址：`http://0.0.0.0:8000`
- 静态资源：`/static/*`

你也可以手动用 Uvicorn 启动：

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

---

### Web 控制台使用指南

1. **打开控制台**
   - 在浏览器中访问：`http://localhost:8000/`
   - 顶部展示系统名称与连接状态（已连接/未连接）

2. **检查连接状态**
   - 如果：
     - Chrome 已用 `--remote-debugging-port=9222` 启动
     - 并且已经登录交易网站且进入交易页面
   - 那么 `/api/status` 返回的 `connected` 会为 `true`，顶部状态会显示“已连接”。

3. **配置并启动策略**

   - 点击「启动策略」按钮，弹出配置对话框：
     - **市场类型**：
       - `合约 (Contract)`：支持杠杆, 自动适配相应杠杆
       - `现货 (Spot)`：暂时不支持
     - **交易对**：
       - 输入或下拉选择，如 `AAPL`、`ETHUSDT` 等
       - 前端会通过 `/api/symbols?market_type=...` 获取列表并进行模糊匹配
     - **交易方向（合约）**：
       - `做多 (Long)` / `做空 (Short)`
     - **杠杆倍数（合约）**：
       - 支持滑杆 + 数字输入联动
       - 对于合约交易对，系统会根据后台返回的 `leverTypes` 动态设置允许的最小 / 最大杠杆
     - **价格区间**：
       - 最低价格 `min_price`
       - 最高价格 `max_price`
     - **网格数量**：
       - 至少 2
       - 前端会根据价格区间与网格数计算网格间距：
         \[
         grid\_spacing = \frac{max\_price - min\_price}{grid\_count \times \frac{min\_price + max\_price}{2}}
         \]
     - **投资额**：
       - 以 USD/USDT 为单位，例如 `1000`，实际总仓位 = 投资额 × 杠杆倍数

### 开发与调试建议

- **策略逻辑扩展**
  - 所有网格逻辑集中在 `msx/grid.py` 的 `GridStrategy` 中：
    - 想改变建仓规则、网格间距算法、止盈止损策略，可以从这里入手。

- **交易接入调试**
  - `msx/exchange.py` 中有大量日志（建议开启 `verbose=True` 以及 `loguru` 日志级别调试），方便排查：
    - 授权头是否抓到
    - 请求是否被频控 / 拒绝（code 1006 等）
    - K 线 / 持仓 / 订单数据解析是否正确

- **风控提示**
  - 本项目仅为技术实验性质示例代码：
    - 请务必在 **模拟环境 / 小额资金** 下测试
    - 确认每一笔下单逻辑符合你的预期后，再考虑使用到真实环境
    - 建议增加：最大持仓限制、最大亏损停止、黑名单时段等额外风控规则

---

### 常见问题（FAQ）

1. **`/api/status` 提示「交易所实例未初始化」？**
   - 检查 `app.py` 是否正常启动，以及 `config/config.yaml` 是否存在并能被读取。
   - 检查 `cdp_url` 是否正确，Chrome 是否 **已用调试端口启动**。

2. **`/api/start` 返回「账户余额不足」等错误？**
   - 确认账户内余额是否 >= 投资额（保证金）。
   - 网格数量过多 / 价格区间过宽会导致每单金额超过或低于最小要求，适当缩小价格区间或减少网格数。

3. **页面显示「未连接」？**
   - 确保 Chrome 是通过 `--remote-debugging-port=9222` 启动的，而不是普通方式。
   - 确认 `config.yaml` 中的 `cdp_url` 与实际端口一致。
   - 确认已登录交易网站且浏览器里有正常的网络请求发往交易 API 域名。

---

如本项目对你有帮助，欢迎捐赠支持（非必需）：  
SOL 捐赠地址：`2PrHdxX8uBwqDMqySsxKp5FbK2tmE3yrqcRXaG6BwKjj`

### 免责声明

本项目仅用于技术研究与学习示例，不构成任何投资建议。  
使用本项目进行实盘交易可能导致资金损失，请在完全理解代码逻辑、并自行评估风险后再使用。作者与贡献者不对任何损失负责。  





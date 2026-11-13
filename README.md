<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="CigarMonitor：本地雪茄库存监控工具，缺货转有货立即邮件、系统通知与微信提醒">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.2.0-2563EB" alt="version 1.2.0">
  <img src="https://img.shields.io/badge/python-3.x-3776AB" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-10B981" alt="license MIT">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4" alt="platform windows">
</p>

## 这是什么

CigarMonitor 是一个**本地部署的雪茄库存监控工具**：把商品页网址丢进去，它会在后台定时检查库存，一旦从「缺货」变成「有货」，立即发邮件、弹出 Windows 系统通知，并推送到你的微信。全部数据保存在自己电脑上，无需公网服务器，也不向第三方上传数据。

提供桌面应用（推荐）与浏览器版两种使用方式。

## 界面预览

<table>
  <tr>
    <td width="33%">
      <img src="./assets/readme/shot-main.png" width="100%" alt="主界面与监控列表，缺货状态一目了然">
    </td>
    <td width="33%">
      <img src="./assets/readme/shot-search.png" width="100%" alt="中文搜索与品牌标签，搜威古洛即可找到对应商品">
    </td>
    <td width="33%">
      <img src="./assets/readme/shot-filter.png" width="100%" alt="品牌标签在英文后标注中文，支持按品牌与有货筛选">
    </td>
  </tr>
  <tr>
    <td align="center"><b>监控总览</b></td>
    <td align="center"><b>中文搜索</b></td>
    <td align="center"><b>品牌筛选</b></td>
  </tr>
</table>

<details>
<summary>查看「监控总览」大图</summary>
<img src="./assets/readme/shot-main.png" alt="主界面与监控列表，缺货状态一目了然">
</details>

<details>
<summary>查看「中文搜索」大图</summary>
<img src="./assets/readme/shot-search.png" alt="中文搜索与品牌标签，搜威古洛即可找到对应商品">
</details>

<details>
<summary>查看「品牌筛选」大图</summary>
<img src="./assets/readme/shot-filter.png" alt="品牌标签在英文后标注中文，支持按品牌与有货筛选">
</details>

## 功能特性

- **定时巡检**：添加网址即自动识别商品名并完成首次检查，默认每 5 分钟轮询（界面可调，最小 30 秒）
- **有货提醒**：仅在「缺货 → 有货」时触发，系统托盘 / 邮件 / 微信三路同时发送，互不阻塞，任一成功即算已提醒，不重复刷屏；**没有开关**，配置完即自动生效
- **微信通知（免费）**：内置微信官方 ClawBot 通道，扫一次码即可用。不注册第三方推送平台、不填 API Key、不新增 Python 依赖、全程 0 元
- **中文搜索**：内置 34 个雪茄品牌的中英文词库，简称、全称都认；品牌标签在英文后标注中文
- **到手计算器**：支持 8 种货币，海关计征汇率取中国货币网官方中间价（每月更新）、实时市场汇率自动获取并本地缓存；按 50% 烟草综合税率计算到手总价与单支，自动判断免征区间，计税价超 2000 元提示寄递限值/退运风险，断网可回退缓存
- **本地优先**：数据存本机 SQLite，关闭窗口即缩到托盘继续运行，不依赖公网服务器
- **自动更新**：后台静默检测新版本，一键下载整包并镜像替换、自动重启；用户数据独立存放，更新不丢失
- **多邮箱预设**：QQ、163、126、Gmail、Outlook，另支持自定义 SMTP

## 工作原理

<p align="center">
  <img src="./assets/readme/workflow.svg" width="100%" alt="工作流程：粘贴网址、定时巡检、解析状态、立即通知">
</p>

未知站点会先读取页面结构化库存数据（JSON-LD），再用多语言关键词（in stock / add to cart / ausverkauft / rupture de stock 等）兜底判断。

## 快速开始

### 桌面版（推荐）

1. 到 [Releases](https://github.com/hoho77777/cigar-monitor/releases) 下载安装包 `CigarMonitor_v1.2.0_setup.exe` 双击安装（自动建桌面快捷方式）；也可下载免安装的 `CigarMonitor_v1.2.0_windows.zip` 解压使用，整包包含 `CigarMonitor.exe` 与 `_internal`，两者必须放在一起，不要只移动 exe
2. 双击 `CigarMonitor.exe`，稍候弹出原生窗口
3. （可选）在「微信通知 · ClawBot」点「扫码绑定微信」，手机微信扫一次即可，无需任何账号或 API Key
4. 在「发信邮箱与监控设置」填入邮箱账号和 **SMTP 授权码**，保存后可点「发送测试邮件」；只想要微信通知可跳过
5. 顶部粘贴商品网址即可添加监控，列表默认空，由你自行添加

**系统托盘行为**：点关闭按钮（×）不会退出，窗口隐藏并转入后台继续监控；点击托盘图标恢复窗口，右键可选择「显示主窗口」或「退出」，只有托盘菜单的「退出」才会真正结束程序。

> 桌面版依赖 Microsoft Edge WebView2 运行时，Windows 10/11 通常已预装；若窗口无法打开，可在微软官网免费安装「Microsoft Edge WebView2 Runtime」。

### 浏览器版

1. 双击 `start.bat`（首次运行自动安装依赖）
2. 浏览器打开 `http://127.0.0.1:5050`，在设置区填入邮箱与授权码
3. 关闭命令行窗口即停止监控；保持窗口开着即可持续运行

## 邮箱授权码获取

- **QQ 邮箱**：网页版「设置 → 账号」开启「IMAP/SMTP 服务」，按提示验证后获得 16 位授权码（非登录密码）
- **163 / 126 邮箱**：网页版「设置 → POP3/SMTP/IMAP」开启 SMTP 并获取客户端授权码
- **Gmail**：开启两步验证后使用「应用专用密码」
- 选择对应预设后，SMTP 主机、端口、加密方式会自动填充，一般无需手动修改

## 微信通知（ClawBot）

完全免费，走微信官方 ClawBot 通道（iLink 协议）直连，**不经过任何第三方推送平台**。

### 配置步骤

1. 手机微信升级到最新版，进入「我 → 设置 → 插件」启用 **ClawBot**（灰度中，若没有入口说明暂未放量）
2. 软件里展开「发信邮箱与监控设置」卡片（顶部铃铛图标可直接跳转），在下方「微信通知 · ClawBot」区块点「扫码绑定微信」
3. 用手机微信扫描界面上的二维码并确认；若手机提示配对数字，填进界面上的输入框
4. 状态变为「已绑定」后，**在微信里给 ClawBot 发任意一条消息**——这是必须的一步，iLink 要求 bot 先拿到来自你的会话上下文才能主动下发
5. 界面会自动变为「通道就绪」，此时点「发送测试微信」验证

绑定后，每次「缺货 → 有货」都会把商品名、状态、检查时间和可点击的商品链接推到微信 ClawBot 对话。

### 免费与依赖

| 项目 | 说明 |
|---|---|
| 费用 | 0 元，无订阅、无条数计费 |
| 第三方平台 | 不用注册 Server酱 / PushPlus / 企业微信，不用申请 API Key |
| 服务器 | 无需公网 IP、内网穿透或云服务器 |
| 依赖 | 复用已有 `requests`，未新增 pip 包；二维码由随包本地 JS 生成，离线可用 |

### 重要限制

- ClawBot 本质是「你与自己的机器人对话」通道，**不是通知推送 API**：bot 主动下发受微信侧 **24 小时 / 最多 10 条**窗口限制，且需要你在此期间给 bot 发过消息。
- 程序会在后台持续维护会话；长时间不互动时，在微信里给 ClawBot 发任意一条消息即可恢复。
- 窗口过期时微信这条会失败并在「检查日志」里单独记录，**邮件与系统通知不受影响**（三路独立派发，任一成功即算已提醒）。
- iLink 为微信非公开接口且仍在灰度，微信侧策略调整可能影响可用性。

> 通知渠道**没有开关**，配置即启用：系统托盘常开；SMTP 主机/账号/授权码/收件人填齐后自动发邮件；扫码绑定微信后自动推送。未配置的一路静默跳过，不产生失败日志。邮件与微信的配置都在「发信邮箱与监控设置」这一张卡片内完成。

## 支持站点与判断逻辑

| 站点 | 判断方式 |
|---|---|
| cigars-of-cuba.com | 页面 `stock-availability` 区块：Out of Stock / In Stock |
| cigarone.com | 加购按钮是否禁用（disabled = 缺货） |
| c-cigars.de | 结构化数据 schema.org/SoldOut 与 InStock |
| alpscigar.com | 模拟浏览器指纹绕过 Cloudflare，读取 WooCommerce 库存与结构化数据 |

其他网站直接粘贴网址即可，工具会自动按结构化数据 + 多语言关键词判断。

## 从源码构建

仓库不包含二进制文件（图标、exe、数据库均通过 `.gitignore` 排除）。

1. 安装依赖：`pip install -r requirements.txt`
2. 生成图标：`python make_icons.py`（有源图则从源图生成，无源图自动绘制「深色圆角底 + 金雪茄」默认图标）
3. 打包：直接运行 `build.bat`（缺图标时会先自动执行上一步）

首次启动默认不预置任何监控项；如需预置，可在 `seed/products.json` 中加入条目。

**开机自启**：按 `Win + R` 输入 `shell:startup`，把 `CigarMonitor.exe` 的快捷方式拖入启动文件夹即可后台静默运行。

## 数据与安全

- 浏览器版数据存于 `data/monitor.db`；桌面版存于 `%LOCALAPPDATA%\CigarMonitor\data\monitor.db`
- 邮箱授权码仅保存在本机，不上传任何第三方
- ClawBot 的 bot_token 与会话 token 只存本机 SQLite 的 settings 表，不写日志、不上传；点「解绑」即清除
- 公开仓库只含源码与纯文本种子，不含邮箱、授权码、地址、数据库、图标、exe 等个人数据或二进制资产
- 监控请求模拟普通浏览器访问，请合理设置检查频率，避免对目标站点造成压力

## 常见问题

- **测试邮件发不出去**：确认授权码正确、SMTP 服务已开启，主机/端口/加密保持对应预设
- **刚绑定点测试就报 `[-2] prepare failed`**：不是绑定失败，也不是窗口过期，而是微信侧还没有你的消息、会话未激活。去微信里给 ClawBot 发任意一条消息，等界面显示「通道就绪」再测；新版会直接给出这一步提示，不再抛技术错误码
- **微信收不到提醒**：无需任何开关，确认状态为「通道就绪」；长时间未互动导致窗口过期时，在微信里再发一条消息即可恢复，界面状态会自动刷新
- **扫码时一直等待 / 提示配对码**：手机微信需为最新版并启用 ClawBot 插件；提示配对数字时填进界面输入框再提交；二维码 5 分钟有效，过期请重新扫码
- **找不到 ClawBot 插件入口**：功能仍在灰度放量，可先用邮件 + 系统通知，等入口出现后再扫码绑定
- **商品显示「未知」**：多为网络或反爬拦截，日志里有原因；Cloudflare 站点会自动重试，仍失败可降低检查频率
- **端口被占用**：桌面版会从 5050 起自动寻找可用端口，无需手动处理
- **自动更新**：仅在桌面打包版生效，整包镜像替换安装目录；数据库与设置位于 `%LOCALAPPDATA%` 独立目录，不会被改动，失败时静默跳过

## License

本项目基于 [MIT License](./LICENSE) 开源，可自由使用、修改与分发，请保留原始版权声明。

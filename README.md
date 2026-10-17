# Kaadas 凯迪仕门锁 Home Assistant 集成

通过凯迪仕 App 的云端接口，把凯迪仕 Wi-Fi 猫眼门锁接入 Home Assistant，并可桥接到 Apple HomeKit 作为原生视频门铃。

已在 **K20 Max Plus**（凯迪仕 App 6.19.3、Home Assistant 2026.9）上验证。其他使用同一套 App 接口的 Wi-Fi 门锁可能也能用。

> 本集成**只读**：只轮询云端记录，不包含任何开锁、上锁或修改设置的接口。

## 功能

| 实体 | 说明 |
|---|---|
| `camera` 门口抓拍 | 最近一次门铃或徘徊的抓拍图（只有图片，没有视频流） |
| `event` 门铃 | 有人按门铃（记录 type 96），设备类型 doorbell |
| `event` 徘徊报警 | 人脸徘徊报警（type 113），设备类型 motion |
| `event` 开关锁 | 开锁 / 上锁，属性里带开锁方式（指纹、感应把手……）和用户编号 |
| `event` 门锁报警 | 锁舌未能完全伸出/收回（type 32）等 |
| `lock` 门锁 | 根据最近一条开/关锁记录显示状态；开关锁请求一律拒绝 |
| `sensor` | 电量、最近动态、最近开锁人、最近开锁/门铃/徘徊时间、Wi-Fi、固件版本 |

- 新记录按 id 去重，并持久化保存：重启后不会重复推送，重启期间来的门铃会补发；超过 15 分钟的旧记录不触发事件。
- 抓拍图缓存在内存里，不写到 `/config/www`（凯迪仕的抓拍图链接无需鉴权，写进公开目录等于公开门口照片）。
- token 失效时 HA 会提示重新认证，填入新 token 即可；换成另一个账号时把 uid 一起改掉。手机 App 重新登录（包括退出账号）会让旧 token 失效，此时接口返回 `code=455`。

## 安装

1. 把 `custom_components/kaadas` 复制到 HA 配置目录的 `custom_components/` 下（或在 HACS 中添加本仓库为自定义集成仓库）。
2. 重启 Home Assistant。
3. 「设置 → 设备与服务 → 添加集成」，搜索 **Kaadas**。
4. 填入抓包得到的：
   - **Token**：任意 `app.kaadas.com:34000` 请求的请求头 `token`
   - **uid**：`/app/user/findAllBindDevice` 请求体里的 `uid`

   账号下的门锁会自动列出。

### 抓包

推荐 iPhone 上的 [Stream](https://apps.apple.com/cn/app/stream/id1312141691)：

1. 在 Stream 中安装 CA 证书，然后到「设置 → 通用 → 关于本机 → 证书信任设置」里**打开完全信任**（漏掉这一步只能抓到 `CONNECT`，看不到内容）。
2. 开始抓包，打开凯迪仕 App 的设备页、开锁记录、访客记录。
3. 在抓包历史里找 `app.kaadas.com` 的请求。

### 选项

| 选项 | 默认 | 说明 |
|---|---|---|
| 记录轮询间隔 | 30 秒 | 每次轮询请求 3 个接口 |
| 设备信息刷新间隔 | 600 秒 | 电量、固件等 |
| 抓拍图旋转 | 90° | 猫眼竖装时原图是横的，由阿里云 OSS 在服务端顺时针旋转 |
| 实时推送（MQTT） | 关 | 见下文 |

### 实时推送（MQTT）

打开后连接凯迪仕云端 MQTT（`appmq.kaadas.com:5883`），收到本门锁的事件就立刻轮询，并在 30 秒内每 3 秒轮询一次。带抓拍图的门铃、徘徊事件会等新图下载好再触发（最多等 25 秒），保证 HomeKit 通知里是这次的照片。轮询始终作为兜底。

⚠️ MQTT 客户端 ID 固定为 `app:{uid}`，和手机 App 相同：同一账号的 App 开在前台时，两边会每隔几秒互相挤掉，App 关掉后恢复稳定。可以注册一个新账号，把门锁分享给它专门给 HA 用，但这个账号不要在手机上保持登录，也不要在抓到 token 后退出登录（退出会让 token 失效），最好用一台闲置设备登录它。连接参数参考了 [alexlee728/ha-kaadas](https://github.com/alexlee728/ha-kaadas)（MIT）。

## 接入 Apple HomeKit

用 HA 自带的 HomeKit Bridge：

- 把 `camera` 门口抓拍和 `lock` 门锁加入一个 HomeKit 实例。HomeKit Bridge 会自动把同一设备的**门铃事件**、**徘徊事件**、**电量**关联到摄像头上，在「家庭」App 里显示为**视频门铃**：按门铃时推送带抓拍图的门铃通知，HomePod 响铃；徘徊时推送"检测到移动"。
- HA 推荐摄像头和门锁使用单独的 accessory 模式实例。若要放进已有的桥接，需要桥接的 `exclude_accessory_mode` 为 `false`，HA 会在日志里给出性能警告。
- 门锁也会被自动关联门铃，导致一次按门铃收到两条通知。可在 HomeKit 的 `entity_config` 里给门锁设置 `linked_doorbell_sensor: ""` 取消。
- 门锁在「家庭」App 里只读：点开锁会被拒绝，并在 1 秒内恢复原状态，不会卡在"正在开锁"。

## 限制

- **没有实时画面和录像**：凯迪仕的视频走 P2P 私有协议，抓包中没有 HTTP 播放接口。
- **不能远程开关锁**。
- 通知有延迟：凯迪仕云端上传抓拍图需要十几秒；不开实时推送时还要加上轮询间隔。
- 需要手动抓包获取 token。

接口和字段说明见 [docs/api-notes.md](docs/api-notes.md)。

## 开发

```bash
uv venv -p 3.14 .venv
uv pip install -p .venv/bin/python "homeassistant==2026.9.2" pytest-homeassistant-custom-component PyTurboJPEG
.venv/bin/python -m pytest
```

测试数据来自真实抓包（已脱敏），位于 `tests/fixtures/responses.json`。

## 致谢

- 思路来自瀚思彼岸 [@starxxxw](https://bbs.hassbian.com/home.php?mod=space&uid=48929) 的帖子 [《凯迪仕门锁通过APP抓包方式接入HA》](https://bbs.hassbian.com/thread-24121-1-1.html)
- 原始集成：[MF-142/kaadas](https://github.com/MF-142/kaadas)
- 报警抓拍思路参考：[xiangbingxi/kaadas-doorlock-homeassistant-nodered](https://github.com/xiangbingxi/kaadas-doorlock-homeassistant-nodered)

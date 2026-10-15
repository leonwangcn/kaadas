# 凯迪仕 K20 Max Plus 云端接口笔记

来源：2026-10-13 iPhone Stream 抓包，凯迪仕 App 6.19.3（iOS）。敏感值已打码。

## 通用

- Base URL：`https://app.kaadas.com:34000`
- 方法：POST，`Content-Type: application/json`
- 响应：`{"code":200,"msg":"成功","data":...}`（`opencount` 的 code 是字符串 `"200"`）
- 请求头（App 实际发送）：

| Header | 示例 | 说明 |
|---|---|---|
| `token` | `***` | 登录凭据，抓包获取 |
| `ver` | `20230913` / `20230412` | 接口版本，按接口不同 |
| `reqSource` | `app` | |
| `lang` | `zh_CN` | |
| `User-Agent` | `KaadasLock/6.19.3 (iPhone; iOS 27.0.1; Scale/3.00)` | |
| `phoneName` / `terminalModel` | `iPhone 17` | |
| `terminalName` | `iPhone` | |
| `clientAPPVersion` | `6.19.3.8` | 6.19 新增 |
| `clientOSVersion` | `27.0.1` | 6.19 新增 |
| `uniqueCode` | `***`（UUID） | 6.19 新增，设备标识 |

## 接口

### 开锁记录 `/app/record/operation/list`（ver 20230913）
请求：`{"wifiSN":"K2M***","page":1}`，每页 10 条，按时间倒序。

| type | 含义 | 关键字段 |
|---|---|---|
| 1 | 开锁 | `pwdType`、`pwdNum`、`userNickname`、`textContent` |
| 2 | 门已上锁 | — |

已观察到的 `pwdType`：

| pwdType | 含义 | pwdNum 示例 |
|---|---|---|
| 4 | 指纹 | 1（"编号01"） |
| 11 | 感应把手（室内） | 106 |

密码、人脸、卡片、钥匙的 `pwdType` 暂未观察到。

### 最近 5 条 `/app/record/operation/latest-five`（ver 20230913）
请求：`{"wifiSN":"K2M***"}`。字段同上，多一个 `recordType: "operation"`，没有 `id`。适合轻量轮询。

### 门铃记录 `/app/record/operation/visit`（ver 20230913）
请求：`{"wifiSN":"K2M***","page":1}`

| type | 含义 |
|---|---|
| 96 | 有人按门铃 |

### 报警记录 `/app/record/operation/alarm`（ver 20230913）
请求：`{"wifiSN":"K2M***","page":1}`

| type | 含义 | 有图 |
|---|---|---|
| 113 | 人脸徘徊报警 | 有 |
| 32 | 锁舌未能完全伸出/收回 | 无 |

### 门铃和报警记录的公共字段

- `id` / `_id`：记录 ID
- `eventId`：事件 ID（有图的记录才有）
- `time`：事件时间，Unix 秒。**以它为准**
- `startTime`：毫秒，比 `time` 多 8 小时（北京时间被当成 UTC 存储），不要用
- `thumbUrl`：`https://kds-alarm.oss-cn-shenzhen.aliyuncs.com/{wifiSN}/{eventId}.jpg`
  - 不带签名，**无需鉴权即可访问**
  - 实际是 640×360 的 JPEG（`width`/`height` 字段写的是 1920×1080，指的是视频分辨率）
- `vedioTime`（原文拼写）：录像时长 8～9 秒；`fileDate`/`fileName`：录像文件的本地日期和时间
- 同一时刻可能同时产生门铃（visit）和徘徊（alarm）两条记录，`eventId` 不同

### 设备信息 `/app/user/findAllBindDevice`（ver 20230412）
请求：`{"uid":"***","modelSearchType":2}`。设备在 `data.wifiList[]` 中。

| 字段 | 示例 | 用途 |
|---|---|---|
| `wifiSN` | `K2M***` | 设备主键 |
| `lockNickname` | 我的家 | 设备名 |
| `productModel` / `device_model` | K20FV / K10V02P | 型号 |
| `power` | 31 | 电量 % |
| `openStatus` / `open_status` | 1 | 门锁状态（含义待确认） |
| `open_lock_time_stamp` | 秒 | 最近开锁时间 |
| `hoverAlarm` / `hoverAlarmLevel` | 1 / 2 | 徘徊报警开关和灵敏度 |
| `setPir` | `{stay_time:10, pir_sen:35}` | 逗留判定 |
| `wifiName` | | 所连 Wi-Fi |
| `camera_version` / `wifiVersion` / `mcu_version` / `frontPanelVersion` / `backPanelVersion` / `faceVersion` | | 固件版本 |
| `keep_alive_status` | 1 | 猫眼保活 |
| `isAdmin` | 0 | 当前账号是否为管理员 |

`data.productInfoList[]` 中有 `abbreviation: "K20 Max Plus"`、`pictureRotation: "0"`、`videoType: "wifi长连接,传视频流"`。

⚠️ `pictureRotation` 不可信：K20 Max Plus 的猫眼是竖装的，抓拍原图是横的，要顺时针转 90° 才是正的。集成用 OSS 参数 `?x-oss-process=image/rotate,90` 让服务端旋转。

响应中含 `p2p_password`、`randomCode` 等敏感字段，不要记录到日志。

### 今日统计 `/app/ble/statistics/day`（ver 20230913）
请求：`{"uid":"***","wifiSN":"K2M***"}`。返回各开锁方式的今日次数（`fingerprintOpenLockCount`、`handleOpenLockCount`、`doorbellCount`……）。

### 唤醒猫眼 `/app/video/wakeupDspVideo`（ver 20230913）
请求：`{"sn":"K2M***"}`。返回 `deviceState`（如 `Offline`）和一条通过 MQTT 下发的 `wakeup` 指令。实时视频和录像回放走 P2P，抓包里没有 HTTP 播放接口，**集成暂不支持视频**。

## 不相关的接口
`/acm/banners/find`、`/shop/*`、`/app/oms/customer-service/one`、`/app/wechat/saveData`、`/app/wifi/device/setUserParam`（App 弹窗设置）、`/wifi/operation/opencount`（请求体是加密的）。

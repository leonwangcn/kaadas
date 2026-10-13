"""凯迪仕门锁集成常量。字段与类型码来自凯迪仕 App 6.19.3 抓包。"""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "kaadas"

PLATFORMS: list[Platform] = [
    Platform.CAMERA,
    Platform.EVENT,
    Platform.LOCK,
    Platform.SENSOR,
]

CONF_TOKEN = "token"
CONF_UID = "uid"
CONF_WIFI_SN = "wifi_sn"
CONF_USER_AGENT = "user_agent"
CONF_PHONE_NAME = "phone_name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_INFO_INTERVAL = "info_interval"
CONF_IMAGE_ROTATION = "image_rotation"

DEFAULT_USER_AGENT = "KaadasLock/6.19.3 (iPhone; iOS 27.0.1; Scale/3.00)"
DEFAULT_PHONE_NAME = "iPhone"
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_INFO_INTERVAL = 600
MIN_SCAN_INTERVAL = 10

# 猫眼是竖着装的，抓拍原图是横的，顺时针转 90° 才是正的（设备信息里的 pictureRotation 写的是 0，不可信）
DEFAULT_IMAGE_ROTATION = 90
IMAGE_ROTATIONS = (0, 90, 180, 270)

API_BASE_URL = "https://app.kaadas.com:34000"

# (路径, 请求头 ver)
ENDPOINT_OPERATIONS = ("/app/record/operation/list", "20230913")
ENDPOINT_VISITS = ("/app/record/operation/visit", "20230913")
ENDPOINT_ALARMS = ("/app/record/operation/alarm", "20230913")
ENDPOINT_DEVICES = ("/app/user/findAllBindDevice", "20230412")

# 开锁记录 type
OP_TYPE_UNLOCK = 1
OP_TYPE_LOCK = 2

# 开锁记录 pwdType -> 开锁方式；未列出的按 "other" 处理，原始值放在事件属性里
PWD_TYPE_METHODS: dict[int, str] = {
    4: "fingerprint",
    11: "handle",
}

# 门铃记录 type
VISIT_TYPE_DOORBELL = 96

# 报警记录 type
ALARM_TYPE_LOITERING = 113
ALARM_TYPE_BOLT_JAMMED = 32

# 记录时间早于这个秒数的，视为历史记录，只标记已读，不触发事件
EVENT_MAX_AGE = 15 * 60

# 每类记录最多记住多少个已处理的 id
SEEN_IDS_LIMIT = 200

STORAGE_VERSION = 1

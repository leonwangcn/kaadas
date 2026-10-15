"""凯迪仕云端 MQTT 推送。

只用来"敲门"：收到本门锁的事件就让 coordinator 立刻轮询，事件判断、去重和抓拍图
仍然走 HTTP 那一套。连接参数参考 alexlee728/ha-kaadas（MIT）。

注意：客户端 ID 固定为 app:{uid}，和手机 App 相同，同一账号两边同时在线会互相挤掉。
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt
from homeassistant.core import HomeAssistant, callback

from .const import MQTT_HOST, MQTT_KEEPALIVE, MQTT_PORT

_LOGGER = logging.getLogger(__name__)

TOPICS = ("/{uid}/rpc/reply", "/kiot/{uid}/app/down")

# CONNACK 4/5：用户名密码错误 / 未授权
_AUTH_FAILURE_CODES = {4, 5, 134, 135}


def parse_event(payload: bytes, wifi_sn: str) -> str | None:
    """本门锁的 wfevent 返回 eventtype，其他消息返回 None。"""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("func") != "wfevent":
        return None
    params = data.get("eventparams") if isinstance(data.get("eventparams"), dict) else {}
    if wifi_sn not in (data.get("wfId"), params.get("sn")):
        return None
    return str(data.get("eventtype") or "")


class KaadasPush:
    """paho 在自己的线程里跑网络循环，回调都转回 HA 的事件循环处理。"""

    def __init__(
        self,
        hass: HomeAssistant,
        uid: str,
        token: str,
        wifi_sn: str,
        on_event: Callable[[str], None],
    ) -> None:
        self._hass = hass
        self._uid = uid
        self._token = token
        self._wifi_sn = wifi_sn
        self._on_event = on_event
        self._client: mqtt.Client | None = None
        self.connected = False

    async def async_start(self) -> None:
        await self._hass.async_add_executor_job(self._start)

    async def async_stop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await self._hass.async_add_executor_job(_stop, client)
        self.connected = False

    def _start(self) -> None:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"app:{self._uid}",
            clean_session=False,
        )
        client.username_pw_set(self._uid, self._token)
        client.reconnect_delay_set(5, 300)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
        client.loop_start()
        self._client = client

    # 以下回调在 paho 线程里执行

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            self._call_soon(self._handle_connect_failure, reason_code.value, str(reason_code))
            return
        client.subscribe([(topic.format(uid=self._uid), 1) for topic in TOPICS])
        self._call_soon(self._set_connected, True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        self._call_soon(self._set_connected, False)

    def _on_message(self, client, userdata, message) -> None:
        _LOGGER.debug("MQTT %s: %s", message.topic, message.payload[:300])
        if (event_type := parse_event(message.payload, self._wifi_sn)) is not None:
            self._call_soon(self._on_event, event_type)

    def _call_soon(self, func: Callable[..., Any], *args: Any) -> None:
        # HA 关闭时事件循环已经停了
        with contextlib.suppress(RuntimeError):
            self._hass.loop.call_soon_threadsafe(func, *args)

    # 以下在 HA 事件循环里执行

    @callback
    def _set_connected(self, connected: bool) -> None:
        if connected != self.connected:
            _LOGGER.info("凯迪仕实时推送%s", "已连接" if connected else "已断开，稍后自动重连")
        self.connected = connected

    @callback
    def _handle_connect_failure(self, code: int, reason: str) -> None:
        if code in _AUTH_FAILURE_CODES:
            _LOGGER.warning("凯迪仕实时推送认证失败（%s），请检查 token；将继续用轮询", reason)
        else:
            _LOGGER.debug("凯迪仕实时推送连接失败：%s", reason)


def _stop(client: mqtt.Client) -> None:
    client.disconnect()
    client.loop_stop()

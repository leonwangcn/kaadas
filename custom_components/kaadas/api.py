"""凯迪仕 App 云端接口客户端。"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    API_BASE_URL,
    ENDPOINT_ALARMS,
    ENDPOINT_DEVICES,
    ENDPOINT_OPERATIONS,
    ENDPOINT_VISITS,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = ClientTimeout(total=15)

# 抓包里没见过 token 失效时的返回，先按常见写法判断，原始 code/msg 会写进日志方便后续校正
_AUTH_HTTP_STATUS = {401, 403}
_AUTH_MSG_KEYWORDS = ("token", "登录", "失效", "过期", "授权")


class KaadasError(Exception):
    """凯迪仕接口错误。"""


class KaadasAuthError(KaadasError):
    """token 失效或无权限。"""


class KaadasApi:
    """凯迪仕 App 接口。只读，不包含任何控制门锁的接口。"""

    def __init__(
        self,
        session: ClientSession,
        token: str,
        uid: str,
        user_agent: str,
        phone_name: str,
    ) -> None:
        self._session = session
        self._token = token
        self._uid = uid
        self._user_agent = user_agent
        self._phone_name = phone_name

    def _headers(self, ver: str) -> dict[str, str]:
        return {
            "token": self._token,
            "ver": ver,
            "reqSource": "app",
            "lang": "zh_CN",
            "phoneName": self._phone_name,
            "terminalName": "iPhone",
            "terminalModel": self._phone_name,
            "User-Agent": self._user_agent,
            "Content-Type": "application/json",
        }

    async def _post(self, endpoint: tuple[str, str], payload: dict[str, Any]) -> Any:
        path, ver = endpoint
        try:
            async with self._session.post(
                f"{API_BASE_URL}{path}",
                json=payload,
                headers=self._headers(ver),
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in _AUTH_HTTP_STATUS:
                    raise KaadasAuthError(f"{path}: HTTP {resp.status}")
                if resp.status != 200:
                    raise KaadasError(f"{path}: HTTP {resp.status}")
                body = await resp.json(content_type=None)
        except (TimeoutError, ClientError, ValueError) as err:
            raise KaadasError(f"{path}: {err!r}") from err

        if not isinstance(body, dict):
            raise KaadasError(f"{path}: 响应不是 JSON 对象")

        code = str(body.get("code"))
        if code == "200":
            return body.get("data")

        msg = str(body.get("msg", ""))
        _LOGGER.debug("%s 返回 code=%s msg=%s", path, code, msg)
        if code in {"401", "403"} or any(k in msg.lower() for k in _AUTH_MSG_KEYWORDS):
            raise KaadasAuthError(f"{path}: code={code} msg={msg}")
        raise KaadasError(f"{path}: code={code} msg={msg}")

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """账号下绑定的 Wi-Fi 门锁列表（data.wifiList）。

        productInfoList 里同 esn 的产品信息（如 abbreviation "K20 Max Plus"）放在 "product" 键下。
        """
        data = await self._post(ENDPOINT_DEVICES, {"uid": self._uid, "modelSearchType": 2})
        if not isinstance(data, dict):
            return []
        products = {
            p.get("esn"): p for p in data.get("productInfoList") or [] if isinstance(p, dict)
        }
        return [
            {**d, "product": products.get(d.get("wifiSN"), {})}
            for d in data.get("wifiList") or []
            if isinstance(d, dict)
        ]

    async def _records(self, endpoint: tuple[str, str], wifi_sn: str) -> list[dict[str, Any]]:
        data = await self._post(endpoint, {"wifiSN": wifi_sn, "page": 1})
        if not isinstance(data, list):
            return []
        return [r for r in data if isinstance(r, dict)]

    async def async_get_operations(self, wifi_sn: str) -> list[dict[str, Any]]:
        """开锁/上锁记录，最新的在前。"""
        return await self._records(ENDPOINT_OPERATIONS, wifi_sn)

    async def async_get_visits(self, wifi_sn: str) -> list[dict[str, Any]]:
        """门铃记录，最新的在前。"""
        return await self._records(ENDPOINT_VISITS, wifi_sn)

    async def async_get_alarms(self, wifi_sn: str) -> list[dict[str, Any]]:
        """报警记录（徘徊、锁舌异常等），最新的在前。"""
        return await self._records(ENDPOINT_ALARMS, wifi_sn)

    async def async_get_image(self, url: str) -> bytes | None:
        """下载抓拍图。图片还没上传完时返回 None。"""
        try:
            async with self._session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    _LOGGER.debug("下载抓拍图失败：HTTP %s", resp.status)
                    return None
                return await resp.read()
        except (TimeoutError, ClientError) as err:
            _LOGGER.debug("下载抓拍图失败：%r", err)
            return None

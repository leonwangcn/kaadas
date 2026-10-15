"""测试公共夹具。响应数据来自凯迪仕 App 6.19.3 抓包（已脱敏）。"""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.kaadas.const import (
    API_BASE_URL,
    CONF_TOKEN,
    CONF_UID,
    CONF_WIFI_SN,
    DOMAIN,
    ENDPOINT_ALARMS,
    ENDPOINT_DEVICES,
    ENDPOINT_OPERATIONS,
    ENDPOINT_VISITS,
)

WIFI_SN = "K2MTEST000001"
TOKEN = "test-token"
UID = "uid0000000000000000000001"
IMAGE = b"\xff\xd8\xff\xe0fake-jpeg"

_RESPONSES = json.loads((Path(__file__).parent / "fixtures" / "responses.json").read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def responses() -> dict[str, Any]:
    """可修改的响应副本。"""
    return copy.deepcopy(_RESPONSES)


def url(endpoint: tuple[str, str]) -> str:
    return f"{API_BASE_URL}{endpoint[0]}"


def mock_cloud(aioclient_mock: AiohttpClientMocker, responses: dict[str, Any]) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.post(url(ENDPOINT_DEVICES), json=responses["devices"])
    aioclient_mock.post(url(ENDPOINT_OPERATIONS), json=responses["operations"])
    aioclient_mock.post(url(ENDPOINT_VISITS), json=responses["visits"])
    aioclient_mock.post(url(ENDPOINT_ALARMS), json=responses["alarms"])
    aioclient_mock.get(
        re.compile(rf"https://kds-alarm\.oss-cn-shenzhen\.aliyuncs\.com/{WIFI_SN}/.+\.jpg"),
        content=IMAGE,
        headers={"Content-Type": "image/jpeg"},
    )


def mock_image_404(aioclient_mock: AiohttpClientMocker, image_url: str) -> None:
    """这张图还没上传好：优先于通用图片 mock 返回 404。"""
    aioclient_mock.get(image_url, status=404)
    aioclient_mock._mocks.insert(0, aioclient_mock._mocks.pop())


def new_record(category: str, rtype: int, text: str, **extra: Any) -> dict[str, Any]:
    """造一条刚刚发生的记录。"""
    now = int(time.time())
    rid = f"new{category}{rtype}{now}{extra.get('eventId', '')}"
    record = {
        "id": rid,
        "_id": rid,
        "wifiSN": WIFI_SN,
        "time": now,
        "type": rtype,
        "textContent": text,
        **extra,
    }
    if "eventId" in record:
        record["thumbUrl"] = (
            f"https://kds-alarm.oss-cn-shenzhen.aliyuncs.com/{WIFI_SN}/{record['eventId']}.jpg"
        )
    return record


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=WIFI_SN,
        title="测试的家（K20 Max Plus）",
        data={CONF_TOKEN: TOKEN, CONF_UID: UID, CONF_WIFI_SN: WIFI_SN},
    )

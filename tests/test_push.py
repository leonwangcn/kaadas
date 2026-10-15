"""实时推送：消息解析、推送触发快速轮询、等抓拍图再触发门铃。"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.kaadas.const import (
    BURST_INTERVAL,
    CONF_PUSH,
    DEFAULT_SCAN_INTERVAL,
    SNAPSHOT_WAIT,
    VISIT_TYPE_DOORBELL,
)
from custom_components.kaadas.push import KaadasPush, parse_event

from .conftest import IMAGE, WIFI_SN, mock_cloud, mock_image_404, new_record
from .test_init import _entity_id, _setup


def _msg(**kwargs) -> bytes:
    return json.dumps({"msgtype": "event", "func": "wfevent", "wfId": WIFI_SN, **kwargs}).encode()


def test_parse_event():
    assert parse_event(_msg(eventtype="alarm"), WIFI_SN) == "alarm"
    assert parse_event(_msg(eventtype="record"), WIFI_SN) == "record"
    # sn 只在 eventparams 里
    payload = json.dumps(
        {"func": "wfevent", "eventtype": "lockInf", "eventparams": {"sn": WIFI_SN}}
    ).encode()
    assert parse_event(payload, WIFI_SN) == "lockInf"
    # 别的门锁、别的消息、非 JSON
    assert parse_event(_msg(eventtype="alarm", wfId="OTHER"), WIFI_SN) is None
    assert parse_event(json.dumps({"func": "wakeup", "wfId": WIFI_SN}).encode(), WIFI_SN) is None
    assert parse_event(b"\x00\xff", WIFI_SN) is None


async def _tick(hass, freezer, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_push_triggers_refresh_and_waits_for_snapshot(
    hass: HomeAssistant, aioclient_mock, responses, config_entry, freezer
):
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data
    doorbell_id = _entity_id(hass, "event", "doorbell")

    # 门铃记录已经出现，但抓拍图还没上传（404）
    record = new_record("visit", VISIT_TYPE_DOORBELL, "有人按门铃", eventId="ev_push")
    responses["visits"]["data"].insert(0, record)
    mock_cloud(aioclient_mock, responses)
    mock_image_404(aioclient_mock, record["thumbUrl"])

    coordinator.async_handle_push("alarm")
    await hass.async_block_till_done(wait_background_tasks=True)

    # 推送后立刻轮询了，进入快速轮询，但门铃先不触发
    assert coordinator.update_interval == timedelta(seconds=BURST_INTERVAL)
    assert hass.states.get(doorbell_id).state == STATE_UNKNOWN

    # 图上传好了，下一次快速轮询触发门铃，此时摄像头里已经是这次的图
    mock_cloud(aioclient_mock, responses)
    await _tick(hass, freezer, BURST_INTERVAL + 0.5)
    state = hass.states.get(doorbell_id)
    assert state.attributes["event_type"] == "ring"
    assert coordinator.snapshot_event_id == "ev_push"
    assert coordinator.snapshot_image == IMAGE

    # 快速轮询结束后恢复正常间隔
    await _tick(hass, freezer, 31)
    await _tick(hass, freezer, BURST_INTERVAL + 0.5)
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)


async def test_doorbell_fires_without_snapshot_after_timeout(
    hass: HomeAssistant, aioclient_mock, responses, config_entry, freezer
):
    """图一直没上传好，等够时间后照样触发门铃。"""
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)
    doorbell_id = _entity_id(hass, "event", "doorbell")

    record = new_record("visit", VISIT_TYPE_DOORBELL, "有人按门铃", eventId="ev_noimg")
    responses["visits"]["data"].insert(0, record)

    def _mock_404():
        mock_cloud(aioclient_mock, responses)
        mock_image_404(aioclient_mock, record["thumbUrl"])

    _mock_404()
    config_entry.runtime_data.async_handle_push("alarm")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(doorbell_id).state == STATE_UNKNOWN

    _mock_404()
    await _tick(hass, freezer, SNAPSHOT_WAIT)
    await _tick(hass, freezer, BURST_INTERVAL + 0.5)
    assert hass.states.get(doorbell_id).attributes["event_type"] == "ring"


async def test_push_option_starts_and_stops_client(
    hass: HomeAssistant, aioclient_mock, responses, config_entry
):
    mock_cloud(aioclient_mock, responses)
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={CONF_PUSH: True})
    with (
        patch.object(KaadasPush, "async_start", AsyncMock()) as start,
        patch.object(KaadasPush, "async_stop", AsyncMock()) as stop,
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        assert start.await_count == 1
        assert config_entry.runtime_data.push is not None

        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
        assert stop.await_count == 1


async def test_push_disabled_by_default(
    hass: HomeAssistant, aioclient_mock, responses, config_entry
):
    mock_cloud(aioclient_mock, responses)
    with patch.object(KaadasPush, "async_start", AsyncMock()) as start:
        await _setup(hass, config_entry)
    assert start.await_count == 0
    assert config_entry.runtime_data.push is None


async def test_push_client_forwards_messages_to_loop(hass: HomeAssistant):
    """paho 线程里收到的消息转回事件循环；别的门锁的消息忽略。"""
    from types import SimpleNamespace

    received: list[str] = []
    push = KaadasPush(hass, uid="uid", token="token", wifi_sn=WIFI_SN, on_event=received.append)

    await hass.async_add_executor_job(
        push._on_message, None, None, SimpleNamespace(topic="t", payload=_msg(eventtype="alarm"))
    )
    await hass.async_add_executor_job(
        push._on_message,
        None,
        None,
        SimpleNamespace(topic="t", payload=_msg(eventtype="alarm", wfId="X")),
    )
    await hass.async_block_till_done()
    assert received == ["alarm"]

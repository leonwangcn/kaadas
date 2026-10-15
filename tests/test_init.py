"""集成加载、实体、事件触发、去重、token 失效测试。"""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.kaadas.const import (
    ALARM_TYPE_BOLT_JAMMED,
    ALARM_TYPE_LOITERING,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENDPOINT_OPERATIONS,
    OP_TYPE_UNLOCK,
    VISIT_TYPE_DOORBELL,
)

from .conftest import IMAGE, mock_cloud, mock_image_404, new_record, url


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass: HomeAssistant, domain: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"K2MTEST000001_{key}")
    assert entity_id, key
    return entity_id


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_setup_creates_entities(hass, aioclient_mock, responses, config_entry):
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    battery = hass.states.get(_entity_id(hass, "sensor", "battery"))
    assert battery.state == "31"

    # 抓包里最新的开锁记录：编号01 指纹开锁，之后门已上锁
    assert hass.states.get(_entity_id(hass, "sensor", "last_activity")).state == "门已上锁"
    unlocked_by = hass.states.get(_entity_id(hass, "sensor", "last_unlocked_by"))
    assert unlocked_by.state == "编号01"
    assert unlocked_by.attributes["method"] == "fingerprint"
    assert hass.states.get(_entity_id(hass, "lock", "lock")).state == "locked"

    # 历史记录不触发事件
    for key in ("doorbell", "loitering", "lock_activity", "alarm"):
        assert hass.states.get(_entity_id(hass, "event", key)).state == STATE_UNKNOWN

    # 最新一张抓拍（10-11 的门铃）已经下载
    image = await async_get_image(hass, _entity_id(hass, "camera", "snapshot"))
    assert image.content == IMAGE

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "K2MTEST000001"), config_entry.entry_id
    )
    assert device.model == "K20 Max Plus"
    assert device.name == "测试的家"


async def test_new_records_fire_events(hass, aioclient_mock, responses, config_entry, freezer):
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)

    responses["visits"]["data"].insert(
        0, new_record("visit", VISIT_TYPE_DOORBELL, "有人按门铃", eventId="ev_ring")
    )
    responses["alarms"]["data"].insert(
        0, new_record("alarm", ALARM_TYPE_LOITERING, "人脸徘徊报警", eventId="ev_loiter")
    )
    responses["alarms"]["data"].insert(
        0, new_record("alarm", ALARM_TYPE_BOLT_JAMMED, "锁舌未能完全伸出/收回")
    )
    responses["operations"]["data"].insert(
        0,
        new_record(
            "op",
            OP_TYPE_UNLOCK,
            "使用感应把手开锁",
            pwdType=11,
            pwdNum=106,
            userNickname="编号106",
        ),
    )
    mock_cloud(aioclient_mock, responses)
    await _poll(hass, freezer)

    doorbell = hass.states.get(_entity_id(hass, "event", "doorbell"))
    assert doorbell.attributes["event_type"] == "ring"
    assert doorbell.attributes["has_snapshot"] is True
    assert "thumbUrl" not in doorbell.attributes

    loitering = hass.states.get(_entity_id(hass, "event", "loitering"))
    assert loitering.attributes["event_type"] == "loitering"

    alarm = hass.states.get(_entity_id(hass, "event", "alarm"))
    assert alarm.attributes["event_type"] == "bolt_jammed"

    lock_activity = hass.states.get(_entity_id(hass, "event", "lock_activity"))
    assert lock_activity.attributes["event_type"] == "unlocked"
    assert lock_activity.attributes["method"] == "handle"
    assert lock_activity.attributes["user_number"] == 106
    assert hass.states.get(_entity_id(hass, "lock", "lock")).state == "unlocked"

    # 同一批记录再轮询一次，不重复触发
    fired_at = doorbell.state
    await _poll(hass, freezer)
    assert hass.states.get(_entity_id(hass, "event", "doorbell")).state == fired_at


async def test_seen_ids_survive_restart(hass, aioclient_mock, responses, config_entry, freezer):
    """已处理的 id 持久化：重启前处理过的不重发，重启期间新来的会补发。"""
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)

    before = new_record("visit", VISIT_TYPE_DOORBELL, "有人按门铃", eventId="ev_before")
    responses["visits"]["data"].insert(0, before)
    mock_cloud(aioclient_mock, responses)
    await _poll(hass, freezer)
    doorbell_id = _entity_id(hass, "event", "doorbell")
    assert hass.states.get(doorbell_id).attributes["time"] == before["time"]

    # 让延迟保存写进存储
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # "重启期间"又有人按了门铃
    freezer.tick(timedelta(minutes=1))
    during = new_record("visit", VISIT_TYPE_DOORBELL, "有人按门铃", eventId="ev_during")
    responses["visits"]["data"].insert(0, during)
    mock_cloud(aioclient_mock, responses)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(doorbell_id)
    assert state.attributes["time"] == during["time"]
    fired_at = state.state

    # 再轮询一次，两条都不会再触发
    await _poll(hass, freezer)
    assert hass.states.get(doorbell_id).state == fired_at


async def test_old_records_do_not_fire(hass, aioclient_mock, responses, config_entry, freezer):
    """长时间离线后补拉到的旧记录，只标记不触发。"""
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)

    old = new_record("visit", VISIT_TYPE_DOORBELL, "有人按门铃", eventId="ev_old")
    old["time"] -= 3600
    responses["visits"]["data"].insert(0, old)
    mock_cloud(aioclient_mock, responses)
    await _poll(hass, freezer)

    assert hass.states.get(_entity_id(hass, "event", "doorbell")).state == STATE_UNKNOWN


async def test_snapshot_retried_when_not_uploaded(
    hass, aioclient_mock, responses, config_entry, freezer
):
    """图片还没上传完（404）时保留旧图，下一轮再下载。"""
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)
    camera_id = _entity_id(hass, "camera", "snapshot")

    record = new_record("visit", VISIT_TYPE_DOORBELL, "有人按门铃", eventId="ev_slow")
    responses["visits"]["data"].insert(0, record)
    mock_cloud(aioclient_mock, responses)
    mock_image_404(aioclient_mock, record["thumbUrl"])
    await _poll(hass, freezer)
    coordinator = config_entry.runtime_data
    assert coordinator.snapshot_event_id != "ev_slow"
    assert (await async_get_image(hass, camera_id)).content == IMAGE

    mock_cloud(aioclient_mock, responses)
    await _poll(hass, freezer)
    assert coordinator.snapshot_event_id == "ev_slow"


async def test_auth_failure_starts_reauth(hass, aioclient_mock, responses, config_entry, freezer):
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.post(url(ENDPOINT_OPERATIONS), json={"code": 444, "msg": "token失效"})
    await _poll(hass, freezer)

    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_cloud_error_marks_unavailable(
    hass, aioclient_mock, responses, config_entry, freezer
):
    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)

    aioclient_mock.clear_requests()
    aioclient_mock.post(url(ENDPOINT_OPERATIONS), status=502)
    await _poll(hass, freezer)
    assert hass.states.get(_entity_id(hass, "sensor", "battery")).state == "unavailable"

    # 恢复后不会因为 unavailable -> 可用 误触发事件
    mock_cloud(aioclient_mock, responses)
    await _poll(hass, freezer)
    assert hass.states.get(_entity_id(hass, "sensor", "battery")).state == "31"
    assert hass.states.get(_entity_id(hass, "event", "doorbell")).state == STATE_UNKNOWN


async def test_diagnostics_redacts_secrets(hass, aioclient_mock, responses, config_entry):
    from custom_components.kaadas.diagnostics import async_get_config_entry_diagnostics

    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    text = str(diag)
    for secret in ("test-token", "uid0000000000000000000001", "K2MTEST000001", "kds-alarm"):
        assert secret not in text


async def test_lock_is_read_only(hass, aioclient_mock, responses, config_entry):
    """开锁请求被拒绝；状态先变成 unlocking 再恢复，HomeKit 才不会卡在"正在开锁"。"""
    import pytest
    from homeassistant.core import Event, callback
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.event import async_track_state_change_event

    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)
    lock_id = _entity_id(hass, "lock", "lock")
    calls_before = aioclient_mock.call_count

    seen: list[str] = []

    @callback
    def _record(event: Event) -> None:
        seen.append(event.data["new_state"].state)

    unsub = async_track_state_change_event(hass, lock_id, _record)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("lock", "unlock", {"entity_id": lock_id}, blocking=True)
    await hass.async_block_till_done()
    unsub()

    assert seen == ["unlocking", "locked"]
    assert hass.states.get(lock_id).state == "locked"
    # 没有向凯迪仕发出任何请求
    assert aioclient_mock.call_count == calls_before


async def test_snapshot_is_rotated_by_oss(hass, aioclient_mock, responses, config_entry):
    """默认让 OSS 顺时针旋转 90°；选项改成 0 时请求原图。"""
    from custom_components.kaadas.const import CONF_IMAGE_ROTATION

    mock_cloud(aioclient_mock, responses)
    await _setup(hass, config_entry)
    image_urls = [str(call[1]) for call in aioclient_mock.mock_calls if call[0] == "GET"]
    assert image_urls and all(u.endswith("?x-oss-process=image/rotate,90") for u in image_urls)

    hass.config_entries.async_update_entry(config_entry, options={CONF_IMAGE_ROTATION: "0"})
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    image_urls = [str(call[1]) for call in aioclient_mock.mock_calls if call[0] == "GET"]
    assert image_urls[-1].endswith(".jpg")

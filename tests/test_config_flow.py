"""配置流程测试。"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.kaadas.const import (
    CONF_TOKEN,
    CONF_UID,
    CONF_WIFI_SN,
    DOMAIN,
    ENDPOINT_DEVICES,
)

from .conftest import TOKEN, UID, WIFI_SN, mock_cloud, url


async def test_user_flow_single_device(hass: HomeAssistant, aioclient_mock, responses):
    mock_cloud(aioclient_mock, responses)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: f" {TOKEN} ", CONF_UID: UID}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "测试的家（K20 Max Plus）"
    assert result["data"][CONF_TOKEN] == TOKEN
    assert result["data"][CONF_WIFI_SN] == WIFI_SN
    assert result["result"].unique_id == WIFI_SN

    # 请求头里带了 token 和接口版本
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["token"] == TOKEN
    assert headers["ver"] == ENDPOINT_DEVICES[1]


async def test_user_flow_multiple_devices(hass: HomeAssistant, aioclient_mock, responses):
    second = {**responses["devices"]["data"]["wifiList"][0], "wifiSN": "K2MTEST000002"}
    responses["devices"]["data"]["wifiList"].append(second)
    mock_cloud(aioclient_mock, responses)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: TOKEN, CONF_UID: UID}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "device"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WIFI_SN: "K2MTEST000002"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_WIFI_SN] == "K2MTEST000002"


async def test_user_flow_invalid_token(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(url(ENDPOINT_DEVICES), json={"code": 444, "msg": "token失效"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: TOKEN, CONF_UID: UID}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(url(ENDPOINT_DEVICES), status=500)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: TOKEN, CONF_UID: UID}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, aioclient_mock, responses, config_entry
):
    config_entry.add_to_hass(hass)
    mock_cloud(aioclient_mock, responses)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: TOKEN, CONF_UID: UID}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_token(hass: HomeAssistant, aioclient_mock, responses, config_entry):
    config_entry.add_to_hass(hass)
    mock_cloud(aioclient_mock, responses)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "new-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKEN] == "new-token"


async def test_options_flow(hass: HomeAssistant, aioclient_mock, responses, config_entry):
    from custom_components.kaadas.const import (
        CONF_IMAGE_ROTATION,
        CONF_INFO_INTERVAL,
        CONF_SCAN_INTERVAL,
    )

    mock_cloud(aioclient_mock, responses)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 60, CONF_INFO_INTERVAL: 900, CONF_IMAGE_ROTATION: "270"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_IMAGE_ROTATION] == "270"
    await hass.async_block_till_done()
    assert config_entry.runtime_data.update_interval.total_seconds() == 60

"""Sensor platform for Mona."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MEMBER_NUMBER, DOMAIN
from .coordinator import MonaCoordinator


@dataclass(frozen=True, kw_only=True)
class MonaSensorEntityDescription(SensorEntityDescription):
    """Describes Mona sensor entity."""

    value_key: str


# Balance and contribution sensors
BALANCE_SENSORS: tuple[MonaSensorEntityDescription, ...] = (
    MonaSensorEntityDescription(
        key="account_balance",
        translation_key="account_balance",
        native_unit_of_measurement="AUD",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_key="account_balance",
    ),
    MonaSensorEntityDescription(
        key="investment_earnings",
        translation_key="investment_earnings",
        native_unit_of_measurement="AUD",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_key="investment_earnings",
    ),
    MonaSensorEntityDescription(
        key="contributions_ytd",
        translation_key="contributions_ytd",
        native_unit_of_measurement="AUD",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_key="contributions_ytd",
    ),
    MonaSensorEntityDescription(
        key="contribution_cap",
        translation_key="contribution_cap",
        native_unit_of_measurement="AUD",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_key="contribution_cap",
    ),
)

# Investment return sensors (percentages)
RETURN_SENSORS: tuple[MonaSensorEntityDescription, ...] = (
    MonaSensorEntityDescription(
        key="return_1yr",
        translation_key="return_1yr",
        native_unit_of_measurement="%",
        suggested_display_precision=2,
        value_key="investment_return_1yr",
        icon="mdi:chart-line",
    ),
    MonaSensorEntityDescription(
        key="return_3yr",
        translation_key="return_3yr",
        native_unit_of_measurement="%",
        suggested_display_precision=2,
        value_key="investment_return_3yr",
        icon="mdi:chart-line",
    ),
    MonaSensorEntityDescription(
        key="return_5yr",
        translation_key="return_5yr",
        native_unit_of_measurement="%",
        suggested_display_precision=2,
        value_key="investment_return_5yr",
        icon="mdi:chart-line",
    ),
    MonaSensorEntityDescription(
        key="return_7yr",
        translation_key="return_7yr",
        native_unit_of_measurement="%",
        suggested_display_precision=2,
        value_key="investment_return_7yr",
        icon="mdi:chart-line",
    ),
    MonaSensorEntityDescription(
        key="return_10yr",
        translation_key="return_10yr",
        native_unit_of_measurement="%",
        suggested_display_precision=2,
        value_key="investment_return_10yr",
        icon="mdi:chart-line",
    ),
    MonaSensorEntityDescription(
        key="return_fytd",
        translation_key="return_fytd",
        native_unit_of_measurement="%",
        suggested_display_precision=2,
        value_key="investment_return_fytd",
        icon="mdi:chart-line",
    ),
)

# All sensors combined
SENSORS = BALANCE_SENSORS + RETURN_SENSORS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Mona sensors from a config entry."""
    coordinator: MonaCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        MonaSensor(coordinator, entry, description)
        for description in SENSORS
    )


class MonaSensor(CoordinatorEntity[MonaCoordinator], SensorEntity):
    """Representation of a Mona sensor."""

    entity_description: MonaSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MonaCoordinator,
        entry: ConfigEntry,
        description: MonaSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        
        member_number = entry.data.get(CONF_MEMBER_NUMBER, "Mona")
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Mona ({member_number})",
            manufacturer="Mona",
            model="Super Account",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.value_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return None
        
        attrs = {
            "member_number": self._entry.data.get(CONF_MEMBER_NUMBER),
        }
        
        # Add date-related attributes for balance sensors
        if self.entity_description.key == "account_balance":
            attrs["balance_date"] = self.coordinator.data.get("balance_date")
            attrs["account_name"] = self.coordinator.data.get("account_name")
        
        # Add date range for earnings
        if self.entity_description.key == "investment_earnings":
            attrs["from_date"] = self.coordinator.data.get("investment_earnings_from")
            attrs["to_date"] = self.coordinator.data.get("investment_earnings_to")
        
        # Add investment option name for return sensors
        if self.entity_description.key.startswith("return_"):
            attrs["investment_option"] = self.coordinator.data.get("investment_option_name")
        
        return attrs

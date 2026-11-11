"""Which connector serves which kind of integration."""

from collections.abc import Mapping
from types import MappingProxyType

from apps.hub.integrations.canvas import CanvasConnector, canvas_base_url
from apps.hub.integrations.connectors import Connector, IcsConnector
from apps.hub.integrations.imap import ImapConnector, check_imap_config
from packages.contracts.integrations import IntegrationKind

CONNECTORS: Mapping[IntegrationKind, Connector] = MappingProxyType(
    {
        IntegrationKind.ics: IcsConnector(),
        IntegrationKind.canvas: CanvasConnector(),
        IntegrationKind.email: ImapConnector(),
    }
)


def check_config(kind: IntegrationKind, config: Mapping[str, str]) -> dict[str, str]:
    """The kind's config, normalised; ValueError if it is wrong. Config is never secret."""
    if kind is IntegrationKind.ics:
        if config:
            raise ValueError("a calendar feed takes no settings; its address is the credential")
        return {}
    if kind is IntegrationKind.email:
        return check_imap_config(config)
    unknown = set(config) - {"base_url"}
    if unknown:
        raise ValueError(f"unknown Canvas settings: {sorted(unknown)}")
    return {"base_url": canvas_base_url(config.get("base_url", ""))}

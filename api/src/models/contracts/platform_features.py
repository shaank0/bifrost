"""Optional platform features a platform admin turns on in Settings → Platform → Features.

Every feature here is off until someone turns it on. Add a feature by adding
an entry to ``PLATFORM_FEATURES``; its code checks
``platform_features.is_enabled(key)`` before doing anything.
"""

from pydantic import BaseModel

# The system_configs category that holds one row per feature that was ever switched.
PLATFORM_FEATURES_CONFIG_CATEGORY = "platform_features"


class PlatformFeatureInfo(BaseModel):
    key: str
    label: str
    description: str


PLATFORM_FEATURES: dict[str, PlatformFeatureInfo] = {
    feature.key: feature
    for feature in (
        PlatformFeatureInfo(
            key="mcp_gateway",
            label="MCP Gateway",
            description=(
                "Serve the tools of MCP connections marked for the gateway on /mcp/gateway, so AI "
                "clients reach each organization's connections through Bifrost with per-role access. "
                "Off: the gateway serves no tools and the Gateway section is hidden on connections."
            ),
        ),
        PlatformFeatureInfo(
            key="alerts",
            label="Failure Alerts",
            description=(
                "Open an alert when a scheduled or event-triggered workflow fails after its last retry, "
                "or an integration needs reconnecting, and show them in the header and on the Alerts "
                "page. Alert email is set up separately under Alerts."
            ),
        ),
    )
}


class PlatformFeaturePublic(PlatformFeatureInfo):
    enabled: bool


class PlatformFeaturesResponse(BaseModel):
    features: list[PlatformFeaturePublic]


class PlatformFeaturesRequest(BaseModel):
    """Features to switch, by key. Features not named keep their setting."""

    enabled: dict[str, bool]

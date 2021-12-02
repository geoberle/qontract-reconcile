import json
from dataclasses import field
from typing import Any, Optional

from pydantic.dataclasses import dataclass

from reconcile.utils.vaultsecretref import VaultSecretRef
from reconcile import queries

@dataclass(frozen=True, eq=True)
class BlackboxMonitoringProvider:

    module: str
    # the namespace of a blackbox-exporter provider is mapped as dict
    # since its only use with ob.fetch_current_state is as a dict
    namespace: dict[str, Any] = field(compare=False, hash=False)
    exporterUrl: str


@dataclass(frozen=True, eq=True)
class CatchpointMonitoringProvider:

    productId: int
    credentials: VaultSecretRef = field(compare=False, hash=False)
    signalFxCredentials: VaultSecretRef = field(compare=False, hash=False)
    signalFxStreamUrl: str


@dataclass(frozen=True, eq=True)
class EndpointMonitoringProvider:

    name: str
    provider: str
    description: str
    timeout: Optional[str] = None
    checkInterval: Optional[str] = None
    blackboxExporter: Optional[BlackboxMonitoringProvider] = None
    catchpoint: Optional[CatchpointMonitoringProvider] = None
    metricLabels: Optional[str] = None

    @property
    def metric_labels(self):
        return json.loads(self.metricLabels) if self.metricLabels else {}


@dataclass
class Endpoint:

    name: str
    description: str
    url: str

    @dataclass
    class Monitoring:

        provider: EndpointMonitoringProvider
        probeName: Optional[str]

    monitoring: list[Monitoring]


def get_endpoints(provider_type: str) -> dict[EndpointMonitoringProvider, list[Endpoint]]:
    endpoints: dict[EndpointMonitoringProvider, list[Endpoint]] = {}
    for app in queries.get_service_monitoring_endpoints():
        for ep_data in app.get("endPoints") or []:
            monitoring = ep_data.get("monitoring")
            if monitoring:
                ep_data["monitoring"] = [
                    m for m in monitoring
                    if m["provider"]["provider"] == provider_type
                ]
                ep = Endpoint(**ep_data)
                for mon in ep.monitoring:
                    endpoints.setdefault(mon.provider, [])
                    if ep not in endpoints[mon.provider]:
                        endpoints[mon.provider].append(ep)
    return endpoints

from abc import abstractmethod
from typing import Iterable, Tuple

from prometheus_client import CollectorRegistry, Gauge, Counter
import  prometheus_client.exposition as prom_exp
import threading
import signalfx
from sretoolbox.utils import threaded


from reconcile.utils.semver_helper import make_semver
from reconcile.monitoring import Endpoint, get_endpoints


QONTRACT_INTEGRATION = "signalfx-prometheus"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


# integration metrics
received_metrics = Counter(f"qontract_reconcile_signalfx_received_metrics", "Number of metrics received by a monitoring prodiver", ["provider"])
exposed_timeseries = Gauge(f"qontract_reconcile_signalfx_exposed_timeseries", "Number of prometheus metrics exposed by a monitoring provider", ["provider"])


class MetricProcessor:

    @staticmethod
    @abstractmethod
    def declare_gauges(registry: CollectorRegistry) -> dict[Gauge, str]:
        pass

    @staticmethod
    @abstractmethod
    def process_metric(gauge: Gauge, metadata: dict[str,str], provider: str, value: float) -> None:
        pass


class CatchpointErrorRateProcessor(MetricProcessor):

    @staticmethod
    def declare_gauges(endpoints: Iterable[Endpoint], registry: CollectorRegistry) -> dict[Gauge, str]:
        probe_names = []
        for ep in endpoints:
            for m in ep.monitoring:
                probe_names.append(m.probeName)
        decorated_probe_names = ",".join([f"'{p}'" for p in probe_names])
        filter = f"filter('cp_testname', {decorated_probe_names})"
        return {
            Gauge(f"catchpoint_probe_errors:rate{tw}",
                  f"catchpoint probe {tw} error rate",
                  ["probe_name", "catchpoint_probe_id", "provider"],
                  registry=registry): CatchpointErrorRateProcessor._flow_program_for_time_window(filter, tw)
            for tw in ["5m", "10m", "1h"]
        }

    @staticmethod
    def _flow_program_for_time_window(filter: list[str], time_window: str):
        # read about signalfx-flow here
        # https://dev.splunk.com/observability/docs/signalflow/
        return (
            "combine("
                f"data('catchpoint.counterfailedrequests', {filter})"
                    ".sum(by=['cp_testid', 'cp_testname'])"
                    f".sum(over='{time_window}')"
                "/"
                f"data('catchpoint.counterrequests', {filter})"
                    ".sum(by=['cp_testid', 'cp_testname'])"
                    f".sum(over='{time_window}')"
            ")"
        )

    @staticmethod
    def process_metric(gauge: Gauge, signalfx_metadata: dict[str, str], provider: str, value: float) -> None:
        test_name = signalfx_metadata.get("cp_testname")
        test_id = signalfx_metadata.get("cp_testid")
        gauge.labels(test_name, test_id, provider).set(value)


class FlowProgram:

    def __init__(self, name, stream_url: str, token: str):
        self.name = name
        self.stream_url = stream_url
        self.token = token
        self.program_list = []
        self.registered_gauges: dict[str, Tuple[MetricProcessor, Gauge]] = {}
        self.registry = CollectorRegistry()
        exposed_timeseries.labels(self.name).set_function(lambda: self.exposed_metrics_count())

    def register_endpoints(self, endpoints: Iterable[Endpoint], processor: type[MetricProcessor]) -> None:
        for gauge, program in processor().declare_gauges(endpoints, self.registry).items():
            gauge_name = gauge.describe()[0].name
            self.registered_gauges[gauge_name] = (processor, gauge)
            self.program_list.append(f"{program}.publish(label='{gauge_name}')")

    def exposed_metrics_count(self) -> int:
        return sum([len(m.samples) for m in list(self.registry.collect())])

    def stream(self, resolution: int):
        sfx = signalfx.SignalFx(stream_endpoint=self.stream_url)
        with sfx.signalflow(self.token) as flow:
            computation = flow.execute("\n".join(self.program_list), resolution=resolution)
            for msg in computation.stream():
                if isinstance(msg, signalfx.signalflow.messages.DataMessage):
                    received_metrics.labels(self.name).inc(len(msg.data.items()))
                    for tsid, value in msg.data.items():
                        metadata = computation.get_metadata(tsid)
                        metric_name = metadata.get("sf_streamLabel")
                        if metric_name in self.registered_gauges:
                            exporter, gauge = self.registered_gauges[metric_name]
                            exporter.process_metric(gauge, metadata, self.name, value)


def start_stream(flow: FlowProgram):
    flow.stream(resolution=5000)


def expose_flow_registries(port, flows: list[FlowProgram]):
    flow_handler = {
        f.name: prom_exp.make_wsgi_app(registry=f.registry) for f in flows
    }
    def path_based_exposer(environ, start_response):
        handler = flow_handler.get(environ['PATH_INFO'][1:])
        if handler:
            return handler(environ, start_response)
        else:
            # Serve empty response for browsers
            status = str('200 OK')
            header = (str(''), str(''))
            output = b''
            start_response(status, [header])
            return [output]

    httpd = prom_exp.make_server("", port, path_based_exposer, prom_exp.ThreadingWSGIServer, handler_class=prom_exp._SilentHandler)
    t = threading.Thread(target=httpd.serve_forever)
    t.daemon = True
    t.start()


def run(dry_run: bool):

    flows: list[FlowProgram] = []

    endpoints = get_endpoints("catchpoint")
    for provider, endpoints in get_endpoints("catchpoint").items():
        flow = FlowProgram(
            provider.name, provider.catchpoint.signalFxStreamUrl,
            provider.catchpoint.signalFxCredentials.get()
        )
        flows.append(flow)
        flow.register_endpoints(endpoints, CatchpointErrorRateProcessor)

    expose_flow_registries(8888, flows)
    threaded.run(start_stream, flows, len(flows))

    # todo make sure thread terminate after a timeout so they can rearead the
    # stream configurations from Endpoint monitoring

import socket
import elasticsearch
import logging

from esrally import exceptions, time


logger = logging.getLogger("rally.cluster")


class Node:
    """
    Represents an Elasticsearch cluster node.
    """
    def __init__(self, process, host_name, node_name, telemetry):
        """
        Creates a new node.

        :param process: Process handle for this node.
        :param host_name: The name of the host where this node is running.
        :param node_name: The name of this node.
        :param telemetry: The attached telemetry.
        """
        self.process = process
        self.host_name = host_name
        self.node_name = node_name
        self.telemetry = telemetry

    def on_benchmark_start(self, phase):
        """
        Callback method when a benchmark is about to start.
        """
        self.telemetry.on_benchmark_start(phase)

    def on_benchmark_stop(self, phase):
        """
        Callback method when a benchmark is about to stop.
        """
        self.telemetry.on_benchmark_stop(phase)


class EsClientFactory:
    """
    Abstracts how the Elasticsearch client is created. Intended for testing.
    """
    def __init__(self, hosts):
        self.client = elasticsearch.Elasticsearch(hosts=hosts, timeout=60, request_timeout=60)

    def create(self):
        return self.client


class Cluster:
    """
    Cluster exposes APIs of the running benchmark candidate.
    """
    EXPECTED_CLUSTER_STATUS = "green"

    def __init__(self, hosts, nodes, metrics_store, client_factory_class=EsClientFactory, clock=time.Clock):
        """
        Creates a new Elasticsearch cluster.

        :param hosts: The hosts to which we can connect to (this must not necessarily be each host in the cluster). Mandatory.
        :param nodes: The nodes of which this cluster consists of. Mandatory.
        :param metrics_store: The corresponding metrics store. Mandatory.
        :param client_factory_class: This parameter is just intended for testing. Optional.
        :param clock: This parameter is just intended for testing. Optional.
        """
        self.client = client_factory_class(hosts).create()
        self.nodes = nodes
        self.metrics_store = metrics_store
        self.clock = clock

    def wait_for_status_green(self):
        """
        Synchronously waits until the cluster reaches status green. Upon timeout a LaunchError is thrown.
        """
        logger.info("\nWait for %s cluster..." % Cluster.EXPECTED_CLUSTER_STATUS)
        stop_watch = self.clock.stop_watch()
        stop_watch.start()
        reached_cluster_status, relocating_shards = self._do_wait(Cluster.EXPECTED_CLUSTER_STATUS)
        stop_watch.stop()
        logger.info("Cluster reached status [%s] within [%.1f] sec." % (reached_cluster_status, stop_watch.total_time()))
        logger.info("Cluster health: %s" % str(self.client.cluster.health()))
        logger.info("SHARDS:\n%s" % self.client.cat.shards(v=True))

    def _do_wait(self, expected_cluster_status):
        reached_cluster_status = None
        for attempt in range(10):
            try:
                result = self.client.cluster.health(wait_for_status=expected_cluster_status, wait_for_relocating_shards=0, timeout="3s")
            except (socket.timeout, elasticsearch.exceptions.ConnectionError, elasticsearch.exceptions.TransportError):
                pass
            else:
                reached_cluster_status = result["status"]
                relocating_shards = result["relocating_shards"]
                logger.info("GOT: %s" % str(result))
                logger.info("ALLOC:\n%s" % self.client.cat.allocation(v=True))
                logger.info("RECOVERY:\n%s" % self.client.cat.recovery(v=True))
                logger.info("SHARDS:\n%s" % self.client.cat.shards(v=True))
                if reached_cluster_status == expected_cluster_status and relocating_shards == 0:
                    return reached_cluster_status, relocating_shards
                else:
                    time.sleep(0.5)
        msg = "Cluster did not reach status [%s]. Last reached status: [%s]" % (expected_cluster_status, reached_cluster_status)
        logger.error(msg)
        raise exceptions.LaunchError(msg)

    def info(self):
        """
        :return: cluster info. See http://elasticsearch-py.readthedocs.org/en/master/api.html#elasticsearch.Elasticsearch.info
        """
        return self.client.info()

    def on_benchmark_start(self, phase=None):
        """
        Callback method when a benchmark is about to start.
        """
        for node in self.nodes:
            node.on_benchmark_start(phase)

    def on_benchmark_stop(self, phase=None):
        """
        Callback method when a benchmark is about to stop.
        """
        for node in self.nodes:
            node.on_benchmark_stop(phase)

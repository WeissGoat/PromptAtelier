from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from tags_machine_core.clients import gateway_novelai
from tags_machine_core.clients.gateway_novelai import GatewayNovelAIRawClient, _SharedTransport


class FakeRawClient:
    instances: list["FakeRawClient"] = []

    def __init__(self, config):
        self.config = config
        self.initialized = 0
        self.closed = 0
        self.calls = 0
        FakeRawClient.instances.append(self)

    async def initialize(self):
        self.initialized += 1

    async def close(self):
        self.closed += 1

    async def generate_raw(self, payload):
        self.calls += 1
        return SimpleNamespace(images=[], retry_records=[])


class SharedTransportTest(TestCase):
    def setUp(self):
        FakeRawClient.instances = []
        self.transport = _SharedTransport()
        patches = [
            patch.object(gateway_novelai, "NovelAIRawClient", FakeRawClient),
            patch.object(gateway_novelai, "_TRANSPORT", self.transport),
            patch.object(GatewayNovelAIRawClient, "build_payload", lambda self, request: {"input": "1girl", "model": "nai-diffusion-4-5-full"}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_reuses_one_client_across_tasks(self):
        # 执行器每个任务都新建 GatewayNovelAIRawClient，连接仍应只初始化一次
        for _ in range(3):
            GatewayNovelAIRawClient(access_token="t", base_url="https://image.novelai.net").generate_images(None)

        self.assertEqual(len(FakeRawClient.instances), 1)
        client = FakeRawClient.instances[0]
        self.assertEqual((client.initialized, client.calls), (1, 3))

        self.transport.close()
        self.assertEqual(client.closed, 1)

    def test_different_settings_get_separate_clients(self):
        GatewayNovelAIRawClient(access_token="a", base_url="https://image.novelai.net").generate_images(None)
        GatewayNovelAIRawClient(access_token="b", base_url="https://image.novelai.net").generate_images(None)

        self.assertEqual(len(FakeRawClient.instances), 2)

"""MQTT transport tests with a fake broker client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiomqtt
import pytest

from custom_components.gree_custom.aiogree import transport_mqtt
from custom_components.gree_custom.aiogree.cloud_api import GreeRegion
from custom_components.gree_custom.aiogree.errors import GreeConnectionError
from custom_components.gree_custom.aiogree.transport_mqtt import GreeMqttTransport

from .conftest import PARENT_MAC


@dataclass
class _Message:
    topic: str
    payload: bytes


class FakeMqttClient:
    instances: list[FakeMqttClient] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.subscribed: list[str] = []
        self.published: list[tuple[str, str]] = []
        self.queue: asyncio.Queue = asyncio.Queue()
        self.auto_reply = True
        FakeMqttClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscribed.append(topic)

    async def unsubscribe(self, topic: str) -> None:
        self.subscribed.remove(topic)

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        self.published.append((topic, payload))
        if self.auto_reply:
            mac = topic.split("/", 1)[1]
            self.queue.put_nowait(_Message(f"response/{mac}/x", f"echo:{payload}".encode()))

    @property
    def messages(self):
        return self._messages()

    async def _messages(self):
        while True:
            item = await self.queue.get()
            if isinstance(item, Exception):
                raise item
            yield item


@pytest.fixture
def fake_client(monkeypatch):
    FakeMqttClient.instances = []
    monkeypatch.setattr(transport_mqtt.aiomqtt, "Client", FakeMqttClient)
    return FakeMqttClient


def _transport(timeout: float = 1.0) -> GreeMqttTransport:
    return GreeMqttTransport("1234", "token", GreeRegion.EU, timeout=timeout)


async def test_request_goes_to_gateway_topic(fake_client) -> None:
    transport = _transport()
    await transport.subscribe(PARENT_MAC)

    response = await transport.request(PARENT_MAC, "hello")

    client = fake_client.instances[0]
    assert client.published == [(f"request/{PARENT_MAC}", "hello")]
    assert response == "echo:hello"
    assert f"status/{PARENT_MAC}/#" in client.subscribed

    await transport.unsubscribe(PARENT_MAC)
    assert not transport.connected


async def test_timeout_is_a_connection_error(fake_client) -> None:
    transport = _transport(timeout=0.05)
    await transport.subscribe(PARENT_MAC)
    fake_client.instances[0].auto_reply = False

    with pytest.raises(GreeConnectionError):
        await transport.request(PARENT_MAC, "hello")

    await transport.disconnect()


async def test_reconnects_and_resubscribes_after_connection_loss(fake_client) -> None:
    transport = _transport()
    await transport.subscribe(PARENT_MAC)
    first = fake_client.instances[0]

    first.queue.put_nowait(aiomqtt.MqttError("connection lost"))
    for _ in range(5):
        await asyncio.sleep(0)

    assert not transport.connected

    response = await transport.request(PARENT_MAC, "again")

    assert response == "echo:again"
    assert len(fake_client.instances) == 2
    second = fake_client.instances[1]
    assert f"status/{PARENT_MAC}/#" in second.subscribed
    assert f"response/{PARENT_MAC}/#" in second.subscribed

    await transport.disconnect()


async def test_pending_request_fails_fast_on_connection_loss(fake_client) -> None:
    transport = _transport(timeout=5)
    await transport.subscribe(PARENT_MAC)
    client = fake_client.instances[0]
    client.auto_reply = False

    task = asyncio.create_task(transport.request(PARENT_MAC, "hello"))
    await asyncio.sleep(0.01)
    client.queue.put_nowait(aiomqtt.MqttError("connection lost"))

    with pytest.raises(GreeConnectionError):
        await asyncio.wait_for(task, 1)

    await transport.disconnect()


async def test_unsubscribe_after_connection_loss(fake_client) -> None:
    transport = _transport()
    await transport.subscribe(PARENT_MAC)
    fake_client.instances[0].queue.put_nowait(aiomqtt.MqttError("connection lost"))
    for _ in range(5):
        await asyncio.sleep(0)

    await transport.unsubscribe(PARENT_MAC)

    assert not transport.connected_devices

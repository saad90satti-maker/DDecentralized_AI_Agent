"""
MQTT Protocol Module — Industrial IoT communication.
Publish/subscribe to MQTT brokers for sensor data, actuator control,
and real-time device telemetry.
"""

import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ProtocolMQTT")

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False


class MQTTClient:
    """
    MQTT client for industrial IoT communication.

    Usage:
        client = MQTTClient("ghost-sensor-node", "broker.hivemq.com", 1883)
        client.connect()
        client.subscribe("factory/sensor/#", on_message)
        client.publish("factory/actuator/valve1", {"position": 75})
        client.disconnect()
    """

    def __init__(self, client_id: str, broker_host: str = "broker.hivemq.com",
                 broker_port: int = 1883, username: str = "",
                 password: str = "", use_tls: bool = False):
        self.client_id = client_id
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self._client = None
        self._connected = False
        self._subscriptions: Dict[str, Callable] = {}

    def available(self) -> bool:
        return HAS_MQTT

    def connect(self, timeout: int = 10) -> bool:
        if not HAS_MQTT:
            logger.warning("paho-mqtt not installed — install with: pip install paho-mqtt")
            return False

        try:
            self._client = mqtt.Client(
                client_id=self.client_id,
                protocol=mqtt.MQTTv311,
            )

            if self.username:
                self._client.username_pw_set(self.username, self.password)

            if self.use_tls:
                self._client.tls_set()

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            self._client.connect(self.broker_host, self.broker_port, timeout)
            self._client.loop_start()

            # Wait for connection
            for _ in range(timeout):
                if self._connected:
                    break
                time.sleep(0.5)

            if self._connected:
                logger.info("MQTT connected: %s:%d as %s",
                            self.broker_host, self.broker_port, self.client_id)
            else:
                logger.warning("MQTT connection timeout: %s:%d",
                               self.broker_host, self.broker_port)

            return self._connected

        except Exception as e:
            logger.warning("MQTT connect failed: %s", e)
            return False

    def _on_connect(self, client, userdata, flags, rc) -> None:
        self._connected = rc == 0
        if rc == 0:
            logger.debug("MQTT connected OK")
            # Re-subscribe after reconnect
            for topic, cb in self._subscriptions.items():
                self._client.subscribe(topic)
        else:
            logger.warning("MQTT connection refused: rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        logger.debug("MQTT disconnected: rc=%d", rc)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            topic = msg.topic
            payload = msg.payload.decode()

            # Try to parse as JSON, fallback to raw string
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                data = {"raw": payload}

            # Route to matching subscription callback
            for sub_topic, callback in self._subscriptions.items():
                if mqtt.topic_matches_sub(sub_topic, topic):
                    callback(topic, data)

            logger.debug("MQTT message: %s -> %s", topic, str(data)[:100])
        except Exception as e:
            logger.warning("MQTT message handler: %s", e)

    def subscribe(self, topic: str, callback: Callable[[str, Any], None]) -> bool:
        if not self._client or not self._connected:
            logger.warning("MQTT subscribe: not connected")
            return False

        try:
            self._client.subscribe(topic)
            self._subscriptions[topic] = callback
            logger.info("MQTT subscribed: %s", topic)
            return True
        except Exception as e:
            logger.warning("MQTT subscribe failed: %s", e)
            return False

    def publish(self, topic: str, payload: Any, qos: int = 1) -> bool:
        if not self._client or not self._connected:
            logger.warning("MQTT publish: not connected")
            return False

        try:
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)
            result = self._client.publish(topic, payload, qos=qos)
            logger.debug("MQTT published: %s -> %s", topic, str(payload)[:80])
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.warning("MQTT publish failed: %s", e)
            return False

    def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
            logger.info("MQTT disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @staticmethod
    def public_brokers() -> List[Dict[str, Any]]:
        return [
            {"host": "broker.hivemq.com", "port": 1883},
            {"host": "test.mosquitto.org", "port": 1883},
            {"host": "iot.eclipse.org", "port": 1883},
            {"host": "broker.emqx.io", "port": 1883},
        ]

    def status(self) -> Dict[str, Any]:
        return {
            "protocol": "MQTT v3.1.1",
            "connected": self._connected,
            "broker": f"{self.broker_host}:{self.broker_port}",
            "client_id": self.client_id,
            "subscriptions": list(self._subscriptions.keys()),
            "tls": self.use_tls,
        }


class MQTTSensorFeed:
    """High-level MQTT sensor data consumer for factory/industrial telemetry."""

    def __init__(self, client: MQTTClient):
        self.client = client
        self._buffer: List[Dict[str, Any]] = []
        self._max_buffer = 1000

    def subscribe_sensors(self, topic: str = "factory/+/sensors/+") -> bool:
        def _on_sensor(topic: str, data: Any) -> None:
            entry = {
                "topic": topic,
                "data": data,
                "timestamp": time.time(),
            }
            self._buffer.append(entry)
            if len(self._buffer) > self._max_buffer:
                self._buffer = self._buffer[-self._max_buffer:]

        return self.client.subscribe(topic, _on_sensor)

    def subscribe_actuators(self, topic: str = "factory/+/actuators/+") -> bool:
        def _on_actuator(topic: str, data: Any) -> None:
            entry = {
                "topic": topic,
                "data": data,
                "timestamp": time.time(),
            }
            self._buffer.append(entry)
            if len(self._buffer) > self._max_buffer:
                self._buffer = self._buffer[-self._max_buffer:]

        return self.client.subscribe(topic, _on_actuator)

    def read_recent(self, seconds: int = 300) -> List[Dict[str, Any]]:
        cutoff = time.time() - seconds
        return [e for e in self._buffer if e["timestamp"] >= cutoff]

    def latest_value(self, topic_filter: str = "") -> Optional[Dict[str, Any]]:
        for entry in reversed(self._buffer):
            if topic_filter in entry["topic"]:
                return entry
        return None

    def clear_buffer(self) -> None:
        self._buffer.clear()

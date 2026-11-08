from __future__ import annotations

import ssl
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import paho.mqtt.client as mqtt
import main


class MqttSecurityConfigurationTests(unittest.TestCase):
    def test_username_and_password_are_configured_when_present(self):
        client = MagicMock(spec=mqtt.Client)
        tls_enabled = main.configure_mqtt_client_security(
            client,
            env={
                "MQTT_USERNAME": "  ward_service  ",
                "MQTT_PASSWORD": "secret-broker-password",
                "MQTT_PORT": "8083",
                "MQTT_TLS_ENABLED": "false",
            },
        )
        self.assertFalse(tls_enabled)
        client.username_pw_set.assert_called_once_with("ward_service", "secret-broker-password")
        client.tls_set.assert_not_called()

    def test_tls_is_configured_when_mqtt_tls_enabled_is_true(self):
        client = MagicMock(spec=mqtt.Client)
        tls_enabled = main.configure_mqtt_client_security(
            client,
            env={
                "MQTT_PORT": "8083",
                "MQTT_TLS_ENABLED": "true",
            },
        )
        self.assertTrue(tls_enabled)
        client.tls_set.assert_called_once_with(
            ca_certs=None,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set.assert_not_called()

    def test_tls_is_automatically_enabled_on_port_8883_or_8084(self):
        for port in ("8883", "8084"):
            with self.subTest(port=port):
                client = MagicMock(spec=mqtt.Client)
                tls_enabled = main.configure_mqtt_client_security(
                    client,
                    env={"MQTT_PORT": port},
                )
                self.assertTrue(tls_enabled)
                client.tls_set.assert_called_once_with(
                    ca_certs=None,
                    tls_version=ssl.PROTOCOL_TLS_CLIENT,
                )

    def test_tls_passes_ca_certs_and_insecure_flag_when_provided(self):
        client = MagicMock(spec=mqtt.Client)
        tls_enabled = main.configure_mqtt_client_security(
            client,
            env={
                "MQTT_PORT": "8883",
                "MQTT_CA_CERT": "/etc/ssl/certs/hospital-mqtt-ca.pem",
                "MQTT_TLS_INSECURE": "1",
            },
        )
        self.assertTrue(tls_enabled)
        client.tls_set.assert_called_once_with(
            ca_certs="/etc/ssl/certs/hospital-mqtt-ca.pem",
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set.assert_called_once_with(True)

    def test_plaintext_local_fallback_does_not_call_tls_set(self):
        client = MagicMock(spec=mqtt.Client)
        tls_enabled = main.configure_mqtt_client_security(
            client,
            env={
                "MQTT_PORT": "8083",
                "MQTT_TLS_ENABLED": "false",
            },
        )
        self.assertFalse(tls_enabled)
        client.username_pw_set.assert_not_called()
        client.tls_set.assert_not_called()
        client.tls_insecure_set.assert_not_called()


if __name__ == "__main__":
    unittest.main()

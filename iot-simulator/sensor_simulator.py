"""Realistic vital-sign MQTT simulator for the AI Smart Ward dashboard.

Each bed keeps its own physiological baseline, gradual trend and occasional
condition-aware episode. Values are deliberately continuous rather than a new
random number on every MQTT message. This is demonstration data only.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import paho.mqtt.client as mqtt

# Reuse the backend's deterministic, synthetic ward registry. Running this
# file directly places only iot-simulator on sys.path, so add the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from backend.patient_registry import PATIENT_PROFILES as REGISTERED_PATIENTS


import os
import ssl

BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT = int(os.getenv("MQTT_PORT", "8083"))
TOPIC = os.getenv("MQTT_TOPIC", "my_ai_hospital/vitals")
MQTT_TRANSPORT = os.getenv("MQTT_TRANSPORT", "websockets")
MQTT_USERNAME = (os.getenv("MQTT_USERNAME") or "").strip()
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD") or ""
MQTT_CA_CERT = (os.getenv("MQTT_CA_CERT") or "").strip()


def _default_tls_enabled(port: int = PORT) -> bool:
    raw = (os.getenv("MQTT_TLS_ENABLED") or "").strip().lower()
    if raw in {"true", "1", "yes"}:
        return True
    if raw in {"false", "0", "no"}:
        return False
    return port in {8883, 8084}


def configure_simulator_mqtt_security(
    client: mqtt.Client,
    *,
    port: int = PORT,
    username: str | None = None,
    password: str | None = None,
    tls_enabled: bool | None = None,
    ca_cert: str | None = None,
) -> bool:
    resolved_user = (username if username is not None else MQTT_USERNAME).strip()
    resolved_pass = password if password is not None else MQTT_PASSWORD
    resolved_ca = (ca_cert if ca_cert is not None else MQTT_CA_CERT).strip()
    resolved_tls = tls_enabled if tls_enabled is not None else _default_tls_enabled(port)
    tls_insecure = (os.getenv("MQTT_TLS_INSECURE") or "").strip().lower() in {"true", "1", "yes"}

    if resolved_user:
        client.username_pw_set(resolved_user, resolved_pass or None)
    if resolved_tls:
        client.tls_set(
            ca_certs=resolved_ca if resolved_ca else None,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        if tls_insecure:
            client.tls_insecure_set(True)
    return resolved_tls


@dataclass(frozen=True)
class PatientProfile:
    patient_id: str
    label: str
    zone: str
    room_number: str
    base_hr: float
    base_spo2: float
    base_rr: float
    base_glucose: float
    sleep_hours: float
    ecg_rhythm: str
    hr_variability: float
    spo2_variability: float
    episode_probability: float
    episode_types: tuple[str, ...]


@dataclass
class PatientState:
    profile: PatientProfile
    rng: random.Random
    heart_rate: float = field(init=False)
    spo2: float = field(init=False)
    respiratory_rate: float = field(init=False)
    blood_glucose: float = field(init=False)
    slow_hr_shift: float = 0.0
    slow_spo2_shift: float = 0.0
    slow_rr_shift: float = 0.0
    episode: str | None = None
    episode_samples_left: int = 0

    def __post_init__(self) -> None:
        self.heart_rate = self.profile.base_hr + self.rng.uniform(-2, 2)
        self.spo2 = self.profile.base_spo2 + self.rng.uniform(-0.7, 0.7)
        self.respiratory_rate = self.profile.base_rr + self.rng.uniform(-1, 1)
        self.blood_glucose = self.profile.base_glucose + self.rng.uniform(-5, 5)

    def _start_episode_if_needed(self) -> None:
        if self.episode_samples_left or self.rng.random() >= self.profile.episode_probability:
            return
        self.episode = self.rng.choice(self.profile.episode_types)
        self.episode_samples_left = self.rng.randint(3, 8)

    def sample(self, elapsed_seconds: float) -> tuple[int, int, int, float, str, str]:
        """Return a smooth sample and the simulator state for display/logging."""
        self._start_episode_if_needed()
        # Slow variation makes a patient drift over minutes rather than jump per reading.
        phase = elapsed_seconds / 180.0 + int(self.profile.patient_id[1:])
        self.slow_hr_shift = 2.5 * math.sin(phase) + self.rng.gauss(0, 0.25)
        self.slow_spo2_shift = 0.7 * math.sin(phase / 1.8) + self.rng.gauss(0, 0.08)
        self.slow_rr_shift = 1.2 * math.sin(phase / 1.35) + self.rng.gauss(0, 0.12)

        target_hr = self.profile.base_hr + self.slow_hr_shift
        target_spo2 = self.profile.base_spo2 + self.slow_spo2_shift
        target_rr = self.profile.base_rr + self.slow_rr_shift
        target_glucose = self.profile.base_glucose + 6 * math.sin(phase / 3.2)
        state = "stable"
        ecg_rhythm = self.profile.ecg_rhythm

        if self.episode == "desaturation":
            target_spo2 -= self.rng.uniform(5.0, 9.0)
            target_hr += self.rng.uniform(8.0, 16.0)
            target_rr += self.rng.uniform(4.0, 8.0)
            state = "desaturation episode"
        elif self.episode == "tachycardia":
            target_hr += self.rng.uniform(22.0, 38.0)
            target_spo2 -= self.rng.uniform(0.0, 2.0)
            target_rr += self.rng.uniform(1.0, 4.0)
            if "irregular" in ecg_rhythm.lower():
                ecg_rhythm = "Irregular rhythm (episode)"
            state = "tachycardia episode"
        elif self.episode == "bradycardia":
            target_hr -= self.rng.uniform(16.0, 25.0)
            if "irregular" in ecg_rhythm.lower():
                ecg_rhythm = "Irregular rhythm (episode)"
            state = "bradycardia episode"
        elif self.episode == "infection_stress":
            target_hr += self.rng.uniform(12.0, 22.0)
            target_spo2 -= self.rng.uniform(2.0, 5.0)
            target_rr += self.rng.uniform(3.0, 6.0)
            target_glucose += self.rng.uniform(15.0, 35.0)
            state = "physiological stress episode"

        # First-order smoothing represents a monitor observing a changing patient.
        self.heart_rate += (target_hr - self.heart_rate) * 0.42 + self.rng.gauss(0, self.profile.hr_variability)
        self.spo2 += (target_spo2 - self.spo2) * 0.38 + self.rng.gauss(0, self.profile.spo2_variability)
        self.respiratory_rate += (target_rr - self.respiratory_rate) * 0.38 + self.rng.gauss(0, 0.35)
        self.blood_glucose += (target_glucose - self.blood_glucose) * 0.25 + self.rng.gauss(0, 1.8)
        self.heart_rate = min(160.0, max(38.0, self.heart_rate))
        self.spo2 = min(100.0, max(78.0, self.spo2))
        self.respiratory_rate = min(42.0, max(8.0, self.respiratory_rate))
        self.blood_glucose = min(380.0, max(55.0, self.blood_glucose))

        if self.episode_samples_left:
            self.episode_samples_left -= 1
            if self.episode_samples_left == 0:
                self.episode = None

        return (
            round(self.heart_rate), round(self.spo2), round(self.respiratory_rate),
            round(self.blood_glucose, 1), ecg_rhythm, state,
        )


def build_simulator_profiles() -> tuple[PatientProfile, ...]:
    profiles = []
    for record in REGISTERED_PATIENTS.values():
        simulation = record["simulation"]
        profiles.append(PatientProfile(
            patient_id=record["patient_id"],
            label=record["condition"],
            zone=record["zone"],
            room_number=record["room_number"],
            base_hr=simulation["base_hr"],
            base_spo2=simulation["base_spo2"],
            base_rr=simulation["base_rr"],
            base_glucose=record["blood_glucose_mg_dl"],
            sleep_hours=record["sleep_hours"],
            ecg_rhythm=record["ecg_rhythm"],
            hr_variability=1.8 if "arrhythmia" in record["condition"].lower() else 0.9,
            spo2_variability=0.32 if record["zone"] == "A" else 0.20,
            episode_probability=simulation["episode_probability"],
            episode_types=tuple(simulation["episode_types"]),
        ))
    return tuple(profiles)


PATIENT_PROFILES = build_simulator_profiles()


def build_states(seed: int | None = None) -> list[PatientState]:
    seed_source = random.Random(seed)
    return [PatientState(profile, random.Random(seed_source.randrange(1_000_000))) for profile in PATIENT_PROFILES]


def run(
    interval: float,
    jitter: float,
    seed: int | None,
    broker: str = BROKER,
    port: int = PORT,
    topic: str = TOPIC,
    mqtt_username: str | None = None,
    mqtt_password: str | None = None,
    tls: bool | None = None,
    ca_cert: str | None = None,
    inject_artifact_bed: str | None = None,
    inject_artifact_type: str = "probe_disconnect",
) -> None:
    states = build_states(seed)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport=MQTT_TRANSPORT)
    configure_simulator_mqtt_security(
        client,
        port=port,
        username=mqtt_username,
        password=mqtt_password,
        tls_enabled=tls,
        ca_cert=ca_cert,
    )
    print(f"⏳ Connecting to MQTT broker {broker}:{port}...")
    client.connect(broker, port, 60)
    client.loop_start()
    print(f"Connected. Sending {len(states)} individual patient streams every ~{interval:.0f}s to topic '{topic}'.")
    print("Press Ctrl+C to stop. Use --seed for repeatable demonstrations.")

    start = time.monotonic()
    schedule = {state.profile.patient_id: start + state.rng.uniform(0, interval) for state in states}
    state_by_id = {state.profile.patient_id: state for state in states}
    try:
        while True:
            now = time.monotonic()
            due_patient_id = min(schedule, key=schedule.get)
            delay = schedule[due_patient_id] - now
            if delay > 0:
                time.sleep(delay)
                continue

            state = state_by_id[due_patient_id]
            heart_rate, spo2, respiratory_rate, blood_glucose, ecg_rhythm, simulation_state = state.sample(time.monotonic() - start)
            if inject_artifact_bed and due_patient_id == inject_artifact_bed.upper():
                if inject_artifact_type == "impossible_spo2":
                    spo2 = 105
                    simulation_state = "INJECTED_ARTIFACT: SpO2 105% (Sensor out of bounds)"
                elif inject_artifact_type == "impossible_hr":
                    heart_rate = 255
                    simulation_state = "INJECTED_ARTIFACT: HR 255 bpm (Signal fault)"
                elif inject_artifact_type == "apnea_fault":
                    respiratory_rate = 0
                    simulation_state = "INJECTED_ARTIFACT: RR 0 /min (Sensor disconnect)"
                else:  # probe_disconnect
                    heart_rate = 22
                    spo2 = 0
                    respiratory_rate = 0
                    simulation_state = "INJECTED_ARTIFACT: Disconnected probe"
            payload = {
                "patient_id": due_patient_id,
                "heart_rate": heart_rate,
                "spo2": spo2,
                "respiratory_rate": respiratory_rate,
                "blood_glucose": blood_glucose,
                "ecg_rhythm": ecg_rhythm,
                "sleep_hours": state.profile.sleep_hours,
                "zone": state.profile.zone,
                "room_number": state.profile.room_number,
                "timestamp": time.time(),
                "simulation_state": simulation_state,
            }
            result = client.publish(topic, json.dumps(payload))
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"MQTT publish failed for {due_patient_id}: {result.rc}")
            else:
                print(
                    f"{time.strftime('%H:%M:%S')} | {due_patient_id:<4} | {state.profile.zone}/{state.profile.room_number} | "
                    f"HR {heart_rate:>3} | SpO2 {spo2:>3}% | RR {respiratory_rate:>2} | Glucose {blood_glucose:>5} | {simulation_state}"
                )
            schedule[due_patient_id] = time.monotonic() + max(1.0, interval + state.rng.uniform(-jitter, jitter))
    except KeyboardInterrupt:
        print("\nSimulation stopped.")
    finally:
        client.loop_stop()
        client.disconnect()
        print("Disconnected from broker.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send realistic individual vital-sign streams over MQTT.")
    parser.add_argument("--broker", default=BROKER, help=f"MQTT broker host (default: {BROKER}).")
    parser.add_argument("--port", type=int, default=PORT, help=f"MQTT WebSocket port (default: {PORT}).")
    parser.add_argument("--topic", default=TOPIC, help=f"MQTT topic (default: {TOPIC}).")
    parser.add_argument("--mqtt-username", default=MQTT_USERNAME, help="Optional MQTT broker username.")
    parser.add_argument("--mqtt-password", default=MQTT_PASSWORD, help="Optional MQTT broker password.")
    parser.add_argument("--tls", action="store_true", default=None, help="Enable TLS for MQTT broker connection.")
    parser.add_argument("--ca-cert", default=MQTT_CA_CERT, help="Optional path to CA certificate bundle for TLS.")
    parser.add_argument("--interval", type=float, default=30.0, help="Average seconds between readings for each patient (default: 30).")
    parser.add_argument("--jitter", type=float, default=6.0, help="Random scheduling variation per reading in seconds (default: 6).")
    parser.add_argument("--seed", type=int, help="Optional deterministic random seed for demos.")
    parser.add_argument("--inject-artifact-bed", default=None, help="Optional patient ID to inject sensor artifacts into (e.g. A001).")
    parser.add_argument("--inject-artifact-type", choices=["probe_disconnect", "impossible_spo2", "impossible_hr", "apnea_fault"], default="probe_disconnect", help="Type of artifact to inject.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.interval <= 0 or args.jitter < 0:
        raise SystemExit("--interval must be positive and --jitter cannot be negative")
    run(
        args.interval,
        args.jitter,
        args.seed,
        broker=args.broker,
        port=args.port,
        topic=args.topic,
        mqtt_username=args.mqtt_username,
        mqtt_password=args.mqtt_password,
        tls=args.tls,
        ca_cert=args.ca_cert,
        inject_artifact_bed=args.inject_artifact_bed,
        inject_artifact_type=args.inject_artifact_type,
    )

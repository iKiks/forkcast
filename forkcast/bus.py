"""Event bus abstraction.

Locally, events flow in-process. When EVENTHUB_CONNECTION_STRING and
EVENTHUB_NAME are set (and ``azure-eventhub`` is installed), every match event
is also published to Azure Event Hubs, so Fabric Eventstream or other consumers
can subscribe to the same live feed.
"""
from __future__ import annotations

import json
import os


class Bus:
    def __init__(self):
        self.producer = None
        conn = os.getenv("EVENTHUB_CONNECTION_STRING")
        name = os.getenv("EVENTHUB_NAME")
        if conn and name:
            try:
                from azure.eventhub import EventHubProducerClient

                self.producer = EventHubProducerClient.from_connection_string(conn, eventhub_name=name)
            except Exception:
                self.producer = None

    @property
    def kind(self) -> str:
        return "azure-event-hubs" if self.producer else "in-process"

    def publish(self, events: list[dict]) -> None:
        if not self.producer or not events:
            return
        try:
            from azure.eventhub import EventData

            batch = self.producer.create_batch()
            for ev in events:
                batch.add(EventData(json.dumps(ev)))
            self.producer.send_batch(batch)
        except Exception:
            pass  # the live demo never depends on the cloud path


BUS = Bus()

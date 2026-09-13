import time

from pydantic import BaseModel, Field


class Consumer(BaseModel):
    consumer_id: str
    last_heartbeat: float = Field(default_factory=time.time)

class ConsumerGroup:
    def __init__(self, group_id: str) -> None:
        self.group_id = group_id
        self.consumers: dict[str, Consumer] = {}
        self.offsets: dict[str, int] = {}  # topic -> offset
        self.heartbeat_timeout = 30.0

    def register_consumer(self, consumer_id: str) -> None:
        self.consumers[consumer_id] = Consumer(consumer_id=consumer_id)

    def heartbeat(self, consumer_id: str) -> None:
        if consumer_id in self.consumers:
            self.consumers[consumer_id].last_heartbeat = time.time()

    def commit_offset(self, topic: str, offset: int) -> None:
        self.offsets[topic] = offset

    def get_offset(self, topic: str) -> int:
        return self.offsets.get(topic, 0)

    def rebalance(self) -> None:
        now = time.time()
        dead_consumers = [
            cid for cid, c in self.consumers.items()
            if now - c.last_heartbeat > self.heartbeat_timeout
        ]
        for cid in dead_consumers:
            del self.consumers[cid]

class ConsumerGroupCoordinator:
    def __init__(self) -> None:
        self.groups: dict[str, ConsumerGroup] = {}

    def get_group(self, group_id: str) -> ConsumerGroup:
        if group_id not in self.groups:
            self.groups[group_id] = ConsumerGroup(group_id)
        return self.groups[group_id]

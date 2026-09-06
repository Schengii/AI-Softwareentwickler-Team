class KafkaManager:
    def send_event(self, topic: str, payload: dict):
        if not payload:
            raise ValueError("Payload cannot be empty")
        return {"status": "sent", "topic": topic}

kafka_manager = KafkaManager()

from enum import Enum


class EventType(str, Enum):
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    ORDER_CREATED = "order.created"
    ORDER_COMPLETED = "order.completed"
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_FAILED = "payment.failed"
    SYSTEM_ALERT = "system.alert"
    CUSTOM = "custom"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"

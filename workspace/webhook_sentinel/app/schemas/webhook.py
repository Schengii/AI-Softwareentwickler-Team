from pydantic import BaseModel, HttpUrl, Field, ConfigDict
from typing import List, Optional, Any, Dict
from datetime import datetime
from uuid import UUID

class SubscriptionCreate(BaseModel):
    target_url: HttpUrl = Field(..., description="The URL to send webhooks to")
    secret: str = Field(..., description="Secret used to sign the webhook payload via HMAC-SHA256")
    event_types: List[str] = Field(..., description="List of event types to subscribe to, e.g., ['user.created', 'order.shipped']")

class SubscriptionResponse(BaseModel):
    id: UUID
    target_url: str
    secret: str
    event_types: List[str]
    is_active: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class EventPublish(BaseModel):
    event_id: str = Field(..., description="Unique identifier for the event")
    event_type: str = Field(..., description="Type of the event, e.g., 'user.created'")
    payload: Dict[str, Any] = Field(..., description="The actual event data")

class DeliveryResponse(BaseModel):
    id: UUID
    subscription_id: UUID
    event_id: str
    payload: Dict[str, Any]
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    attempt: int
    delivered_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

import pytest
from pydantic import TypeAdapter, ValidationError
from schemas import VoteEvent, PollUpdateEvent, WSMessage

# WSMessage ist ein Union[...]-Typalias, kein BaseModel - TypeAdapter validiert gegen
# ein solches Union direkt (WSMessage selbst hat kein .model_validate()).
_ws_message_adapter = TypeAdapter(WSMessage)

def test_ws_message_validation():
    # Valid VoteEvent
    vote_data = {"type": "vote", "option_id": 1}
    msg = VoteEvent(**vote_data)
    assert msg.type == "vote"
    assert msg.option_id == 1

    # Valid PollUpdateEvent
    update_data = {"type": "poll_update", "message": "test", "total_votes": 5}
    msg = PollUpdateEvent(**update_data)
    assert msg.type == "poll_update"
    assert msg.total_votes == 5

    # Invalid structure
    with pytest.raises(ValidationError):
        VoteEvent(type="vote", option_id="not_an_int")

    # Union validation
    data = {"type": "vote", "option_id": 10}
    validated = _ws_message_adapter.validate_python(data)
    assert isinstance(validated, VoteEvent)

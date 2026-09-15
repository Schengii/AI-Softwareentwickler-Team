import pytest
from pydantic import ValidationError

from app.schemas import SnippetCreate, SnippetUpdate


def test_snippet_create_validation():
    with pytest.raises(ValidationError):
        SnippetCreate(title="", code="print('hello')", language="python")
    
    with pytest.raises(ValidationError):
        SnippetCreate(title="Test", code="", language="python")
        
    with pytest.raises(ValidationError):
        SnippetCreate(title="Test", code="print('hello')", language="")
        
    snippet = SnippetCreate(title="Test", code="print('hello')", language="python")
    assert snippet.title == "Test"

def test_snippet_update_validation():
    with pytest.raises(ValidationError):
        SnippetUpdate(title="")

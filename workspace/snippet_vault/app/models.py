from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship

from .database import Base

snippet_tags = Table(
    "snippet_tags",
    Base.metadata,
    Column("snippet_id", Integer, ForeignKey("snippets.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

class Snippet(Base):
    __tablename__ = "snippets"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    language = Column(String)
    tags = relationship("Tag", secondary=snippet_tags)

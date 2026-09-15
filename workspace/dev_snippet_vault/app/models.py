from sqlalchemy import DDL, Boolean, Column, Integer, String, Text, event

from app.database import Base


class Snippet(Base):
    __tablename__ = "snippets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    code = Column(Text, nullable=False)
    language = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(String, nullable=True) # Komma-separierte Tags
    is_favorite = Column(Boolean, default=False)

# FTS5 Setup für Volltextsuche
trigger_ddl = DDL("""
CREATE VIRTUAL TABLE IF NOT EXISTS snippets_fts USING fts5(title, description, code, tags, content='snippets', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS snippets_ai AFTER INSERT ON snippets BEGIN
  INSERT INTO snippets_fts(rowid, title, description, code, tags) VALUES (new.id, new.title, new.description, new.code, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS snippets_ad AFTER DELETE ON snippets BEGIN
  INSERT INTO snippets_fts(snippets_fts, rowid, title, description, code, tags) VALUES('delete', old.id, old.title, old.description, old.code, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS snippets_au AFTER UPDATE ON snippets BEGIN
  INSERT INTO snippets_fts(snippets_fts, rowid, title, description, code, tags) VALUES('delete', old.id, old.title, old.description, old.code, old.tags);
  INSERT INTO snippets_fts(rowid, title, description, code, tags) VALUES (new.id, new.title, new.description, new.code, new.tags);
END;
""")

event.listen(Snippet.__table__, 'after_create', trigger_ddl)

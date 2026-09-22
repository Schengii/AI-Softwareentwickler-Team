import pytest
import pytest_asyncio
from app.core.vault import VaultManager


@pytest_asyncio.fixture(scope="function")
async def temp_vault(tmp_path):
    """Initialisiert einen isolierten temporären Vault für jeden Test."""
    manager = VaultManager(vault_path=str(tmp_path))
    await manager.initialize_vault()
    return manager


@pytest.mark.asyncio
async def test_vault_initialization(temp_vault: VaultManager):
    """Prüft, ob Standardordner bei Vault-Initialisierung korrekt angelegt werden."""
    folders = await temp_vault.list_folders()
    assert "01 Projects" in folders
    assert "02 Areas" in folders
    assert "03 Resources" in folders
    assert "04 Archive" in folders


@pytest.mark.asyncio
async def test_vault_save_and_get_note_roundtrip(temp_vault: VaultManager):
    """Schreiben-dann-Lesen Roundtrip für Notizen im Vault."""
    rel_path = "01 Projects/smart-hub.md"
    content = "# Smart Knowledge Hub\n\nDas Kernprojekt für das Zettelkasten-System."
    frontmatter = {"type": "project", "tags": ["python", "fastapi"]}

    saved = await temp_vault.save_note(rel_path, content, frontmatter)
    assert saved["path"] == rel_path
    assert saved["title"] == "Smart Knowledge Hub"
    assert "python" in saved["tags"]

    # Notiz per get_note wieder einlesen
    read_note = await temp_vault.get_note(rel_path)
    assert read_note is not None
    assert read_note["path"] == rel_path
    assert read_note["title"] == "Smart Knowledge Hub"
    assert read_note["frontmatter"]["type"] == "project"
    assert "Das Kernprojekt für das Zettelkasten-System." in read_note["content"]


@pytest.mark.asyncio
async def test_vault_tree_structure(temp_vault: VaultManager):
    """Prüft die hierarchische Baumstruktur (Tree View)."""
    await temp_vault.save_note("01 Projects/Alpha.md", "# Project Alpha")
    await temp_vault.save_note("01 Projects/Sub/Beta.md", "# Subproject Beta")
    await temp_vault.save_note("02 Areas/Health.md", "# Health")

    tree = await temp_vault.get_tree()
    assert isinstance(tree, list)
    
    # 01 Projects finden
    projects_folder = next((item for item in tree if item["name"] == "01 Projects"), None)
    assert projects_folder is not None
    assert projects_folder["type"] == "directory"
    
    children_names = [child["name"] for child in projects_folder.get("children", [])]
    assert "Alpha.md" in children_names
    assert "Sub" in children_names


@pytest.mark.asyncio
async def test_vault_delete_note(temp_vault: VaultManager):
    """Prüft das Löschen einer existierenden Notiz."""
    rel_path = "02 Areas/TempNote.md"
    await temp_vault.save_note(rel_path, "# Temp Note")
    assert await temp_vault.note_exists(rel_path) is True

    deleted = await temp_vault.delete_note(rel_path)
    assert deleted is True
    assert await temp_vault.note_exists(rel_path) is False

    # Erneutes Löschen soll False liefern
    deleted_again = await temp_vault.delete_note(rel_path)
    assert deleted_again is False


@pytest.mark.asyncio
async def test_vault_path_traversal_prevention(temp_vault: VaultManager):
    """Sicherheits-Check: Path Traversal Versuche müssen mit ValueError abgefangen werden."""
    with pytest.raises(ValueError):
        await temp_vault.save_note("../../../etc/passwd", "malicious content")

    with pytest.raises(ValueError):
        await temp_vault.get_note("../outside.md")

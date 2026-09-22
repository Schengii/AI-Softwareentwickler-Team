
# 2. Fix app/main.py
with open("app/main.py", "r") as f:
    content = f.read()
if "setup_security(app)" not in content:
    lines = content.splitlines()
    out = []
    for line in lines:
        out.append(line)
        if line.startswith("app = FastAPI"):
            out.append("setup_security(app)")
        if line.startswith("from fastapi import FastAPI"):
            out.append("from app.core.security import setup_security")
    with open("app/main.py", "w") as f:
        f.write("\n".join(out))

# 3. Fix app/models/event.py
with open("app/models/event.py", "r") as f:
    content = f.read()
if "validate_payload_size" not in content:
    lines = content.splitlines()
    out = []
    has_imported_json = False
    for line in lines:
        if line.startswith("from pydantic import BaseModel"):
            if "field_validator" not in line:
                line = line.replace("BaseModel", "BaseModel, field_validator")
            out.append(line)
            out.append("import json")
            has_imported_json = True
            continue
        out.append(line)
        if line.startswith("class EventCreate"):
            out.append("    @field_validator('payload', mode='before')")
            out.append("    @classmethod")
            out.append("    def validate_payload_size(cls, v):")
            out.append("        if v is not None:")
            out.append("            size = len(json.dumps(v)) if isinstance(v, dict) else len(str(v))")
            out.append("            if size > 65536:")
            out.append("                raise ValueError('Payload exceeds 64KB limit')")
            out.append("        return v")
    if not has_imported_json:
        out.insert(0, "import json")
        out.insert(0, "from pydantic import field_validator")
    with open("app/models/event.py", "w") as f:
        f.write("\n".join(out))

# 4. Fix app/services/event_service.py
with open("app/services/event_service.py", "r") as f:
    content = f.read()
if "is_safe_url" not in content:
    lines = content.splitlines()
    out = []
    for line in lines:
        if line.startswith("class EventService"):
            out.insert(0, "from app.core.security import is_safe_url")
        out.append(line)
        if "def dispatch" in line or "def publish" in line:
            out.append("        if hasattr(event, 'url') and event.url and not is_safe_url(event.url):")
            out.append("            raise ValueError('Unsafe URL detected')")
            out.append("        if hasattr(event, 'webhook_url') and event.webhook_url and not is_safe_url(event.webhook_url):")
            out.append("            raise ValueError('Unsafe URL detected')")
            out.append("        if isinstance(event, dict) and 'url' in event and not is_safe_url(event['url']):")
            out.append("            raise ValueError('Unsafe URL detected')")
    with open("app/services/event_service.py", "w") as f:
        f.write("\n".join(out))

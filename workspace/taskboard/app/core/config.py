import secrets

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    PROJECT_NAME: str = "TaskTimer"
    API_V1_STR: str = "/api/v1"
    # SECRET_KEY niemals als hartcodiertes Literal im Quellcode. Fehlt die Umgebungsvariable
    # (z.B. lokaler Demo-Start ohne .env), wird zur Laufzeit ein zufaelliger Wert erzeugt statt
    # eines weiteren Literals oder eines zwingend erforderlichen Feldes, das den Start ohne .env
    # komplett blockiert - in Produktion IMMER per echter SECRET_KEY-Umgebungsvariable
    # ueberschreiben, sonst verlieren bereits ausgestellte JWTs bei jedem Neustart ihre Gueltigkeit.
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_hex(32))
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    # Explizite Liste erlaubter Host-Header statt Wildcard ("*") - ein Wildcard hebelt den
    # Schutz von TrustedHostMiddleware vor Host-Header-Injection/DNS-Rebinding komplett aus.
    # "testserver" ist der von starlette.testclient.TestClient fest verwendete Host
    # (base_url="http://testserver") - ohne ihn wuerde jeder Testaufruf ueber TestClient mit
    # 400 Invalid host header fehlschlagen. Per ALLOWED_HOSTS-Umgebungsvariable (kommagetrennt)
    # in Produktion auf die echte(n) Domain(s) ueberschreiben.
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1", "testserver"]
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "tasktimer"
    POSTGRES_PORT: str = "5432"
    # Optionaler direkter DSN-Override (docker-compose.yml setzt z.B.
    # DATABASE_URL=sqlite:///./test.db fuer einen leichtgewichtigen Demo-Start ohne eigenen
    # Postgres-Container) - bindet ueber validation_alias an dieselbe Umgebungsvariable
    # "DATABASE_URL", der Python-Attributname unterscheidet sich bewusst von der
    # DATABASE_URL-Property unten (Namenskollision zwischen Feld und Property waere sonst nicht
    # moeglich).
    DATABASE_URL_OVERRIDE: str | None = Field(default=None, validation_alias="DATABASE_URL")

    @property
    def DATABASE_URL(self) -> str:
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_SERVER,
                port=int(self.POSTGRES_PORT),
                # Pydantic v2's Url.build() haengt den fuehrenden "/" selbst an - ein Pfad MIT
                # fuehrendem "/" (wie zuvor) erzeugt sonst einen doppelten Slash ("//tasktimer").
                path=self.POSTGRES_DB,
            )
        )


settings = Settings()

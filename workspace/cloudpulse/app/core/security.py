import ipaddress
import socket
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost", "http://localhost:8000", "http://127.0.0.1:8000"]
    )
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

def validate_ssrf_safe_url(url_str: str) -> str:
    """
    Validates that the given URL does not point to an internal/private IP address.
    Raises ValueError if the URL is deemed unsafe.
    """
    parsed = urlparse(url_str)
    hostname = parsed.hostname
    
    if not hostname:
        raise ValueError("Invalid URL: Missing hostname")
        
    # Block obvious local hostnames
    if hostname.lower() in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        raise ValueError("SSRF blocked: Localhost is not allowed")
        
    try:
        # Resolve hostname to IP
        ip_address = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_address)
        
        # Check if IP is private, loopback, or reserved
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise ValueError(f"SSRF blocked: Private/Internal IP {ip_address} is not allowed")
            
    except socket.gaierror:
        # If DNS resolution fails, we let it pass here. The checker will just fail to connect.
        pass
        
    return url_str

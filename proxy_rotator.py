import json
import logging
import os
import random
import re
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("ProxyRotator")

PAKISTAN_ASNS = {"AS17557", "AS24499", "AS38264", "AS45595", "AS55803", "AS59191", "AS131295", "AS132278"}
IPINFO_URL = "https://ipinfo.io/json"

@dataclass
class ProxyEntry:
    host: str
    port: int
    protocol: str = "http"
    username: Optional[str] = None
    password: Optional[str] = None
    region: str = ""
    latency_ms: float = 0.0
    failures: int = 0

    @property
    def url(self) -> str:
        auth = f"{self.username}:{self.password}@" if self.username else ""
        return f"{self.protocol}://{auth}{self.host}:{self.port}"

    @property
    def dict(self) -> Dict[str, str]:
        return {"http": self.url, "https": self.url}


SOCKS5_URL_PATTERN = re.compile(r"socks5://(?:([^:@]+):([^@]+)@)?([^:]+):(.+)")

def parse_socks5_url(url: str) -> Optional[ProxyEntry]:
    m = SOCKS5_URL_PATTERN.match(url.strip())
    if not m:
        return None
    username, password, host, port_str = m.groups()
    try:
        port = int(port_str)
    except ValueError:
        logger.warning("Non-numeric port in proxy URL, using 1080: %s", url)
        port = 1080
    return ProxyEntry(
        host=host, port=port, protocol="socks5",
        username=username, password=password, region="user_provided",
    )

PLACEHOLDER_PROXY_POOL: List[ProxyEntry] = [
    # Tor default (requires Tor running on :9050)
    ProxyEntry(host="127.0.0.1", port=9050, protocol="socks5", region="tor"),
    # Common proxy ports to scan on localhost
    ProxyEntry(host="127.0.0.1", port=1080, protocol="socks5", region="local"),
    ProxyEntry(host="127.0.0.1", port=3128, protocol="http", region="local"),
    ProxyEntry(host="127.0.0.1", port=8080, protocol="http", region="local"),
    ProxyEntry(host="127.0.0.1", port=8118, protocol="http", region="local"),
]


class IPInspector:
    @staticmethod
    def current_identity() -> Dict[str, str]:
        try:
            r = requests.get(IPINFO_URL, timeout=10)
            if r.ok:
                data = r.json()
                return {
                    "ip": data.get("ip", "unknown"),
                    "country": data.get("country", "unknown"),
                    "region": data.get("region", "unknown"),
                    "city": data.get("city", "unknown"),
                    "org": data.get("org", "unknown"),
                    "asn": data.get("asn", ""),
                }
        except Exception as e:
            logger.warning("IPInfo check failed: %s", e)
        return {"ip": "unknown", "country": "unknown"}

    @staticmethod
    def is_pakistan(identity: Dict[str, str]) -> bool:
        if identity.get("country") == "PK":
            return True
        org = identity.get("org", "").upper()
        return any(asn in org for asn in PAKISTAN_ASNS)

    @staticmethod
    def public_ip() -> str:
        try:
            return requests.get("https://api.ipify.org", timeout=5).text.strip()
        except Exception:
            return "unknown"


class ProxyRotator:
    def __init__(self, pool: Optional[List[ProxyEntry]] = None):
        self.pool = pool or list(PLACEHOLDER_PROXY_POOL)
        self._current_index = 0
        self._proxy_file = Path(__file__).resolve().parent / "agent_data" / "proxy_pool.json"
        self._load_pool()

    def _load_pool(self) -> None:
        if self._proxy_file.exists():
            try:
                data = json.loads(self._proxy_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for entry in data:
                        e = ProxyEntry(**entry)
                        if not any(x.host == e.host and x.port == e.port for x in self.pool):
                            self.pool.append(e)
            except Exception:
                pass

    def save_pool(self) -> None:
        try:
            self._proxy_file.parent.mkdir(parents=True, exist_ok=True)
            data = [{"host": e.host, "port": e.port, "protocol": e.protocol,
                      "username": e.username, "password": e.password, "region": e.region} for e in self.pool]
            self._proxy_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to save proxy pool: %s", e)

    def current_proxy(self) -> Optional[Dict[str, str]]:
        if not self.pool:
            return None
        entry = self.pool[self._current_index % len(self.pool)]
        return entry.dict

    def rotate(self) -> Optional[Dict[str, str]]:
        if not self.pool:
            return None
        self._current_index = (self._current_index + 1) % len(self.pool)
        entry = self.pool[self._current_index]
        logger.info("Rotated to proxy: %s (%s)", entry.host, entry.region)
        return entry.dict

    def test_proxy(self, proxy: Dict[str, str]) -> bool:
        try:
            start = time.time()
            r = requests.get("https://api.ipify.org?format=json", proxies=proxy, timeout=10)
            latency = (time.time() - start) * 1000
            if r.ok:
                ip = r.json().get("ip", "?")
                logger.info("Proxy test OK: %s -> %s (%.0fms)", proxy.get("http"), ip, latency)
                return True
        except Exception:
            pass
        return False

    def find_working_proxy(self) -> Optional[Dict[str, str]]:
        random.shuffle(self.pool)
        for entry in self.pool:
            proxy = entry.dict
            if self.test_proxy(proxy):
                idx = self.pool.index(entry)
                self._current_index = idx
                return proxy
        logger.warning("No working proxy found in pool")
        return None

    def scan_local_ports(self) -> List[int]:
        found = []
        for port in [9050, 1080, 3128, 8080, 8118, 8888, 9090]:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    found.append(port)
                    if port not in [e.port for e in self.pool]:
                        self.pool.append(ProxyEntry(host="127.0.0.1", port=port,
                                                     protocol="socks5" if port == 9050 else "http",
                                                     region="local_scan"))
        if found:
            logger.info("Local proxy ports found: %s", found)
        return found

    def load_socks5_urls(self, urls: List[str]) -> int:
        """Parse and add SOCKS5 proxy URLs to the pool. Returns count added."""
        added = 0
        for url in urls:
            entry = parse_socks5_url(url)
            if entry:
                # Avoid duplicates
                if not any(e.host == entry.host and e.port == entry.port for e in self.pool):
                    self.pool.append(entry)
                    added += 1
        if added:
            logger.info("Loaded %d SOCKS5 proxies from URLs", added)
            self.save_pool()
        return added


def get_random_proxy(pool_path: Optional[str] = None) -> Optional[str]:
    """Pick a random proxy URL from the saved pool file."""
    path = Path(pool_path or Path(__file__).resolve().parent / "agent_data" / "proxy_pool.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            entry = random.choice(data)
            return ProxyEntry(**entry).url
    except Exception:
        pass
    return None


def make_stealth_request(url: str, **kwargs):
    """Make an HTTP request through a random proxy from the pool."""
    proxy_url = get_random_proxy()
    proxies = {"http": proxy_url, "https": proxy_url}
    if proxy_url:
        print(f"Requesting via stealth node: {proxy_url.split('@')[-1]}")
    else:
        print("No proxy in pool — requesting directly")
    return requests.get(url, proxies=proxies if proxy_url else None, **kwargs)

import logging
import asyncio
import aiohttp
from telethon import TelegramClient

logger = logging.getLogger(__name__)

COMMON_LOCAL_PROXIES = [
    None,  # Try direct connection first (works if VPN is in TUN mode)
]

# Dynamically add system proxies (like Psiphon's random ports)
import urllib.request
sys_proxies = urllib.request.getproxies()
if 'socks' in sys_proxies:
    import urllib.parse
    p = urllib.parse.urlparse(sys_proxies['socks'])
    COMMON_LOCAL_PROXIES.append(("socks5", p.hostname, p.port))
if 'http' in sys_proxies:
    import urllib.parse
    p = urllib.parse.urlparse(sys_proxies['http'])
    COMMON_LOCAL_PROXIES.append(("http", p.hostname, p.port))

COMMON_LOCAL_PROXIES.extend([
    ("socks5", "127.0.0.1", 10808),  # v2rayN / Nekoray
    ("http", "127.0.0.1", 10809),    # v2rayN / Nekoray HTTP
    ("http", "127.0.0.1", 7890),     # Clash
    ("socks5", "127.0.0.1", 7891),   # Clash SOCKS5
    ("socks5", "127.0.0.1", 1080),   # Generic SOCKS5
    ("http", "127.0.0.1", 8080),     # Generic HTTP
    ("socks5", "127.0.0.1", 2080),   # Nekobox generic
])

async def check_proxy(proxy_tuple) -> bool:
    """Quickly check if a proxy port is open and reachable."""
    if proxy_tuple is None:
        return True # Direct connection is always "open" conceptually, we test it via Telegram
    
    proxy_type, host, port = proxy_tuple[:3]
    try:
        # Just try to open a TCP connection to the local port
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), 
            timeout=1.0
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

async def fetch_public_proxies():
    """Fetches a list of public proxies as a last resort."""
    url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"
    proxies = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    lines = text.strip().split("\n")
                    # Grab top 10 to try
                    for line in lines[:10]:
                        if ":" in line:
                            host, port = line.split(":")
                            proxies.append(("socks5", host.strip(), int(port.strip())))
    except Exception as e:
        logger.warning(f"Failed to fetch public proxies: {e}")
    return proxies

async def get_connected_client(session, api_id, api_hash, explicit_proxy=None):
    """Attempts to create and connect a client using explicit proxy, local VPN ports, or public proxies."""
    
    if explicit_proxy:
        import urllib.parse
        parsed = urllib.parse.urlparse(explicit_proxy)
        if parsed.username:
            proxy_tuple = (parsed.scheme, parsed.hostname, parsed.port, True, parsed.username, parsed.password)
        else:
            proxy_tuple = (parsed.scheme, parsed.hostname, parsed.port)
        
        client = TelegramClient(session, api_id, api_hash, proxy=proxy_tuple)
        await client.connect()
        if client.is_connected():
            return client
        logger.warning(f"Explicit proxy {explicit_proxy} failed. Falling back to auto-discovery...")

    # 1. Test local VPN ports first (instant)
    for proxy in COMMON_LOCAL_PROXIES:
        if await check_proxy(proxy):
            try:
                client = TelegramClient(
                    session, api_id, api_hash, 
                    proxy=proxy, 
                    connection_retries=1, 
                    timeout=3
                )
                logger.info(f"Attempting to connect to Telegram using local proxy: {proxy}")
                await client.connect()
                if client.is_connected():
                    logger.info(f"Successfully connected to Telegram using proxy: {proxy}")
                    return client
            except Exception as e:
                logger.debug(f"Proxy {proxy} failed to connect to Telegram: {e}")

    # 2. If no local VPN worked, try public proxies
    logger.info("No local VPN proxy worked. Fetching public proxies...")
    public_proxies = await fetch_public_proxies()
    for proxy in public_proxies:
        try:
            client = TelegramClient(
                session, api_id, api_hash, 
                proxy=proxy,
                connection_retries=1,
                timeout=2
            )
            logger.info(f"Attempting public proxy: {proxy}")
            await client.connect()
            if client.is_connected():
                logger.info(f"Successfully connected using public proxy: {proxy}")
                return client
        except Exception:
            pass

    logger.error("All auto-proxy attempts failed. Could not connect to Telegram.")
    raise ConnectionError("Could not connect to Telegram via any proxy.")


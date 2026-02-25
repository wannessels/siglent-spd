import asyncio


class SCPIConnection:
    """Async TCP connection to a SCPI instrument."""

    def __init__(self, host: str, port: int = 5025, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )

    async def disconnect(self):
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def _ensure_connected(self):
        if self._writer is None or self._writer.is_closing():
            await self.connect()

    async def query(self, command: str) -> str:
        """Send a command and return the response (strips trailing whitespace)."""
        async with self._lock:
            await self._ensure_connected()
            self._writer.write(f"{command}\n".encode("ascii"))
            await self._writer.drain()
            try:
                response = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=self.timeout,
                )
                return response.decode("ascii").strip()
            except asyncio.TimeoutError:
                # Reconnect to flush any stale data in the buffer
                await self.disconnect()
                raise

    async def write(self, command: str):
        """Send a command with no response expected."""
        async with self._lock:
            await self._ensure_connected()
            self._writer.write(f"{command}\n".encode("ascii"))
            await self._writer.drain()
            await asyncio.sleep(0.1)  # inter-command delay

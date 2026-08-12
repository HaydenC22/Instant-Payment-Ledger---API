import httpx


class HttpxWebhookSender:
    """Backs app.domain.webhooks.dispatch.WebhookSender using a shared httpx.AsyncClient."""

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def send(self, *, url: str, headers: dict[str, str], body: bytes) -> int:
        response = await self._client.post(url, headers=headers, content=body)
        return response.status_code

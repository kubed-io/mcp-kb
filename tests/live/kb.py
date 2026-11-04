"""Helpers for the live checks: every one can be scoped to a library."""

from __future__ import annotations

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from tests.test_skills_extension import request

META = "io.kubed.mcp-kb/agent"


def connect(kb_url: str, library: str | None = None, mode: str = "auto") -> Client:
    headers = {"Kb-Library": library} if library else {}
    return Client(StreamableHttpTransport(f"{kb_url}/mcp", headers=headers), mode=mode)


async def rpc(kb_url: str, method: str, library: str | None = None, **params) -> dict:
    async with connect(kb_url, library) as client:
        return await request(client, method, **params)


def health(kb_url: str) -> dict:
    response = httpx.get(f"{kb_url}/health")
    response.raise_for_status()
    return response.json()


async def agent_names(kb_url: str, library: str) -> list[str]:
    listing = await rpc(kb_url, "agents/list", library)
    return [card["name"] for card in listing["agents"]]


async def definition(kb_url: str, name: str, library: str | None = None) -> dict:
    return await rpc(kb_url, "agents/get", library, name=name)


async def owners(kb_url: str, library: str) -> dict[str, str]:
    result = {}
    for name in await agent_names(kb_url, library):
        got = await definition(kb_url, name, library)
        result[name.removeprefix(f"{library}_")] = got["_meta"][META]["plugin"]
    return result


async def prompts(kb_url: str, library: str) -> dict[str, str | None]:
    async with connect(kb_url, library) as client:
        return {p.name: p.description for p in await client.list_prompts()}


async def prompt_text(kb_url: str, name: str, library: str) -> str:
    async with connect(kb_url, library) as client:
        got = await client.get_prompt(name)
    return got.messages[0].content.text


async def read(kb_url: str, uri: str, library: str | None = None) -> str:
    async with connect(kb_url, library) as client:
        return (await client.read_resource(uri))[0].text

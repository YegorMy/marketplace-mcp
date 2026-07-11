#!/usr/bin/env python3
import argparse
import asyncio
import json

from marketplaces_mcp.mcp_server.server import marketplaces_search


async def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke search script")
    parser.add_argument("--query", default="бумага a4")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--marketplaces", default="")
    parser.add_argument("--strategy", default="auto")
    args = parser.parse_args()

    marketplaces = [item.strip() for item in args.marketplaces.split(",") if item.strip()] or None
    response = await marketplaces_search(
        query=args.query,
        marketplaces=marketplaces,
        limit=args.limit,
        strategy=args.strategy,
    )
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2, default=str))


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()

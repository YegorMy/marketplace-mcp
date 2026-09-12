#!/usr/bin/env python3
"""Explicit read-only live canary for Ozon Travel flights and hotels."""

from __future__ import annotations

import argparse
import asyncio
import json

from marketplaces_mcp.adapters import OzonTravelAdapter


async def run(args: argparse.Namespace) -> dict[str, object]:
    adapter = OzonTravelAdapter()
    if args.kind == "flights":
        offers, warnings, source_url = await adapter.search_flights(
            args.origin,
            args.destination,
            args.departure_date,
            args.return_date,
            adults=args.adults,
            children=args.children,
            infants=args.infants,
            cabin_class=args.cabin_class,
            direct_only=args.direct_only,
            sort=args.sort,
            limit=args.limit,
            strategy=args.strategy,
        )
    else:
        offers, warnings, source_url = await adapter.search_hotels(
            args.destination,
            args.check_in,
            args.check_out,
            adults=args.adults,
            rooms=args.rooms,
            min_rating=args.min_rating,
            stars=args.stars,
            max_total_price=args.max_total_price,
            sort=args.sort,
            include_rates=not args.no_rates,
            limit=args.limit,
            strategy=args.strategy,
        )
    return {
        "kind": args.kind,
        "source_url": source_url,
        "warnings": warnings,
        "results": [offer.model_dump(mode="json") for offer in offers],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument(
        "--strategy", choices=("auto", "hive_web", "legacy"), default="auto"
    )
    root.add_argument("--limit", type=int, default=5)
    commands = root.add_subparsers(dest="kind", required=True)

    flights = commands.add_parser("flights")
    flights.add_argument("origin", help="IATA code or a common city name")
    flights.add_argument("destination", help="IATA code or a common city name")
    flights.add_argument("departure_date", help="YYYY-MM-DD")
    flights.add_argument("--return-date")
    flights.add_argument("--adults", type=int, default=1)
    flights.add_argument("--children", type=int, default=0)
    flights.add_argument("--infants", type=int, default=0)
    flights.add_argument(
        "--cabin-class", choices=("economy", "comfort", "business"), default="economy"
    )
    flights.add_argument("--direct-only", action="store_true")
    flights.add_argument(
        "--sort", choices=("price", "duration", "departure"), default="price"
    )

    hotels = commands.add_parser("hotels")
    hotels.add_argument(
        "destination", help="city, region, or Ozon Travel hotel/category URL"
    )
    hotels.add_argument("check_in", help="YYYY-MM-DD")
    hotels.add_argument("check_out", help="YYYY-MM-DD")
    hotels.add_argument("--adults", type=int, default=2)
    hotels.add_argument("--rooms", type=int, default=1)
    hotels.add_argument("--min-rating", type=float)
    hotels.add_argument("--stars", type=int, nargs="+", choices=range(1, 6))
    hotels.add_argument("--max-total-price", type=float)
    hotels.add_argument(
        "--sort", choices=("price", "rating", "distance"), default="price"
    )
    hotels.add_argument("--no-rates", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build probe 3's verbatim situation copy, stored answer pairs, and seeded map."""

import json

import shared


def main():
    pairs = shared.build_pairs()
    mapping = shared.build_mapping(pairs)
    shared.validate_mapping(mapping, pairs)
    print(f"situations copied verbatim: {len(pairs)}")
    print(f"pairs stored from probe 2 main-phase answers: {len(pairs)}")
    print(f"seeded mapping ({shared.SEED}) written to {shared.MAP.name}")
    x_law = sum(1 for side in mapping.values() if side["X"] == "law")
    print(f"X=law in {x_law}/20 situations (a coin flip, not a signal)")
    print(json.dumps(mapping, ensure_ascii=False))


if __name__ == "__main__":
    main()

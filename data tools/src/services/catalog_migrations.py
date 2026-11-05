"""Upgrade specific untouched demo seeds, never overwrite a customized SQL row."""
import hashlib
import json

# Exact pre-28.10.2026 demo records. The update only fixes pet-transfer flags.
LEGACY_ROUTE_HASHES = {
    'dubai': 'ebaab4a5abb5d690afd5ab83dc9777272f08d07296b326105cca703135e16d3e',
    'bali': 'b7c7e79ed7d9bae00df01ff14bdb2cacf33d208ef625bdd8d903da35b63ca658',
}


def is_legacy_demo_route(record):
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    return digest == LEGACY_ROUTE_HASHES.get(record.get('id'))

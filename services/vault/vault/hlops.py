"""The vault's only door to Hyperliquid: thin wrappers over `hl.accounts`.

Imported lazily so `vault` loads without `hl` (and hl.env can import vault
without a cycle). Tests replace `post_signed_action` / `extra_agents` here;
the signing helpers are pure and run for real.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _acc() -> Any:
    from hl import accounts  # type: ignore[import-not-found]
    return accounts


def hyperliquid_chain() -> str:
    return _acc().hyperliquid_chain()


def approve_agent_action(agent_address: str, agent_name: str, nonce: int,
                         chain_id: Optional[str] = None) -> Dict[str, Any]:
    return _acc().approve_agent_action(agent_address, agent_name, nonce, chain_id)


def approve_agent_typed_data(action: Dict[str, Any]) -> Dict[str, Any]:
    return _acc().approve_agent_typed_data(action)


def split_signature(sig_hex: str) -> Dict[str, Any]:
    return _acc().split_signature(sig_hex)


def recover_typed_signer(typed_data: Dict[str, Any], sig: Dict[str, Any]) -> str:
    return _acc().recover_typed_signer(typed_data, sig)


def sign_approve_agent(main_key: str, agent_address: str, agent_name: str,
                       nonce: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return _acc().sign_approve_agent(main_key, agent_address, agent_name, nonce)


def sign_usd_send(main_key: str, destination: str, amount: str,
                  time_ms: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return _acc().sign_usd_send(main_key, destination, amount, time_ms)


def user_action(kind: str, amount: str, nonce: int, to_perp: Optional[bool] = None,
                destination: Optional[str] = None, chain_id: Optional[str] = None) -> Dict[str, Any]:
    return _acc().user_action(kind, amount, nonce, to_perp=to_perp, destination=destination, chain_id=chain_id)


def user_action_typed_data(kind: str, action: Dict[str, Any]) -> Dict[str, Any]:
    return _acc().user_action_typed_data(kind, action)


def user_action_keys(kind: str) -> set:
    return _acc().user_action_keys(kind)


def action_type(kind: str) -> str:
    return _acc().action_type(kind)


def sign_user_action(main_key: str, kind: str, amount: str, nonce: int, to_perp: Optional[bool] = None,
                     destination: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return _acc().sign_user_action(main_key, kind, amount, nonce, to_perp=to_perp, destination=destination)


def post_signed_action(action: Dict[str, Any], nonce: int, signature: Dict[str, Any]) -> Dict[str, Any]:
    return _acc().post_signed_action(action, nonce, signature)


def extra_agents(user: str) -> Optional[List[Dict[str, Any]]]:
    return _acc().extra_agents(user)

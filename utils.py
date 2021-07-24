import os
import json
import functools

from typing import Callable
from exceptions import InvalidToken
from eth_typing import AnyAddress
from web3.main import Web3
from web3.types import Address, Any
from web3.contract import Contract


ETH_ADDRESS = "0x0000000000000000000000000000000000000000"


def validate_address(a: AnyAddress) -> None:
    assert addr_to_str(a)


def load_contract(abi_name: str, address: AnyAddress, w3: Web3) -> Contract:
    return w3.eth.contract(address=address, abi=load_abi(abi_name))


def load_abi(name: str) -> str:
    path = f"{os.path.dirname(os.path.abspath(__file__))}/abis/"
    
    with open(os.path.abspath(path + f"{name}.abi")) as f:
        abi: str = json.load(f)

    return abi


def str_to_addr(s: str) -> AnyAddress:
    if s.startswith("0x"):
        return Address(bytes.fromhex(s[2:]))
    else:
        raise Exception("Could't convert string {s} to AnyAddress")


def addr_to_str(a: AnyAddress, ) -> str:
    if isinstance(a, bytes):
        addr: str = Web3.toChecksumAddress("0x" + bytes(a).hex())
        return addr

    elif isinstance(a, str):
        if a.startswith("0x"):
            addr = Web3.toChecksumAddress(a)
            return addr
        else:
            raise InvalidToken(a)


def check_approval(method: Callable) -> Callable:
    """
    Decorator to check if user is approved for a token. It approves them if they
    need to be approved.
    """
    @functools.wraps(method)
    def approved(self: Any, *args: Any, **kwargs: Any) -> Any:
        token = args[0] if args[0] != ETH_ADDRESS else None
        token_two = None

        if method.__name__ == "make_trade" or method.__name__ == "make_trade_output":
            token_two = args[1] if args[1] != ETH_ADDRESS else None

        if token:
            is_approved = self._is_approved(token)
            if not is_approved:
                self.approve(token)
        if token_two:
            is_approved = self._is_approved(token_two)
            if not is_approved:
                self.approve(token_two)
        return method(self, *args, **kwargs)

    return approved

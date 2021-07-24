import pytest
import shutil
import subprocess
import logging
import os

from time import time, sleep
from web3.main import Web3
from pancakeswap import Pancakeswap
from typing import Generator
from dataclasses import dataclass
from contextlib import contextmanager
from exceptions import InvalidToken


logger = logging.getLogger(__name__)


@dataclass
class GanacheInstance:
    """
    Object that contains information of our local mainnet fork.
    """
    provider: str
    address: str
    pk: str


@pytest.fixture(scope="module")
def ganache() -> Generator[GanacheInstance, None, None]:
    """
    Method that runs ganache-cli and allows us to create a local fork of the mainnet
    provided to run the tests in a simulated environment. Creates fixture of the GanacheInstance
    dataclass
    """
    PROVIDER = 'https://bsc-dataseed.binance.org/'

    if not shutil.which("ganache-cli"):
        raise Exception(
            "ganache-cli was not found in PATH, you can install it with `npm install -g ganache-cli`"
        )
    port = 10999
    
    p = subprocess.Popen(
        f"ganache-cli --port {port} -s test --networkId 56 --fork {PROVIDER}",
        shell=True
    )
    
    # Address #1 when ganache is run with `-s test`, it starts with 100 ETH
    address = "0x94e3361495bD110114ac0b6e35Ed75E77E6a6cFA"
    pk = "0x6f1313062db38875fb01ee52682cbf6a8420e92bfbc578c5d4fdc0a32c50266f"
    
    sleep(3)

    yield GanacheInstance(f"http://127.0.0.1:{port}", address, pk)
    p.kill()
    p.wait()


@pytest.fixture(scope="module")
def web3(ganache: GanacheInstance):
    """
    Method that returns fixture of Web3 instance that utilizes our local fork
    of the given mainnet provided by ganache-cli
    """
    w3 = Web3(Web3.HTTPProvider(ganache.provider, request_kwargs={"timeout": 60}))
    return w3


@pytest.fixture(scope="module")
def client(web3: Web3, ganache: GanacheInstance) -> Pancakeswap:
    """
    Method that returns fixture of an instance of our Pancakeswap client.

    :param web3     -
    :param ganache  -

    :returns (Pancakeswap) instance of the Pancakeswap class
    """
    return Pancakeswap(ganache.address, ganache.pk, web3=web3)


@contextmanager
def does_not_raise():
    yield


@pytest.mark.usefixtures("client", "web3")
class TestPancakeswap(object):
    ONE_BNB = 10 ** 18
    ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
    bnb = "0x0000000000000000000000000000000000000000"
    wbnb = Web3.toChecksumAddress("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
    dai = Web3.toChecksumAddress("0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3")
    usdc = Web3.toChecksumAddress("0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d")


    def test_sample_method(self):
        one = 1

        assert one == 1

    def test_deadline(self, client: Pancakeswap):
        ten_minutes_in_seconds = 10 * 60
        now = int(time())
        deadline = client._deadline()

        assert  (now + ten_minutes_in_seconds) == deadline

    def test_get_eth_balance(self, client: Pancakeswap):
        balance = client.get_eth_balance()
        assert balance == 100 * self.ONE_BNB

    def test_get_token_balance(self, client: Pancakeswap):
        bnb_balance = client.get_token_balance(self.bnb)
        dai_balance = client.get_token_balance(self.dai)

        assert bnb_balance == 100 * self.ONE_BNB
        assert dai_balance == 0

    def test_get_weth_address(self, client: Pancakeswap):
        wbnb_client_address = client.get_weth_address()

        assert wbnb_client_address == self.wbnb

    @pytest.mark.parametrize(
        "token, qty",
        [(dai, ONE_BNB)]
    )
    def test_get_eth_token_input_price(self, client: Pancakeswap, token, qty):
        price = client.get_eth_token_input_price(token, qty)
        assert price

    
    @pytest.mark.parametrize(
        "input_token, output_token, qty, recipient, expectation",
        [
            # ETH -> Token
            (bnb, dai, ONE_BNB*2, None, does_not_raise),
            # Token -> Token
            (dai, usdc, int(ONE_BNB*1.5), None, does_not_raise),
            # Token -> ETH
             (usdc, bnb, ONE_BNB, None, does_not_raise),
             (dai, "btc", ONE_BNB, None, lambda: pytest.raises(InvalidToken)),
        ],
    )
    def test_make_trade(
        self,
        client: Pancakeswap,
        web3: Web3,
        ganache: GanacheInstance,
        input_token,
        output_token,
        qty: int,
        recipient,
        expectation,
    ):
        with expectation():
            bal_in_before = client.get_token_balance(input_token)

            txid = client.make_trade(input_token, output_token, qty, 100, ganache.address, ganache.pk, recipient)
            tx = web3.eth.waitForTransactionReceipt(txid)
            assert tx.status

            # TODO: Checks for ETH, taking gas into account
            bal_in_after = client.get_token_balance(input_token)
            if input_token != self.bnb:
                assert bal_in_before - qty == bal_in_after
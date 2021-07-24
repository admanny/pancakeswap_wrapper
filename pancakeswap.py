import functools
import logging
import os
import time
import utils

from web3 import Web3
from web3.contract import ContractFunction
from web3.types import Any, Wei, ChecksumAddress, TxParams, Nonce, HexBytes
from typing import Union, Optional, Callable
from exceptions import InsufficientBalance
from eth_typing import AnyAddress
from eth_utils import is_same_address


logger = logging.getLogger(__name__)


class Pancakeswap:
    """
        Pancakeswap is a wrapper class that provides functionality to interact with
        pancakeswap.finance contracts. 
        
        Supports only PancakeswapV2.
    """
    def __init__(self, address: Union[str, AnyAddress], private_key: str, provider: str = None, 
        web3: Web3 = None, version:int = 2, max_slippage: float = 0.1) -> None:
        """
        Initiates the Pancakeswap wrapper

        :param: address      - User's wallet address
        :param: private_key  - User's wallet private key
        :param: provider     -
        :param: web3         -
        :param: version      - Version of Pancakeswap to use (currently only supporting V2)
        :param: max_slippage - Maximum slippage willing to tolerate on a trade
        """

        self.address: AnyAddress = utils.str_to_addr(address) if isinstance(address, str) else address
        self.private_key = private_key
        self.version = version
        self.max_slippage = max_slippage

        if web3:
            self.w3 = web3
        else:
            self.provider = provider or os.environ["PROVIDER"]
            self.w3 = Web3(Web3.HTTPProvider(self.provider, request_kwargs={"timeout": 60}))
        
        self.last_nonce: Nonce = self.w3.eth.get_transaction_count(self.address)

        
        self.factory_address_v2 = utils.str_to_addr('0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73')
        self.router_address_v2  = utils.str_to_addr('0x10ED43C718714eb63d5aA57B78B54704E256024E')

        self.factory = utils.load_contract("factory", self.factory_address_v2, self.w3)
        self.router = utils.load_contract("router02", self.router_address_v2, self.w3)
    
        self.max_approval_hex = f"0x{64 * 'f'}"
        self.max_approval_int = int(self.max_approval_hex, 16)
        self.max_approval_check_hex = f"0x{15 * '0'}{49 * 'f'}"
        self.max_approval_check_int = int(self.max_approval_check_hex, 16)


    def _build_and_send_approval(self, function: ContractFunction) -> HexBytes:
        """Build and send a transaction."""
        params = {
            "from": utils.addr_to_str(self.address),
            "value": Wei(0),
            "gas": Wei(250000),
            "nonce": max(
                self.last_nonce, self.w3.eth.getTransactionCount(self.address)
            ),
        } 

        transaction = function.buildTransaction(params)
        
        signed_txn = self.w3.eth.account.sign_transaction(
            transaction, private_key=self.private_key
        )
        
        try:
            return self.w3.eth.sendRawTransaction(signed_txn.rawTransaction)
        finally:
            logger.debug(f"nonce: {params['nonce']}")
            self.last_nonce = Nonce(params["nonce"] + 1)


    def _eth_to_token_swap_input(self,gwei, my_address, my_pk, output_token: AnyAddress, qty: Wei, recipient: Optional[AnyAddress]) -> HexBytes:
        """Convert base token (BSC for Binance Smart Chain | ETH for Ethereum) to tokens given an input amount.
        
        :param: gwei         - Amount of gas for trade/transaction (1 ETH = 10^9 gwei)
        :param: my_address   - User's wallet address
        :param: my_pk        - User's wallet private key
        :param: output_token - address of token received as result of swapped
        :param: qty          - Quantity of input_token to swap
        :param: recipient    - Wallet address of recipient of swap, if None defaults to my_address
        
        :returns:            -
        """

        # Validate my_address holds enough 
        eth_balance = self.get_eth_balance()
        if qty > eth_balance:
            raise InsufficientBalance(eth_balance, qty)

        if recipient is None:
            recipient = self.address
        
        amount_out_min = int( (1 - self.max_slippage) * self.get_eth_token_input_price(output_token, qty) )
        
        return self._build_and_send_tx(gwei, my_address, my_pk,
            self.router.functions.swapExactETHForTokens(
                amount_out_min,
                [self.get_weth_address(), output_token],
                recipient,
                self._deadline(),
            ),
            self._get_tx_params(value=qty, gwei=gwei,my_address=my_address),
        )


    def _token_to_eth_swap_input(self, gwei, my_address, my_pk, input_token: AnyAddress, qty: int, recipient: Optional[AnyAddress]) -> HexBytes:
        """
        Method that provides functionality to convert input_token to BNB given an input amount (qty).

        :param: gwei         - Amount of gas for trade/transaction (1 ETH = 10^9 gwei)
        :param: my_address   - User's wallet address
        :param: my_pk        - User's wallet private key
        :param: input_token  - Address of token user wishes to swap
        :param: qty          - Quantity of input_token to swap
        :param: recipient    - Wallet address of recipient of swap, if None defaults to my_address

        :returns: (HexBytes)
        """
        # Balance check
        input_balance = self.get_token_balance(input_token)
        if qty > input_balance:
            raise InsufficientBalance(input_balance, qty)

        if recipient is None:
            recipient = self.address
        amount_out_min = int( (1 - self.max_slippage) * self.get_token_eth_input_price(input_token, qty) )
        
        return self._build_and_send_tx(gwei, my_address,my_pk,
            self.router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
                qty,
                amount_out_min,
                [input_token, self.get_weth_address()],
                recipient,
                self._deadline(),
            )
        )


    def _token_to_token_swap_input(self, gwei, my_address, my_pk, input_token: AnyAddress,
        qty: int, output_token: AnyAddress, recipient: Optional[AnyAddress],) -> HexBytes:
        """
        Method that provides functionality to convert input_token 
        given output_token provided an input amount (qty).

        :param: gwei         - Amount of gas for trade/transaction (1 ETH = 10^9 gwei)
        :param: my_address   - User's wallet address
        :param: my_pk        - User's wallet private key
        :param: input_token  - Address of token user wishes to swap
        :param: qty          - Quantity of input_token to swap
        :param: output_token - Address of token user wishes to receive as a result of swap
        :param: recipient    - Wallet address of recipient of swap, if None defaults to my_address

        :returns: (HexBytes)
        """
        if recipient is None:
            recipient = self.address

        min_tokens_bought = int( (1 - self.max_slippage) * self.get_token_token_input_price(input_token, output_token, qty) )
        
        return self._build_and_send_tx(gwei, my_address,my_pk,
            self.router.functions.swapExactTokensForTokens(
                qty,
                min_tokens_bought,
                [input_token, self.get_weth_address(), output_token],
                recipient,
                self._deadline(),
            ),
        )


    def _build_and_send_tx(self, gwei, my_address, my_pk, function: ContractFunction, tx_params: Optional[TxParams] = None) -> HexBytes:
        """
        Method that leverages web3.contract function to build our desired transaction and send it to the network.
        
        :param: gwei         - Amount of gas for trade/transaction (1 ETH = 10^9 gwei)
        :param: my_address   - User's wallet address
        :param: my_pk        - User's wallet private key
        :param: function     - Instance of contract function as defined in Pancakeswap router
        :param: tx_params    - Defined transaction parameters in a dictionary

        :returns: (HexBytes)
        """
        if not tx_params:
            tx_params = self._get_tx_params(gwei,my_address)
        
        transaction = function.buildTransaction(tx_params)
        signed_txn = self.w3.eth.account.sign_transaction(
            transaction, private_key=my_pk
        )
        try:
            return self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        finally:
            logger.debug(f"nonce: {tx_params['nonce']}")
            self.last_nonce = Nonce(tx_params["nonce"] + 1)


    def _get_tx_params(self, gwei, my_address, value: Wei = Wei(0), gas: Wei = Wei(250000)) -> TxParams:
        """
        Method generates parameters for our transaction based on method's input parameters
        
        :param: gwei         -
        :param: my_address   -
        :param: value        -
        :param: gas          -
        """
        return {
            "from": my_address,
            "value": value,
            "gas": gas,
            "gasPrice":gwei,
            "nonce": max(
                self.last_nonce, self.w3.eth.get_transaction_count(self.address)
            ),
        }


    def _deadline(self) -> int:
        """
        Method returns deadline for transaction which is 10 minutes 
        ahead of current time in seconds.
        
        :returns: (int) 10 minutes ahead of current time in seconds
        """
        return int(time.time()) + 10 * 60


    def _is_approved(self, token: AnyAddress) -> bool:
        """Check to see if the exchange and token is approved."""
        utils.validate_address(token)
        contract_addr = self.router_address_v2
        
        amount = (
            utils.load_contract("erc20", token, self.w3)
            .functions.allowance(self.address, contract_addr)
            .call()
        )
        
        if amount >= self.max_approval_check_int:
            return True
        else:
            return False


    def get_eth_balance(self) -> Wei:
        """
        Method returns balance of ETH in client wallet in Wei
        
        :returns: (Wei) balance of ETH in wallet.
        """
        return self.w3.eth.get_balance(self.address)
    

    @functools.lru_cache()
    def get_weth_address(self) -> ChecksumAddress:
        """
        Method returns the contract address of WBNB
        """
        address = Web3.toChecksumAddress('0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c')
        
        return address


    def get_token_balance(self, token: AnyAddress) -> int:
        """Method gets the balance token in wallet

        :param: token    - Contract address of token

        :returns: (int) number of tokens
        """
        utils.validate_address(token)
        if utils.addr_to_str(token) == utils.ETH_ADDRESS:
            return self.get_eth_balance()
        
        erc20 = utils.load_contract("erc20", token, self.w3)
        balance: int = erc20.functions.balanceOf(self.address).call()
        
        return balance


    def get_eth_token_input_price(self, token: AnyAddress, qty: int) -> int:
        """
        Uses the Pancakeswap router function 'getAmountsOut' to retrieve the price
        for ETH to Token trades with an exact input.

        :param: token    - address of token to receive as result of swap
        :param: qty      - Quantity of ETH to swap

        :returns: (Wei)  -
        """
        price = self.router.functions.getAmountsOut(
            qty, 
            [self.get_weth_address(), token]
        ).call()[-1]
        
        return price


    def get_token_eth_input_price(self, token: AnyAddress, qty: int) -> int:
        """
        Uses the Pancakeswap router function 'getAmountsOut' to retrieve the price
        for Token to ETH trades with an exact input.

        :param: token    - address of token
        :param: qty      - Quantity of token to swap

        :returns: (int)  -
        """
        price = self.router.functions.getAmountsOut(
            qty, 
            [token, self.get_weth_address()]
        ).call()[-1]

        return price


    def get_token_token_input_price(self, token0: AnyAddress, token1: AnyAddress, qty: int) -> int:
        """
        Uses the Pancakeswap router function 'getAmountsOut' to retrieve the price
        for Token to Token trades with an exact input.

        :param: token0   - address of token to swap
        :param: token1   - address of token received as a result of swap
        :param: qty      - Quantity of token0 to swap

        :returns: (int)
        """
        print(f"Factory address: {self.factory_address_v2}")
        print(f"Router address: {self.router_address_v2}")
        
        if is_same_address(token0, self.get_weth_address()):
            return int(self.get_eth_token_input_price(token1, qty))
        elif is_same_address(token1, self.get_weth_address()):
            return int(self.get_token_eth_input_price(token0, qty))

        price: int = self.router.functions.getAmountsOut(
            qty, [token0, self.get_weth_address(), token1]
        ).call()[-1]

        return price


    @utils.check_approval
    def make_trade(self, input_token: AnyAddress, output_token: AnyAddress, qty: Union[int, Wei],
        gwei, my_address, my_pk, recipient: AnyAddress = None,) -> HexBytes:
        """Method is the entry point to validating and creating a trade order.

        :param: input_token  - address of input token (token to be swapped)
        :param: output_token - address of token received as result of swapped
        :param: qty          - Quantity of input_token to swap
        :param: gwei         - Amount of gas for trade/transaction (1 ETH = 10^9 gwei)
        :param: my_address   - User's wallet address
        :param: my_pk        - User's wallet private key
        :param: recipient    - Wallet address of recipient of swap, if None defaults to my_address

        :returns: TO-DO 
        """

        if input_token == utils.ETH_ADDRESS:
            # input_token is base network base token
            return self._eth_to_token_swap_input(gwei, my_address, my_pk, output_token, Wei(qty), recipient)
        else:
            # validate we have enough input_token balance to cover input 'qty' for swap
            balance = self.get_token_balance(input_token)
            if balance < qty:
                raise InsufficientBalance(balance, qty)
            
            if output_token == utils.ETH_ADDRESS:
                return self._token_to_eth_swap_input(gwei, my_address, my_pk, input_token, qty, recipient)
            else:
                return self._token_to_token_swap_input(gwei, my_address, my_pk, input_token, qty, output_token, recipient)


    def approve(self, token: AnyAddress, max_approval: Optional[int] = None) -> None:
        """Give an exchange/router max approval of a token."""
        max_approval = self.max_approval_int if not max_approval else max_approval
        
        contract_addr = (
            self.router_address_v2
        )

        function = utils.load_contract("erc20", token, self.w3).functions.approve(
            contract_addr, max_approval
        )

        logger.info(f"Approving {utils.addr_to_str(token)}...")
        
        tx = self._build_and_send_approval(function)
        self.w3.eth.wait_for_transaction_receipt(tx, timeout=6000)

        time.sleep(1)

    

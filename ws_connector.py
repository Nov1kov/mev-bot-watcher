import asyncio
import base64
import json
import logging
from collections import deque
from typing import Dict, Callable, Literal, Optional

import websockets.client


SubscriptionType = Literal[
    "newHeads",
    "logs",
    "newPendingTransactions",
    "syncing",
    "newBlockHeaders",
]


class WsConnectorRaw:
    OPEN_TIMEOUT = 20  # timeout for longest task such as load arbs.

    def __init__(self, node_url_ws: str, login: Optional[str] = None, password: Optional[str] = None,
                 name: Optional[str] = None):
        self.node_url_ws = node_url_ws
        self.login = login
        self.password = password
        self.name = name
        self.subscriptions: Dict[str, Callable] = {}
        self.subscription_setups = []
        self.ready = asyncio.Event()

    def _log_prefix(self) -> str:
        return f"[{self.name}] " if self.name else ""

    def _build_auth_headers(self) -> Optional[list]:
        if not self.login or not self.password:
            return None
        token = base64.b64encode(f"{self.login}:{self.password}".encode("utf-8")).decode("ascii")
        return [("Authorization", f"Basic {token}")]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def qsize(self):
        """ Will implemented later after run websocket """
        pass

    async def subscribe(self, event_handler: Callable, subscription_type: SubscriptionType, subscription_arg: Dict | bool = None):
        self.subscription_setups.append(
            (
                subscription_type,
                event_handler,
                subscription_arg,
            )
        )

    async def run(self):
        connect_kwargs = {
            "uri": self.node_url_ws,
            "open_timeout": self.OPEN_TIMEOUT,
            "ping_timeout": self.OPEN_TIMEOUT,
            "max_queue": None,
        }
        auth_headers = self._build_auth_headers()
        if auth_headers is not None:
            connect_kwargs["extra_headers"] = auth_headers
        logging.info(f"{self._log_prefix()}Connecting to {self.node_url_ws}")
        async for websocket in websockets.client.connect(**connect_kwargs):
            logging.info(f"{self._log_prefix()}WebSocket connected")
            def get_qsize():
                return len(websocket.messages)

            self.qsize = get_qsize
            self.subscriptions.clear()
            await self.__send_subscription_requests(websocket)
            queue_requests = deque()
            await self.__proceed_subscriptions(websocket, queue_requests)
            self.ready.set()
            try:
                while True:
                    if len(queue_requests) == 0:
                        message = await websocket.recv()
                        response = json.loads(message)
                    else:
                        response = queue_requests.popleft()
                    message_params = response["params"]
                    subscription_id = message_params['subscription']
                    handler = self.subscriptions[subscription_id]
                    try:
                        await handler(message_params)
                    except Exception as e:
                        logging.exception(f"{self._log_prefix()}Subscription {subscription_id} handler error: {e}")
            except websockets.ConnectionClosed:
                logging.exception(f"{self._log_prefix()}Web socket reconnection...")
                continue
            except StopAsyncIteration:
                logging.exception(f"{self._log_prefix()}Websocket connection stopped")
                break
            except Exception as e:
                logging.exception(f"{self._log_prefix()}Web socket connection error: {e}")
                continue

    async def __proceed_subscriptions(self, websocket, queue_requests: deque):
        while len(self.subscription_setups) > len(self.subscriptions):
            response = json.loads(await websocket.recv())
            if 'method' in response:
                queue_requests.append(response)
            else:
                index = response['id']
                subscription_type, event_handler, _ = self.subscription_setups[index]
                if 'error' in response:
                    logging.exception(f"{self._log_prefix()}Subscription {subscription_type} didn't successfully {response['error']}")
                    continue
                subscription_id = response["result"]
                self.subscriptions[subscription_id] = event_handler
                logging.info(f"{self._log_prefix()}[{subscription_type}] subscription active: {subscription_id}")

    async def __send_subscription_requests(self, websocket):
        for id, (subscription_type, _, subscription_arg) in enumerate(self.subscription_setups):
            params_reqeust = [subscription_type]
            if subscription_arg is not None:
                params_reqeust.append(subscription_arg)
            await websocket.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": id,
                        "method": "eth_subscribe",
                        "params": params_reqeust
                    }
                )
            )
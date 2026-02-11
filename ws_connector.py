import json
import logging
from collections import deque
from typing import Dict, Callable, Literal

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

    def __init__(self, node_url_ws: str):
        self.node_url_ws = node_url_ws
        self.subscriptions: Dict[str, Callable] = {}
        self.subscription_setups = []

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
        async for websocket in websockets.client.connect(
                uri=self.node_url_ws,
                ping_timeout=self.OPEN_TIMEOUT,
                max_queue=None,
        ):
            def get_qsize():
                return len(websocket.messages)

            self.qsize = get_qsize
            self.subscriptions.clear()
            await self.__send_subscription_requests(websocket)
            queue_requests = deque()
            await self.__proceed_subscriptions(websocket, queue_requests)
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
                    await handler(message_params)
            except websockets.ConnectionClosed:
                logging.exception(f"Web socket reconnection...")
                continue
            except StopAsyncIteration:
                logging.exception("Websocket connection stopped")
                break
            except Exception as e:
                logging.exception(f"Web socket connection error: {e}")
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
                    logging.exception(f"Subscription {subscription_type} didn't successfully {response['error']}")
                    continue
                subscription_id = response["result"]
                self.subscriptions[subscription_id] = event_handler
                logging.info(f"[{subscription_type}] subscription active: {subscription_id}")

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
import asyncio
import logging
from threading import Thread
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
import uvicorn
import aiohttp
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class WebRTCOffer(BaseModel):
    """Pydantic model for the WebRTC offer from the peer."""
    sdp: str
    type: str
    password: str

class SignalingServer:
    """
    A temporary, one-time-use FastAPI server that runs on the host's machine
    to accept a connection from a single peer and exchange WebRTC details.
    """
    def __init__(self, host_password: str, offer_queue: asyncio.Queue, answer_func):
        self.app = FastAPI()
        self.host_password = host_password
        self.offer_queue = offer_queue  # For passing the peer's offer to the host's WebRTC logic
        self.answer_func = answer_func  # A coroutine to get the host's answer
        self.server_thread = None
        self.uvicorn_server = None

        @self.app.post("/connect")
        async def connect(offer: WebRTCOffer):
            # 1. Validate password
            if offer.password != self.host_password:
                logging.warning("Signaling server received incorrect password.")
                raise HTTPException(status_code=403, detail="Incorrect password")
            
            logging.info("Signaling server received correct password and offer from peer.")
            
            # 2. Pass the peer's offer to the main WebRTC logic
            await self.offer_queue.put(offer.dict())
            
            # 3. Wait for the host's answer
            logging.info("Waiting for host's WebRTC answer...")
            answer = await self.answer_func()
            
            logging.info("Returning host's answer to peer.")
            return answer

    def start(self, host: str, port: int):
        """Starts the Uvicorn server in a separate thread."""
        if self.server_thread is not None and self.server_thread.is_alive():
            logging.warning("Signaling server is already running.")
            return

        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            config = uvicorn.Config(self.app, host=host, port=port, loop="asyncio")
            self.uvicorn_server = uvicorn.Server(config)
            loop.run_until_complete(self.uvicorn_server.serve())

        self.server_thread = Thread(target=run_server, daemon=True)
        self.server_thread.start()
        logging.info(f"Signaling server started on {host}:{port}")

    def stop(self):
        """Stops the Uvicorn server."""
        if self.uvicorn_server:
            # This is a bit of a hack to stop uvicorn from a different thread
            # In a real app, you might use more robust inter-thread communication
            self.uvicorn_server.should_exit = True
            logging.info("Signaling server shutting down.")
            # Give it a moment to close sockets
            self.server_thread.join(timeout=1)
            
class SignalingClient:
    """
    A client to connect to the host's temporary signaling server.
    """
    async def connect_and_exchange(self, host_ip: str, port: int, password: str, offer: dict) -> dict:
        """
        Sends the peer's offer to the host and returns the host's answer.
        """
        url = f"http://{host_ip}:{port}/connect"
        payload = {
            "sdp": offer["sdp"],
            "type": offer["type"],
            "password": password
        }
        
        logging.info(f"Signaling client sending offer to {url}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, timeout=15) as response:
                    response.raise_for_status()
                    answer = await response.json()
                    logging.info("Signaling client received answer from host.")
                    return answer
            except aiohttp.ClientError as e:
                logging.error(f"Signaling client connection error: {e}")
                raise ConnectionError(f"Could not connect to host at {url}. Check address and firewall.") from e
            except json.JSONDecodeError:
                logging.error("Failed to decode server response.")
                raise ValueError("Received invalid response from host.")
            except asyncio.TimeoutError:
                logging.error(f"Connection to {url} timed out.")
                raise ConnectionError(f"Connection to host timed out.")

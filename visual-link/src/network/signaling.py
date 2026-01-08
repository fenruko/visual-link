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

# --- Pydantic Models ---

class WebRTCSession(BaseModel):
    """A generic model for WebRTC session descriptions."""
    sdp: str
    type: str

class AnswerPayload(WebRTCSession):
    """Model for the peer's answer, including the password for validation."""
    password: str

# --- Signaling Server ---

class SignalingServer:
    """
    A temporary FastAPI server on the host's machine to facilitate the WebRTC handshake.
    It provides an endpoint to fetch the host's offer and another to receive the peer's answer.
    """
    def __init__(self, host_offer: dict, host_password: str, answer_queue: asyncio.Queue):
        self.app = FastAPI()
        self.host_offer = host_offer
        self.host_password = host_password
        self.answer_queue = answer_queue  # For passing the peer's answer to the host's logic
        self.server_thread = None
        self.uvicorn_server = None

        @self.app.get("/offer", response_model=WebRTCSession)
        async def get_offer():
            """Endpoint for the peer to fetch the host's initial offer."""
            logging.info("Signaling server: Peer requested offer.")
            return self.host_offer

        @self.app.post("/answer")
        async def receive_answer(payload: AnswerPayload):
            """Endpoint for the peer to submit its answer."""
            # 1. Validate password
            if payload.password != self.host_password:
                logging.warning("Signaling server received incorrect password on /answer.")
                raise HTTPException(status_code=403, detail="Incorrect password")
            
            logging.info("Signaling server received correct password and answer from peer.")
            
            # 2. Pass the peer's answer to the main WebRTC logic
            await self.answer_queue.put({"sdp": payload.sdp, "type": payload.type})
            
            return {"status": "Answer received, connection should be established shortly."}

    def start(self, host: str, port: int):
        """Starts the Uvicorn server in a separate thread."""
        if self.server_thread and self.server_thread.is_alive():
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
            self.uvicorn_server.should_exit = True
            logging.info("Signaling server shutting down.")
            self.server_thread.join(timeout=2)

# --- Signaling Client ---

class SignalingClient:
    """
    A client to interact with the host's temporary signaling server.
    """
    async def get_offer(self, host_ip: str, port: int) -> dict:
        """Fetches the host's WebRTC offer."""
        url = f"http://{host_ip}:{port}/offer"
        logging.info(f"Signaling client requesting offer from {url}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=10) as response:
                    response.raise_for_status()
                    offer = await response.json()
                    logging.info("Signaling client received offer from host.")
                    return offer
            except asyncio.TimeoutError:
                logging.error(f"Connection to {url} timed out.")
                raise ConnectionError("Connection to host timed out.")
            except aiohttp.ClientError as e:
                logging.error(f"Signaling client connection error: {e}")
                raise ConnectionError(f"Could not connect to host at {url}. Check address and firewall.")

    async def send_answer(self, host_ip: str, port: int, password: str, answer: dict):
        """Sends the peer's answer to the host."""
        url = f"http://{host_ip}:{port}/answer"
        payload = {
            "sdp": answer["sdp"],
            "type": answer["type"],
            "password": password
        }
        logging.info(f"Signaling client sending answer to {url}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, timeout=10) as response:
                    response.raise_for_status()
                    logging.info("Signaling client successfully sent answer.")
            except asyncio.TimeoutError:
                logging.error(f"Connection to {url} timed out while sending answer.")
                raise ConnectionError("Connection to host timed out.")
            except aiohttp.ClientError as e:
                logging.error(f"Signaling client connection error while sending answer: {e}")
                raise ConnectionError(f"Could not send answer to host at {url}.")
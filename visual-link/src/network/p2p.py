import asyncio
import logging
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class P2PConnection:
    """Manages a single WebRTC peer-to-peer connection."""
    
    def __init__(self, on_message_callback=None):
        self.pc = RTCPeerConnection()
        self.relay = MediaRelay()
        self.data_channel = None
        self.on_message_callback = on_message_callback

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            logging.info(f"Data channel '{channel.label}' created by remote.")
            self.data_channel = channel
            self._register_channel_callbacks()

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logging.info(f"Connection state is {self.pc.connectionState}")
            if self.pc.connectionState == "failed":
                await self.close()

    def _register_channel_callbacks(self):
        """Registers the on-message callback for the data channel."""
        if not self.data_channel:
            return

        @self.data_channel.on("message")
        def on_message(message):
            if self.on_message_callback:
                self.on_message_callback(message)
            else:
                logging.info(f"Received message: {message}")

    async def create_offer(self) -> dict:
        """Creates an SDP offer to initiate a connection."""
        logging.info("Creating data channel 'main'.")
        self.data_channel = self.pc.createDataChannel("main")
        self._register_channel_callbacks()

        logging.info("Creating WebRTC offer.")
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        
        return {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}

    async def set_offer_and_create_answer(self, offer_data: dict) -> dict:
        """Receives an offer, sets it, and creates an answer."""
        offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
        
        logging.info("Received offer, setting remote description.")
        await self.pc.setRemoteDescription(offer)
        
        logging.info("Creating answer.")
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        
        return {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}

    async def set_answer(self, answer_data: dict):
        """Receives an answer and sets it to establish the connection."""
        answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
        
        logging.info("Received answer, setting remote description.")
        await self.pc.setRemoteDescription(answer)

    def send(self, message: str):
        """Sends a message over the data channel."""
        if self.data_channel and self.data_channel.readyState == "open":
            self.data_channel.send(message)
        else:
            logging.warning("Cannot send message: Data channel is not open.")

    async def close(self):
        """Closes the peer connection."""
        if self.pc.connectionState != "closed":
            logging.info("Closing P2P connection.")
            await self.pc.close()

if __name__ == '__main__':
    # This is a dummy example of how the two P2P objects would interact.
    # In the real app, this is orchestrated by the GUI and signaling modules.
    
    async def run_test():
        # Peer A (the host)
        peer_a = P2PConnection()

        # Peer B (the joiner)
        peer_b = P2PConnection()

        # 1. Peer B creates an offer
        offer = await peer_b.create_offer()
        
        # 2. Peer A receives the offer and creates an answer
        answer = await peer_a.set_offer_and_create_answer(offer)
        
        # 3. Peer B receives the answer
        await peer_b.set_answer(answer)
        
        # Now they wait for the connection to establish...
        # In a real app we'd use pc.on('connectionstatechange') to know when it's 'connected'
        await asyncio.sleep(2)

        print("--- Connection should be established ---")

        # Peer B sends a message
        print("Peer B sending 'Hello from B'")
        peer_b.send("Hello from B")
        
        await asyncio.sleep(1)

        # Peer A sends a message
        print("Peer A sending 'Hello from A'")
        peer_a.send("Hello from A")
        
        await asyncio.sleep(1)
        
        await peer_a.close()
        await peer_b.close()

    logging.getLogger("aiortc").setLevel(logging.WARNING)
    logging.getLogger("aioice").setLevel(logging.WARNING)

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run_test())
    finally:
        loop.close()

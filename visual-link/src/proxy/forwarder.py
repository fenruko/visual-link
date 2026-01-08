import asyncio
import logging
from typing import Optional, Callable

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# A simple wrapper to distinguish proxy data from chat messages
PROXY_DATA_PREFIX = "p2p_proxy_data:"
PROXY_CONN_OPEN = "p2p_proxy_conn_open"
PROXY_CONN_CLOSE = "p2p_proxy_conn_close"

# New prefixes for simplified proxy setup
PROXY_SETUP_HOST = "proxy_setup_host"  # Peer is the game host, we should listen
PROXY_SETUP_JOIN = "proxy_setup_join"  # Peer is joining, they will listen


class TrafficForwarder:
    """
    Manages the forwarding of TCP traffic from a local port over a WebRTC data channel.
    """
    def __init__(self, p2p_send_func: Callable[[str], None]):
        self.p2p_send_func = p2p_send_func
        self.tcp_server = None
        self.tcp_writer: Optional[asyncio.StreamWriter] = None

    async def start_local_server(self, listen_port: int, target_host: str, target_port: int):
        """
        Starts a local TCP server that listens for a game connection.
        When a connection is made, it informs the peer to connect to the target.
        """
        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            self.tcp_writer = writer
            peer_address = writer.get_extra_info('peername')
            logging.info(f"Local game connected from {peer_address}")
            
            # Inform the peer that a local connection has been made
            # and that it should establish a connection to the target game server.
            open_msg = f"{PROXY_CONN_OPEN}|{target_host}|{target_port}"
            self.p2p_send_func(open_msg)

            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    # Wrap data and send over WebRTC
                    self.p2p_send_func(f"{PROXY_DATA_PREFIX}{data.hex()}")
                
            except asyncio.CancelledError:
                logging.info("TCP client handler cancelled.")
            except Exception as e:
                logging.error(f"Error in TCP client handler: {e}")
            finally:
                logging.info("Local game disconnected.")
                self.p2p_send_func(PROXY_CONN_CLOSE)
                self.tcp_writer = None
                writer.close()

        try:
            self.tcp_server = await asyncio.start_server(handle_client, '127.0.0.1', listen_port)
            logging.info(f"Local proxy server started on 127.0.0.1:{listen_port}")
            return True
        except Exception as e:
            logging.error(f"Failed to start local proxy server: {e}")
            return False

    async def connect_to_target(self, host: str, port: int):
        """Connects to the target game server on the peer's machine."""
        try:
            reader, writer = await asyncio.open_connection(host, port)
            self.tcp_writer = writer
            logging.info(f"Successfully connected to target game server at {host}:{port}")

            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    # Wrap data and send over WebRTC
                    self.p2p_send_func(f"{PROXY_DATA_PREFIX}{data.hex()}")
            except asyncio.CancelledError:
                logging.info("Target connection handler cancelled.")
            except Exception as e:
                logging.error(f"Error in target connection handler: {e}")
            finally:
                logging.info("Connection to target game server closed.")
                self.p2p_send_func(PROXY_CONN_CLOSE)
                self.tcp_writer = None
                writer.close()
        except Exception as e:
            logging.error(f"Failed to connect to target game server {host}:{port}: {e}")
            # Inform the initiating peer that the connection failed
            self.p2p_send_func(PROXY_CONN_CLOSE)

    def handle_p2p_proxy_message(self, message: str):
        """
        Parses a message from the WebRTC data channel and forwards it to the local TCP socket.
        """
        if self.tcp_writer and not self.tcp_writer.is_closing():
            try:
                data_hex = message[len(PROXY_DATA_PREFIX):]
                self.tcp_writer.write(bytes.fromhex(data_hex))
            except Exception as e:
                logging.error(f"Error writing to TCP socket: {e}")

    async def stop(self):
        """Stops the local TCP server and closes any active connections."""
        if self.tcp_server:
            self.tcp_server.close()
            await self.tcp_server.wait_closed()
            logging.info("Local proxy server stopped.")
        if self.tcp_writer:
            self.tcp_writer.close()
            await self.tcp_writer.wait_closed()
            logging.info("TCP writer closed.")
        self.tcp_server = None
        self.tcp_writer = None

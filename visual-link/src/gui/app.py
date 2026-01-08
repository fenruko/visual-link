import asyncio
import json
import logging
import os
import threading
import time

import customtkinter as ctk
from PIL import Image
from pystray import Icon, MenuItem

from src.network.discovery import UPnPHandler, get_public_ip
from src.network.p2p import P2PConnection
from src.network.signaling import SignalingServer, SignalingClient
from src.proxy.autodetect import get_windows_proxy
from src.proxy.forwarder import TrafficForwarder, PROXY_DATA_PREFIX, PROXY_CONN_OPEN, PROXY_CONN_CLOSE, PROXY_SETUP_HOST, PROXY_SETUP_JOIN

# --- Constants ---
SIGNALING_PORT = 28571

from pystray import MenuItem, Icon
from PIL import Image

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.p2p_connection: P2PConnection | None = None
        self.signaling_server: SignalingServer | None = None
        self.traffic_forwarder: TrafficForwarder | None = None
        self.async_loop = None
        self.async_thread = None
        self.host_password = None
        self.last_pong_received = None
        self.proxy_settings = {}
        self.tray_icon = None
        self.tray_thread = None
        
        self.answer_queue = asyncio.Queue()

        # ---- App Setup ----
        self.title("Visual Link")
        self.geometry("700x600")
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        self.upnp_handler = UPnPHandler()
        self.is_hosting = False
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.start_asyncio_loop()
        self.setup_tray_icon()

        # ---- UI Creation ----
        self.top_frame = ctk.CTkFrame(self, height=50)
        self.top_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.top_frame.grid_columnconfigure(0, weight=1)
        
        self.app_title = ctk.CTkLabel(self.top_frame, text="Visual Link", font=ctk.CTkFont(size=20, weight="bold"))
        self.app_title.grid(row=0, column=0, padx=20, pady=10, sticky="w")

        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")
        self.tab_view.add("Host Network")
        self.tab_view.add("Join Network")
        self.tab_view.add("Proxy")
        self.tab_view.add("Chat")
        self.tab_view.set("Host Network")

        self._configure_host_tab()
        self._configure_join_tab()
        self._configure_proxy_tab()
        self._configure_chat_tab()
        
        self.status_bar = ctk.CTkLabel(self, text="Ready", anchor="w", font=ctk.CTkFont(size=12))
        self.status_bar.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="ew")

    def setup_tray_icon(self):
        """Sets up the system tray icon."""
        image = Image.open("src/assets/icon.png")
        menu = (MenuItem('Show', self.show_window, default=True),
                MenuItem('Quit', self.quit_app))
        self.tray_icon = Icon("Visual Link", image, "Visual Link", menu)
        
        def run_tray():
            self.tray_icon.run()

        self.tray_thread = threading.Thread(target=run_tray, daemon=True)
        self.tray_thread.start()

    def show_window(self):
        """Shows the main application window."""
        self.deiconify()

    def on_closing(self):
        """Hides the window when the close button is pressed."""
        self.withdraw()

    def quit_app(self):
        """Properly closes the application."""
        logging.info("Application closing...")
        if self.tray_icon:
            self.tray_icon.stop()
        self.run_async(self.cleanup_hosting_resources())
        if self.async_loop:
            self.async_loop.call_soon_threadsafe(self.async_loop.stop)
            self.async_thread.join(timeout=2)
        self.destroy()


    # ---- UI Configuration ----
    def _configure_host_tab(self):
        host_tab = self.tab_view.tab("Host Network")
        host_tab.grid_columnconfigure(0, weight=1)
        host_tab.grid_rowconfigure(1, weight=1)
        controls_frame = ctk.CTkFrame(host_tab)
        controls_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        controls_frame.grid_columnconfigure(1, weight=1)
        self.host_password_label = ctk.CTkLabel(controls_frame, text="Connection Password:")
        self.host_password_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.host_password_entry = ctk.CTkEntry(controls_frame, placeholder_text="Enter a strong password")
        self.host_password_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.generate_invite_button = ctk.CTkButton(controls_frame, text="Start Hosting", command=self.start_hosting_flow)
        self.generate_invite_button.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        invite_frame = ctk.CTkFrame(host_tab)
        invite_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        invite_frame.grid_columnconfigure(0, weight=1)
        invite_frame.grid_rowconfigure(1, weight=1)
        invite_label = ctk.CTkLabel(invite_frame, text="Share this Invite Code with a friend:")
        invite_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.invite_code_box = ctk.CTkTextbox(invite_frame, wrap="word", height=100, state="disabled")
        self.invite_code_box.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

    def _configure_join_tab(self):
        join_tab = self.tab_view.tab("Join Network")
        join_tab.grid_columnconfigure(0, weight=1)
        join_tab.grid_rowconfigure(0, weight=1)
        join_frame = ctk.CTkFrame(join_tab, fg_color="transparent")
        join_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        join_frame.grid_columnconfigure(0, weight=1)
        self.join_code_label = ctk.CTkLabel(join_frame, text="Paste Invite Code from Host:")
        self.join_code_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.join_code_box = ctk.CTkTextbox(join_frame, wrap="word", height=120)
        self.join_code_box.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.join_password_label = ctk.CTkLabel(join_frame, text="Connection Password:")
        self.join_password_label.grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.join_password_entry = ctk.CTkEntry(join_frame, placeholder_text="Enter password from host", show="*")
        self.join_password_entry.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.connect_button = ctk.CTkButton(join_frame, text="Connect to Host", command=self.start_joining_flow)
        self.connect_button.grid(row=4, column=0, padx=10, pady=10, sticky="ew")

    def _configure_proxy_tab(self):
        proxy_tab = self.tab_view.tab("Proxy")
        proxy_tab.grid_columnconfigure(0, weight=1)
        proxy_tab.grid_rowconfigure(3, weight=1)

        # --- Auto-detection Frame ---
        autodetect_frame = ctk.CTkFrame(proxy_tab)
        autodetect_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        autodetect_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(autodetect_frame, text="System Proxy Settings:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(10,5), sticky="w")
        
        self.detect_proxy_button = ctk.CTkButton(autodetect_frame, text="Detect System Proxy", command=self._detect_proxy_settings)
        self.detect_proxy_button.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        
        self.autodetect_status_label = ctk.CTkLabel(autodetect_frame, text="Status: Ready to detect.")
        self.autodetect_status_label.grid(row=1, column=1, padx=10, pady=10, sticky="w")

        # --- Manual Configuration Frame ---
        manual_frame = ctk.CTkFrame(proxy_tab)
        manual_frame.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        manual_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(manual_frame, text="Manual Proxy Configuration:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, padx=10, pady=(10,5), sticky="w")

        ctk.CTkLabel(manual_frame, text="HTTP Proxy:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.manual_http_proxy_entry = ctk.CTkEntry(manual_frame, placeholder_text="e.g., http://user:pass@host:port")
        self.manual_http_proxy_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkLabel(manual_frame, text="HTTPS Proxy:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.manual_https_proxy_entry = ctk.CTkEntry(manual_frame, placeholder_text="e.g., http://user:pass@host:port")
        self.manual_https_proxy_entry.grid(row=2, column=1, padx=10, pady=5, sticky="ew")
        
        self.apply_manual_proxy_button = ctk.CTkButton(manual_frame, text="Apply Manual Proxy", command=self._apply_manual_proxy)
        self.apply_manual_proxy_button.grid(row=3, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        # --- Game Proxy Section (existing code) ---
        game_proxy_frame = ctk.CTkFrame(proxy_tab)
        game_proxy_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        game_proxy_frame.grid_columnconfigure(1, weight=1)
        
        info_label = ctk.CTkLabel(game_proxy_frame, 
                                  text="Once connected to a peer, choose your role in the game and set the game's port.\n"
                                       "This will automatically configure the proxy for both players.",
                                  wraplength=400, justify="left")
        info_label.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        ctk.CTkLabel(game_proxy_frame, text="Game's LAN Port:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.game_port_entry = ctk.CTkEntry(game_proxy_frame, placeholder_text="e.g., 7777 or 25565")
        self.game_port_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

        button_frame = ctk.CTkFrame(game_proxy_frame, fg_color="transparent")
        button_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        button_frame.grid_columnconfigure((0, 1), weight=1)

        self.host_game_button = ctk.CTkButton(button_frame, text="I am HOSTING the game", command=self._start_proxy_as_host)
        self.host_game_button.grid(row=0, column=0, padx=5, pady=10, sticky="ew")

        self.join_game_button = ctk.CTkButton(button_frame, text="I am JOINING the game", command=self._start_proxy_as_joiner)
        self.join_game_button.grid(row=0, column=1, padx=5, pady=10, sticky="ew")
        
        self.proxy_stop_button = ctk.CTkButton(game_proxy_frame, text="Stop Proxy", command=self.stop_proxy, state="disabled")
        self.proxy_stop_button.grid(row=3, column=0, columnspan=2, padx=10, pady=20, sticky="ew")

    def _detect_proxy_settings(self):
        self.autodetect_status_label.configure(text="Detecting...")
        proxy_settings = get_windows_proxy()
        if proxy_settings:
            self.proxy_settings = proxy_settings
            self.autodetect_status_label.configure(text=f"Detected: HTTP={proxy_settings.get('http')} | HTTPS={proxy_settings.get('https')}")
            # Also populate manual fields for easy editing
            self.manual_http_proxy_entry.delete(0, "end")
            self.manual_http_proxy_entry.insert(0, proxy_settings.get('http', ''))
            self.manual_https_proxy_entry.delete(0, "end")
            self.manual_https_proxy_entry.insert(0, proxy_settings.get('https', ''))
            self._apply_proxy_to_environment()
        else:
            self.autodetect_status_label.configure(text="No system proxy detected or proxy is disabled.")

    def _apply_manual_proxy(self):
        http_proxy = self.manual_http_proxy_entry.get()
        https_proxy = self.manual_https_proxy_entry.get()
        
        self.proxy_settings = {}
        if http_proxy:
            self.proxy_settings['http'] = http_proxy
        if https_proxy:
            self.proxy_settings['https'] = https_proxy
        
        self._apply_proxy_to_environment()
        self.update_status("Manual proxy settings applied.")

    def _apply_proxy_to_environment(self):
        """Sets the detected/manual proxy settings as environment variables."""
        if not self.proxy_settings:
            return
            
        logging.info(f"Applying proxy settings: {self.proxy_settings}")
        
        # Set environment variables for the current process
        if 'http' in self.proxy_settings:
            os.environ['HTTP_PROXY'] = self.proxy_settings['http']
        if 'https' in self.proxy_settings:
            os.environ['HTTPS_PROXY'] = self.proxy_settings['https']
        if 'no_proxy' in self.proxy_settings:
            os.environ['NO_PROXY'] = self.proxy_settings['no_proxy']
        
        self.update_status(f"Proxy applied: HTTP={self.proxy_settings.get('http','N/A')}")


    def _configure_chat_tab(self):
        chat_tab = self.tab_view.tab("Chat")
        chat_tab.grid_columnconfigure(0, weight=1)
        chat_tab.grid_rowconfigure(0, weight=1)
        self.chat_box = ctk.CTkTextbox(chat_tab, wrap="word", state="disabled")
        self.chat_box.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        chat_input_frame = ctk.CTkFrame(chat_tab)
        chat_input_frame.grid(row=1, column=0, padx=10, pady=(0,10), sticky="ew")
        chat_input_frame.grid_columnconfigure(0, weight=1)
        self.chat_entry = ctk.CTkEntry(chat_input_frame, placeholder_text="Type a message...")
        self.chat_entry.grid(row=0, column=0, padx=(0,10), pady=10, sticky="ew")
        self.chat_entry.bind("<Return>", self.send_chat_message)
        self.send_button = ctk.CTkButton(chat_input_frame, text="Send", command=self.send_chat_message)
        self.send_button.grid(row=0, column=1, padx=0, pady=10, sticky="e")

    # ---- Core Logic ----
    def update_status(self, message):
        logging.info(f"UI Status: {message}")
        self.status_bar.configure(text=message)

    def append_chat_message(self, sender: str, message: str):
        self.chat_box.configure(state="normal")
        self.chat_box.insert("end", f"[{sender}] {message}\n")
        self.chat_box.configure(state="disabled")
        self.chat_box.see("end")

    def handle_p2p_message(self, message):
        """
        Main router for incoming WebRTC data.
        It checks if the message is for the proxy or for the chat.
        """
        if message.startswith(PROXY_DATA_PREFIX):
            if self.traffic_forwarder:
                self.traffic_forwarder.handle_p2p_proxy_message(message)
        
        elif message.startswith(PROXY_SETUP_HOST):
            # The peer told us they are hosting the game. We need to set up a listener.
            try:
                _, port_str = message.split('|')
                port = int(port_str)
                self.run_async(self._setup_proxy_as_joiner_peer(port))
            except Exception as e:
                self.update_status(f"Error starting proxy for host: {e}")

        elif message.startswith(PROXY_SETUP_JOIN):
            # The peer told us they are joining. We need to connect to our local game server.
            try:
                _, port_str = message.split('|')
                port = int(port_str)
                self.run_async(self._setup_proxy_as_host_peer(port))
            except Exception as e:
                self.update_status(f"Error starting proxy for joiner: {e}")

        elif message.startswith(PROXY_CONN_OPEN):
            parts = message.split('|')
            if len(parts) == 3:
                _, host, port = parts
                self.after(0, self.update_status, f"Peer's game client connected. Connecting to your local server at {host}:{port}...")
                self.run_async(self.traffic_forwarder.connect_to_target(host, int(port)))
        
        elif message == PROXY_CONN_CLOSE:
            self.after(0, self.update_status, "Peer's game connection closed. Stopping proxy.")
            self.run_async(self.stop_proxy())
        
        else:
            self.after(0, self.append_chat_message, "Peer", message)

    def start_asyncio_loop(self):
        def run_loop():
            logging.info("Asyncio event loop started.")
            asyncio.set_event_loop(self.async_loop)
            self.async_loop.run_forever()
        self.async_loop = asyncio.new_event_loop()
        self.async_thread = threading.Thread(target=run_loop, daemon=True)
        self.async_thread.start()

    def run_async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.async_loop)

    # ---- Host/Join Flows ----
    def start_hosting_flow(self):
        self.host_password = self.host_password_entry.get()
        if not self.host_password:
            self.update_status("Error: Please enter a password before starting.")
            return
        self.generate_invite_button.configure(state="disabled", text="Setting Up...")
        self.update_status("Starting host setup...")
        self.run_async(self.setup_host())

    async def setup_host(self):
        try:
            self.after(0, self.update_status, "Initializing P2P connection...")
            self.p2p_connection = P2PConnection(on_message_callback=self.handle_p2p_message)
            
            offer = await self.p2p_connection.create_offer()
            
            self.after(0, self.update_status, "Discovering public IP...")
            public_ip = await self.async_loop.run_in_executor(None, get_public_ip)
            if not public_ip:
                raise ConnectionError("Could not determine public IP.")

            self.after(0, self.update_status, "Starting signaling server...")
            self.signaling_server = SignalingServer(
                host_offer=offer,
                host_password=self.host_password,
                answer_queue=self.answer_queue
            )
            self.signaling_server.start(host="0.0.0.0", port=SIGNALING_PORT)
            
            self.after(0, self.update_status, "Attempting UPnP port mapping...")
            if self.upnp_handler.discover():
                if not self.upnp_handler.add_port_mapping(SIGNALING_PORT, SIGNALING_PORT):
                    self.after(0, self.update_status, f"Warning: UPnP map for {SIGNALING_PORT} failed. Manual forwarding may be needed.")
            else:
                 self.after(0, self.update_status, "Warning: No UPnP router found. Manual forwarding may be needed.")

            invite_data = {"host_ip": public_ip, "port": SIGNALING_PORT}
            invite_code = json.dumps(invite_data)
            self.after(0, self.display_invite_code, invite_code)
            self.is_hosting = True
            
            self.after(0, self.update_status, "Waiting for a peer to connect...")
            
            # This will block until a peer sends its answer
            await self.wait_for_peer_answer()

        except Exception as e:
            logging.error(f"Hosting setup failed: {e}")
            self.after(0, self.update_status, f"Error: {e}")
            await self.cleanup_hosting_resources()

    async def wait_for_peer_answer(self):
        """Waits for the peer's answer from the queue and completes the connection."""
        peer_answer = await self.answer_queue.get()
        self.after(0, self.update_status, "Peer answer received, establishing connection...")
        
        await self.p2p_connection.set_answer(peer_answer)
        
        self.after(0, self.update_status, "Peer connected! Configure and start the proxy to play.")
        self.after(0, self.tab_view.set, "Proxy")
        
        # Clean up signaling server as it's no longer needed
        if self.signaling_server:
            self.signaling_server.stop()
            self.signaling_server = None

    def display_invite_code(self, code):
        self.invite_code_box.configure(state="normal")
        self.invite_code_box.delete("1.0", "end")
        self.invite_code_box.insert("1.0", code)
        self.invite_code_box.configure(state="disabled")
        self.generate_invite_button.configure(text="Stop Hosting", command=self.stop_hosting_flow, state="normal")

    def stop_hosting_flow(self):
        self.update_status("Stopping host...")
        self.run_async(self.cleanup_hosting_resources())

    async def cleanup_hosting_resources(self):
        await self.stop_proxy()
        if self.p2p_connection:
            await self.p2p_connection.close()
            self.p2p_connection = None
        if self.signaling_server:
            self.signaling_server.stop()
            self.signaling_server = None
        if self.upnp_handler.device:
            await self.async_loop.run_in_executor(None, self.upnp_handler.remove_port_mapping, SIGNALING_PORT)
        self.after(0, self.reset_host_ui)
    
    def reset_host_ui(self):
        self.invite_code_box.configure(state="normal")
        self.invite_code_box.delete("1.0", "end")
        self.invite_code_box.configure(state="disabled")
        self.generate_invite_button.configure(command=self.start_hosting_flow, state="normal", text="Start Hosting")
        self.update_status("Ready")
        self.is_hosting = False
        
    def start_joining_flow(self):
        invite_code = self.join_code_box.get("1.0", "end-1c")
        password = self.join_password_entry.get()
        if not invite_code or not password:
            self.update_status("Error: Please provide both an invite code and a password.")
            return
        try:
            invite_data = json.loads(invite_code)
        except (json.JSONDecodeError, AttributeError):
            self.update_status("Error: Invalid invite code format.")
            return
        self.connect_button.configure(state="disabled", text="Connecting...")
        self.run_async(self.join_host(invite_data, password))

    async def join_host(self, invite_data: dict, password: str):
        try:
            client = SignalingClient()
            
            # --- Hairpinning/Loopback Correction ---
            own_public_ip = await self.async_loop.run_in_executor(None, get_public_ip)
            host_ip_to_use = invite_data['host_ip']
            if own_public_ip == host_ip_to_use:
                logging.info("Host IP is our own public IP. Using '127.0.0.1' for loopback connection.")
                host_ip_to_use = "127.0.0.1"
            
            self.after(0, self.update_status, f"Fetching offer from {host_ip_to_use}...")
            host_offer = await client.get_offer(host_ip=host_ip_to_use, port=invite_data["port"])
            
            self.after(0, self.update_status, "Initializing P2P connection...")
            self.p2p_connection = P2PConnection(on_message_callback=self.handle_p2p_message)
            
            self.after(0, self.update_status, "Received offer, creating answer...")
            answer = await self.p2p_connection.set_offer_and_create_answer(host_offer)
            
            self.after(0, self.update_status, f"Sending answer to {host_ip_to_use}...")
            await client.send_answer(
                host_ip=host_ip_to_use,
                port=invite_data["port"],
                password=password,
                answer=answer
            )
            
            self.after(0, self.update_status, "Peer connected! Configure and start the proxy to play.")
            self.after(0, self.connect_button.configure, {"state": "normal", "text": "Connect to Host"})
            self.after(0, self.tab_view.set, "Proxy")
            
        except Exception as e:
            logging.error(f"Joining failed: {e}")
            self.after(0, self.update_status, f"Error: {e}")
            self.after(0, self.connect_button.configure, {"state": "normal", "text": "Connect to Host"})
            if self.p2p_connection:
                await self.p2p_connection.close()

    # ---- PROXY LOGIC ----
    def _get_game_port(self) -> int | None:
        """Safely gets and validates the game port from the UI."""
        try:
            port = int(self.game_port_entry.get())
            if 1 <= port <= 65535:
                return port
            self.update_status("Error: Port must be between 1 and 65535.")
            return None
        except (ValueError, TypeError):
            self.update_status("Error: Invalid game port. Please enter a number.")
            return None

    def _start_proxy_as_host(self):
        """User is hosting the game server. We tell the peer to listen."""
        if not self.p2p_connection or self.p2p_connection.pc.connectionState != 'connected':
            self.update_status("Error: Must be connected to a peer to start proxy.")
            return
        
        port = self._get_game_port()
        if not port:
            return

        # Tell the peer to start a listening server on their end on the game port
        self.p2p_connection.send(f"{PROXY_SETUP_JOIN}|{port}")
        self.run_async(self._setup_proxy_as_host_peer(port))

    def _start_proxy_as_joiner(self):
        """User is joining a game server. We will listen for their local game client."""
        if not self.p2p_connection or self.p2p_connection.pc.connectionState != 'connected':
            self.update_status("Error: Must be connected to a peer to start proxy.")
            return

        port = self._get_game_port()
        if not port:
            return
            
        # Tell the peer that we are going to be the one listening
        self.p2p_connection.send(f"{PROXY_SETUP_HOST}|{port}")
        self.run_async(self._setup_proxy_as_joiner_peer(port))

    async def _setup_proxy_as_host_peer(self, game_port: int):
        """
        This is run on the game host's side.
        It waits for a P2P message from the joiner's proxy, then connects to the local game server.
        """
        self.update_status("Proxy active: Waiting for joiner's game to connect...")
        self.traffic_forwarder = TrafficForwarder(p2p_send_func=self.p2p_connection.send)
        # We don't start a server, we wait for the PROXY_CONN_OPEN message
        self.after(0, self._set_proxy_ui_state, True)

    async def _setup_proxy_as_joiner_peer(self, game_port: int):
        """
        This is run on the game joiner's side.
        It starts a local TCP server to listen for the joiner's actual game client.
        """
        self.update_status(f"Proxy active: Connect your game to 127.0.0.1:{game_port}")
        self.traffic_forwarder = TrafficForwarder(p2p_send_func=self.p2p_connection.send)
        
        # The target host is the peer's machine, which for them is 127.0.0.1
        await self.traffic_forwarder.start_local_server(
            listen_port=game_port,
            target_host="127.0.0.1",
            target_port=game_port
        )
        self.after(0, self._set_proxy_ui_state, True)

    def _set_proxy_ui_state(self, is_running: bool):
        """Enables or disables the proxy UI elements."""
        if is_running:
            self.host_game_button.configure(state="disabled")
            self.join_game_button.configure(state="disabled")
            self.game_port_entry.configure(state="disabled")
            self.proxy_stop_button.configure(state="normal")
        else:
            self.host_game_button.configure(state="normal")
            self.join_game_button.configure(state="normal")
            self.game_port_entry.configure(state="normal")
            self.proxy_stop_button.configure(state="disabled")
            self.update_status("Proxy stopped.")

    async def stop_proxy(self):
        if self.traffic_forwarder:
            self.update_status("Stopping traffic forwarder...")
            await self.traffic_forwarder.stop()
            self.traffic_forwarder = None
            self.after(0, self._set_proxy_ui_state, False)
            
    # ---- CHAT LOGIC ----
    def send_chat_message(self, event=None):
        message = self.chat_entry.get()
        if message and self.p2p_connection:
            self.run_async(self.async_send_chat(message))
            self.append_chat_message("Me", message)
            self.chat_entry.delete(0, "end")

    async def async_send_chat(self, message):
        self.p2p_connection.send(message)

    # ---- APP CLEANUP ----
    def on_closing(self):
        """Hides the window when the close button is pressed."""
        self.withdraw()

    def quit_app(self):
        """Properly closes the application."""
        logging.info("Application closing...")
        if self.tray_icon:
            self.tray_icon.stop()
        self.run_async(self.cleanup_hosting_resources())
        if self.async_loop:
            self.async_loop.call_soon_threadsafe(self.async_loop.stop)
            self.async_thread.join(timeout=2)
        self.destroy()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s')
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    app = App()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app.quit_app()
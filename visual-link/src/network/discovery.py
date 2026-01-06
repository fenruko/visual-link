import socket
import requests
import upnpy
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_local_ip():
    """Finds the local IP address of the machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    logging.info(f"Discovered local IP: {IP}")
    return IP

def get_public_ip():
    """Fetches the public IP address from an external service."""
    try:
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        response.raise_for_status()
        ip = response.json()['ip']
        logging.info(f"Discovered public IP: {ip}")
        return ip
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get public IP: {e}")
        return None

class UPnPHandler:
    """A class to manage UPnP discovery and port mapping."""
    def __init__(self):
        self.upnp = upnpy.UPnP()
        self.device = None

    def discover(self):
        """Discovers UPnP-enabled devices on the network."""
        logging.info("Starting UPnP discovery...")
        try:
            self.device = self.upnp.discover(delay=2)
            if self.device:
                logging.info(f"UPnP device found: {self.device.friendly_name}")
                return True
            else:
                logging.warning("No UPnP devices found on the network.")
                return False
        except Exception as e:
            logging.error(f"UPnP discovery failed: {e}")
            self.device = None
            return False

    def add_port_mapping(self, external_port, internal_port, protocol='TCP'):
        """
        Creates a new port mapping on the UPnP device.
        Returns True on success, False on failure.
        """
        if not self.device:
            logging.error("Cannot add port mapping: No UPnP device available.")
            return False

        service = self.device['WANIPConnection.1'] or self.device['WANCommonInterfaceConfig.1']
        if not service:
            logging.error("Could not find WANIPConnection or WANCommonInterfaceConfig service.")
            return False
            
        local_ip = get_local_ip()
        
        try:
            # Check if mapping already exists
            existing_mapping = service.GetSpecificPortMappingEntry(NewRemoteHost='', NewExternalPort=external_port, NewProtocol=protocol)
            if existing_mapping and existing_mapping['NewInternalClient'] == local_ip:
                logging.info(f"Port mapping for {external_port}->{internal_port} already exists.")
                return True

            # If it exists for another client, we can't map it.
            elif existing_mapping:
                 logging.warning(f"Port {external_port} is already mapped to a different client ({existing_mapping['NewInternalClient']}).")
                 return False

        except Exception:
            # GetSpecificPortMappingEntry often fails if it doesn't exist, so we just continue.
            pass

        try:
            logging.info(f"Attempting to map external port {external_port} to internal port {internal_port} for {local_ip}...")
            service.AddPortMapping(
                NewRemoteHost='',
                NewExternalPort=external_port,
                NewProtocol=protocol,
                NewInternalPort=internal_port,
                NewInternalClient=local_ip,
                NewEnabled=1,
                NewPortMappingDescription='Visual Link Connection',
                NewLeaseDuration=0  # 0 means infinite lease
            )
            logging.info(f"Successfully mapped external port {external_port} to {local_ip}:{internal_port}.")
            return True
        except Exception as e:
            logging.error(f"Failed to add port mapping for port {external_port}: {e}")
            return False

    def remove_port_mapping(self, external_port, protocol='TCP'):
        """Removes a port mapping."""
        if not self.device:
            logging.error("Cannot remove port mapping: No UPnP device available.")
            return False

        service = self.device['WANIPConnection.1'] or self.device['WANCommonInterfaceConfig.1']
        if not service:
            logging.error("Could not find WANIPConnection or WANCommonInterfaceConfig service.")
            return False
            
        try:
            logging.info(f"Attempting to remove port mapping for external port {external_port}...")
            service.DeletePortMapping(
                NewRemoteHost='',
                NewExternalPort=external_port,
                NewProtocol=protocol
            )
            logging.info(f"Successfully removed port mapping for port {external_port}.")
            return True
        except Exception as e:
            logging.error(f"Failed to remove port mapping for port {external_port}: {e}")
            return False

if __name__ == '__main__':
    # Example usage
    print(f"Local IP: {get_local_ip()}")
    print(f"Public IP: {get_public_ip()}")

    handler = UPnPHandler()
    if handler.discover():
        PORT = 12345
        if handler.add_port_mapping(PORT, PORT):
            input("Port mapping added. Press Enter to remove it...")
            handler.remove_port_mapping(PORT)
        else:
            print("Failed to add port mapping.")
    else:
        print("Could not find a UPnP-enabled router.")

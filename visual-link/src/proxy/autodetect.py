import winreg

def get_windows_proxy():
    """
    Retrieves the proxy settings from the Windows Registry.
    Returns a dictionary with 'http' and 'https' proxy settings, or None if no proxy is set.
    """
    try:
        # Open the registry key for internet settings
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                               r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        
        # Check if a proxy is enabled
        proxy_enable = winreg.QueryValueEx(key, "ProxyEnable")[0]
        
        if proxy_enable:
            # Get the proxy server address
            proxy_server = winreg.QueryValueEx(key, "ProxyServer")[0]
            
            # Check for proxy override (bypass list)
            proxy_override = winreg.QueryValueEx(key, "ProxyOverride")[0]

            # The proxy server can be a single entry for all protocols or separate for http/https
            # This is a simplified implementation assuming a single proxy for http/https
            # For more complex scenarios, this logic would need to be expanded.
            
            proxies = {
                'http': f"http://{proxy_server}",
                'https': f"http://{proxy_server}", # Assuming http proxy for https as well
            }
            
            # The 'no_proxy' key in requests can be used for the override list
            if proxy_override:
                # The override list is typically a semicolon-separated string
                no_proxy = proxy_override.replace(';', ',')
                proxies['no_proxy'] = no_proxy
                
            return proxies
            
        winreg.CloseKey(key)
        return None

    except FileNotFoundError:
        # This key might not exist if no proxy has ever been configured
        return None
    except Exception as e:
        print(f"Error reading Windows proxy settings: {e}")
        return None

if __name__ == '__main__':
    proxy_settings = get_windows_proxy()
    if proxy_settings:
        print("Proxy Settings Found:")
        for key, value in proxy_settings.items():
            print(f"  {key}: {value}")
    else:
        print("No system proxy detected or proxy is disabled.")

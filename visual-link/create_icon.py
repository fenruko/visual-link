from PIL import Image

def create_icon(width, height, color, output_path):
    """Creates a simple icon image."""
    img = Image.new('RGB', (width, height), color=color)
    img.save(output_path)

if __name__ == '__main__':
    # Create a 64x64 blue icon
    create_icon(64, 64, 'blue', 'src/assets/icon.png')
    print("Icon created at src/assets/icon.png")

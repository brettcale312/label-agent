import sys
import asyncio
from PIL import Image
from vision_tools.vision import extract_fields_with_vision

async def main():
    if len(sys.argv) < 3:
        print("Usage: python -m vision_tools.test_vision <image_path> <type>")
        return
    img_path, type_ = sys.argv[1], sys.argv[2]
    img = Image.open(img_path)
    result = await extract_fields_with_vision(img, type_, source_filename=img_path)
    print("\n=== FINAL STRUCTURED OUTPUT ===")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())

"""Generate assets/app.ico (app + exe icon)."""
from PIL import Image, ImageDraw

def make(size: int) -> Image.Image:
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=52, fill="#171A1F")
    # battery body
    left, top, right, bottom = 34, 78, 196, 178
    d.rounded_rectangle([left, top, right, bottom], radius=18, outline="#E8EAED", width=12)
    d.rounded_rectangle([right + 8, 108, right + 24, 148], radius=6, fill="#E8EAED")
    d.rounded_rectangle([left + 20, top + 20, left + 20 + 118, bottom - 20], radius=8, fill="#3DDC84")
    # bolt
    bolt = [(142, 58), (108, 128), (132, 128), (118, 198), (166, 118), (140, 118)]
    d.polygon([(x * 256 / 256, y * 256 / 256) for x, y in bolt], fill="#FFD54A")
    return img.resize((size, size), Image.LANCZOS)

make(256).save("assets/app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("written assets/app.ico")

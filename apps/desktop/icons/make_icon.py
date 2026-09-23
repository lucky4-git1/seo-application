"""Generate the desktop app icon (run once; output is tracked in git).

Draws a simple, original mark: dark rounded square with an upward
trend-arrow + bars. No third-party assets.
"""
from PIL import Image, ImageDraw

SIZE = 1024
BG = (15, 23, 42, 255)        # slate-900
ACCENT = (56, 189, 248, 255)  # sky-400
WHITE = (248, 250, 252, 255)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=220, fill=BG)

# bars
for i, h in enumerate((300, 430, 560)):
    x0 = 200 + i * 170
    d.rounded_rectangle([x0, 780 - h, x0 + 110, 780], radius=24, fill=ACCENT)

# trend arrow
d.line([(190, 640), (430, 430), (600, 520), (830, 250)], fill=WHITE, width=56,
       joint="curve")
d.polygon([(830, 250), (700, 250), (700, 290), (830, 290),
           (830, 380), (870, 380), (870, 250)], fill=WHITE)

img.save("icon.png")
print("wrote icon.png")

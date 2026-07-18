# One-off script to populate Android/iOS icon + splash assets from the
# site's logo, since @capacitor/assets (needs `sharp`) can't install here —
# `npm install` for sharp fails downloading its prebuilt binary ("unable to
# get local issuer certificate"), which looks like this network intercepts/
# blocks TLS to GitHub releases. PIL already works fine, so generate the
# exact files Capacitor's Android/iOS templates expect by hand instead.
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
MOBILE = os.path.dirname(HERE)
REPO = os.path.dirname(MOBILE)

BRAND_BLUE = (13, 110, 253, 255)  # bootstrap primary, matches btn-primary site-wide
LOGO_PATH = os.path.join(REPO, "static", "mdb", "img", "logo.png")

logo = Image.open(LOGO_PATH).convert("RGBA")


def fit_on_canvas(w, h, bg, padding_ratio):
    """Center `logo` on a w*h canvas of color `bg` (or None for transparent),
    scaled so its largest dimension is padding_ratio of the canvas."""
    canvas = Image.new("RGBA", (w, h), bg if bg else (0, 0, 0, 0))
    target = int(min(w, h) * padding_ratio)
    ratio = min(target / logo.width, target / logo.height)
    new_w, new_h = max(1, int(logo.width * ratio)), max(1, int(logo.height * ratio))
    resized = logo.resize((new_w, new_h), Image.LANCZOS)
    canvas.paste(resized, ((w - new_w) // 2, (h - new_h) // 2), resized)
    return canvas


# ---------------------------------------------------------------- Android --
ANDROID_RES = os.path.join(MOBILE, "android", "app", "src", "main", "res")

LAUNCHER_SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}
FOREGROUND_SIZES = {
    "mipmap-mdpi": 108,
    "mipmap-hdpi": 162,
    "mipmap-xhdpi": 216,
    "mipmap-xxhdpi": 324,
    "mipmap-xxxhdpi": 432,
}
SPLASH_SIZES = {
    "drawable-port-mdpi": (320, 480),
    "drawable-port-hdpi": (480, 800),
    "drawable-port-xhdpi": (720, 1280),
    "drawable-port-xxhdpi": (960, 1600),
    "drawable-port-xxxhdpi": (1280, 1920),
    "drawable-land-mdpi": (480, 320),
    "drawable-land-hdpi": (800, 480),
    "drawable-land-xhdpi": (1280, 720),
    "drawable-land-xxhdpi": (1600, 960),
    "drawable-land-xxxhdpi": (1920, 1280),
    "drawable": (480, 320),
}

for folder, size in LAUNCHER_SIZES.items():
    flat = fit_on_canvas(size, size, BRAND_BLUE, 0.62).convert("RGB")
    flat.save(os.path.join(ANDROID_RES, folder, "ic_launcher.png"))
    flat.save(os.path.join(ANDROID_RES, folder, "ic_launcher_round.png"))

for folder, size in FOREGROUND_SIZES.items():
    # Transparent bg, smaller so the OS's adaptive-icon mask (circle/squircle/
    # rounded-square, applied at runtime) never crops the logo.
    fg = fit_on_canvas(size, size, None, 0.45)
    fg.save(os.path.join(ANDROID_RES, folder, "ic_launcher_foreground.png"))

for folder, (w, h) in SPLASH_SIZES.items():
    splash = fit_on_canvas(w, h, BRAND_BLUE, 0.4).convert("RGB")
    splash.save(os.path.join(ANDROID_RES, folder, "splash.png"))

bg_xml = os.path.join(ANDROID_RES, "values", "ic_launcher_background.xml")
with open(bg_xml, "w", encoding="utf-8") as f:
    f.write(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<resources>\n"
        '    <color name="ic_launcher_background">#0D6EFD</color>\n'
        "</resources>"
    )

print("Android icons + splash written.")

# -------------------------------------------------------------------- iOS --
IOS_ASSETS = os.path.join(MOBILE, "ios", "App", "App", "Assets.xcassets")

ios_icon = fit_on_canvas(1024, 1024, BRAND_BLUE, 0.62).convert("RGB")
ios_icon.save(os.path.join(IOS_ASSETS, "AppIcon.appiconset", "AppIcon-512@2x.png"))

ios_splash = fit_on_canvas(2732, 2732, BRAND_BLUE, 0.4).convert("RGB")
splash_dir = os.path.join(IOS_ASSETS, "Splash.imageset")
for name in ("splash-2732x2732.png", "splash-2732x2732-1.png", "splash-2732x2732-2.png"):
    ios_splash.save(os.path.join(splash_dir, name))

print("iOS icon + splash written.")

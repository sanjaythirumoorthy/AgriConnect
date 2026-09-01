"""
AI Quality Check
----------------
NOTE ON HONESTY: a real production version of this should be a CNN
(e.g. a fine-tuned MobileNet/EfficientNet) trained on labelled produce
photos (fresh/damaged/rotten). Training that needs a labelled dataset
this project doesn't have yet, so this module implements an
explainable HEURISTIC proxy on the same interface -- swap the body of
`check_quality()` for a real model call later; nothing else in the
app needs to change.

The heuristic scores three signals from the uploaded photo:
  1. Sharpness  (Laplacian-variance edge energy -> in-focus, not blurry)
  2. Brightness (well-lit vs too dark/overexposed)
  3. Color saturation (vivid vs dull/wilted-looking)
and combines them into a 0-100 quality score + letter grade.
"""
import numpy as np
from PIL import Image, ImageFilter


def _laplacian_variance(gray_img: Image.Image) -> float:
    lap = gray_img.filter(ImageFilter.FIND_EDGES)
    arr = np.asarray(lap, dtype=np.float64)
    return float(arr.var())


def check_quality(image_path: str) -> dict:
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return {"score": 0, "grade": "F", "reasons": ["Could not read image file."]}

    img_small = img.resize((400, 400))
    gray = img_small.convert("L")

    # 1. Sharpness
    sharpness_raw = _laplacian_variance(gray)
    sharpness_score = float(np.clip(sharpness_raw / 25.0, 0, 100))  # scaled heuristically

    # 2. Brightness
    brightness = float(np.asarray(gray, dtype=np.float64).mean())  # 0-255
    # Ideal brightness window ~ 90-190
    if 90 <= brightness <= 190:
        brightness_score = 100
    else:
        dist = min(abs(brightness - 90), abs(brightness - 190))
        brightness_score = max(0, 100 - dist)

    # 3. Saturation (HSV)
    hsv = np.asarray(img_small.convert("HSV"), dtype=np.float64)
    saturation = hsv[:, :, 1].mean()  # 0-255
    saturation_score = float(np.clip((saturation / 255.0) * 130, 0, 100))

    overall = round(0.4 * sharpness_score + 0.3 * brightness_score + 0.3 * saturation_score, 1)
    overall = max(0, min(100, overall))

    if overall >= 80:
        grade = "A"
    elif overall >= 60:
        grade = "B"
    elif overall >= 40:
        grade = "C"
    else:
        grade = "D"

    reasons = []
    if sharpness_score < 40:
        reasons.append("Photo looks blurry - retake in focus for a better score.")
    if brightness_score < 50:
        reasons.append("Lighting is poor - photograph in natural daylight.")
    if saturation_score < 40:
        reasons.append("Colors look dull - produce may be wilted or photo is washed out.")
    if not reasons:
        reasons.append("Clear, well-lit, vivid photo.")

    return {
        "score": overall,
        "grade": grade,
        "reasons": reasons,
        "signals": {
            "sharpness": round(sharpness_score, 1),
            "brightness": round(brightness_score, 1),
            "saturation": round(saturation_score, 1),
        },
    }

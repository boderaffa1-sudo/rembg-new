from flask import Flask, request, Response, jsonify, send_file
from PIL import Image, ImageOps
from rembg import remove, new_session
import cv2
import numpy as np
import io
import os
import sys
import time

app = Flask(__name__)

# Max Upload: 25 MB - groessere Dateien werden mit 413 abgelehnt
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024

AVAILABLE_MODELS = {
    "birefnet-general": "Bestes Allround-Modell (IoU 0.87, Dice 0.92)",
    "birefnet-general-lite": "Leichtgewicht-Version, schneller",
    "isnet-general-use": "Schnell, gut fuer einfache Bilder (IoU 0.82)",
}

DEFAULT_MODEL = "isnet-general-use"

# Global Session-Cache: Modelle einmal laden, fuer alle Requests wiederverwenden
sessions = {}

def get_session(model_name):
    if model_name not in sessions:
        print(f">>> Loading model: {model_name} ...", flush=True)
        start = time.time()
        sessions[model_name] = new_session(model_name)
        elapsed = time.time() - start
        print(f">>> Model {model_name} loaded in {elapsed:.1f}s", flush=True)
    return sessions[model_name]

# Default-Modell beim Start vorladen
print(">>> Pre-loading default model ...", flush=True)
get_session(DEFAULT_MODEL)
print(">>> Flask app ready", flush=True)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'models_loaded': list(sessions.keys()),
        'available_models': list(AVAILABLE_MODELS.keys()),
    }), 200


@app.route('/models', methods=['GET'])
def list_models():
    return jsonify({
        'default': DEFAULT_MODEL,
        'available': AVAILABLE_MODELS,
        'loaded': list(sessions.keys()),
    }), 200


@app.route('/remove-bg', methods=['POST'])
def remove_background():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided. Use field name: image'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Query-Parameter auslesen
    model_name = request.args.get('model', DEFAULT_MODEL)
    use_post_process = request.args.get('post_process_mask', 'true').lower() == 'true'
    use_alpha_matting = request.args.get('alpha_matting', 'true').lower() == 'true'
    bgcolor_hex = request.args.get('bgcolor', 'FFFFFF')
    jpeg_quality = int(request.args.get('quality', '95'))
    output_format = request.args.get('format', 'jpeg').lower()
    rotate_degrees = int(request.args.get('rotate', '0'))
    max_size = int(request.args.get('max_size', '0'))  # 0 = kein Output-Resize

    if model_name not in AVAILABLE_MODELS:
        return jsonify({
            'error': f'Unknown model: {model_name}',
            'available': list(AVAILABLE_MODELS.keys()),
        }), 400

    try:
        start = time.time()

        session = get_session(model_name)
        input_bytes = file.read()

        # Bild oeffnen
        img_input = Image.open(io.BytesIO(input_bytes))

        # Bild drehen wenn rotate Parameter gesetzt (Moebel aufrecht stellen)
        if rotate_degrees and rotate_degrees != 0:
            # Pillow rotate() dreht gegen den Uhrzeigersinn, expand=True behaelt alles
            img_input = img_input.rotate(-rotate_degrees, expand=True)
            buf = io.BytesIO()
            img_input.save(buf, format='PNG')
            input_bytes = buf.getvalue()
            print(f">>> Rotated image by {rotate_degrees} degrees", flush=True)

        # Grosse Bilder verkleinern um OOM bei Inferenz zu vermeiden
        # Railway hat begrenzt RAM - max 2048px Seitenlaenge
        max_dim = 2048
        if max(img_input.size) > max_dim:
            ratio = max_dim / max(img_input.size)
            new_size = (int(img_input.size[0] * ratio), int(img_input.size[1] * ratio))
            img_input = img_input.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            img_input.save(buf, format='PNG')
            input_bytes = buf.getvalue()
            print(f">>> Resized image from {img_input.size} to {new_size}", flush=True)

        # bgcolor parsen (hex -> RGBA tuple)
        try:
            r = int(bgcolor_hex[0:2], 16)
            g = int(bgcolor_hex[2:4], 16)
            b = int(bgcolor_hex[4:6], 16)
            bgcolor = (r, g, b, 255)
        except (ValueError, IndexError):
            bgcolor = (255, 255, 255, 255)

        # rembg remove() mit allen Optionen
        remove_kwargs = {
            'session': session,
            'post_process_mask': use_post_process,
            'bgcolor': bgcolor,
        }

        if use_alpha_matting:
            remove_kwargs['alpha_matting'] = True
            remove_kwargs['alpha_matting_foreground_threshold'] = 270
            remove_kwargs['alpha_matting_background_threshold'] = 20
            remove_kwargs['alpha_matting_erode_size'] = 11

        output_bytes = remove(input_bytes, **remove_kwargs)

        # Ausgabe-Format bestimmen
        img = Image.open(io.BytesIO(output_bytes))

        # Output-Resize wenn max_size gesetzt (laengste Seite)
        if max_size > 0 and max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_w = int(img.size[0] * ratio)
            new_h = int(img.size[1] * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            print(f">>> Output resized to {new_w}x{new_h} (max_size={max_size})", flush=True)

        # sRGB Farbraum sicherstellen
        try:
            from PIL.ImageCms import profileToProfile, createProfile
            srgb = createProfile('sRGB')
            if img.info.get('icc_profile'):
                from io import BytesIO as BIO
                from PIL.ImageCms import ImageCmsProfile
                img = profileToProfile(img, ImageCmsProfile(BIO(img.info['icc_profile'])), srgb)
        except Exception:
            pass  # Kein ICC Profil oder Fehler - ignorieren

        if output_format == 'png':
            output_buf = io.BytesIO()
            img.save(output_buf, format='PNG')
            mimetype = 'image/png'
            ext = 'png'
        else:
            # JPEG: Transparenz entfernen falls vorhanden
            if img.mode == 'RGBA':
                bg = Image.new("RGBA", img.size, bgcolor)
                bg.paste(img, mask=img.split()[3])
                img = bg.convert("RGB")
            elif img.mode != 'RGB':
                img = img.convert("RGB")
            output_buf = io.BytesIO()
            img.save(output_buf, format='JPEG', quality=jpeg_quality)
            mimetype = 'image/jpeg'
            ext = 'jpg'

        output_buf.seek(0)
        elapsed = time.time() - start

        return Response(
            output_buf.getvalue(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename=removed_bg.{ext}',
                'X-Processing-Time': f'{elapsed:.2f}s',
                'X-Model-Used': model_name,
                'X-Post-Process': str(use_post_process),
                'X-Alpha-Matting': str(use_alpha_matting),
                'X-Rotation': str(rotate_degrees),
            }
        )

    except Exception as e:
        print(f">>> Error ({model_name}): {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'model': model_name,
        }), 500


# ============================================================
# /crop-book — Smart Crop fuer Buch-Fotos
# Erkennt Buch per Kontur, schneidet zu, weisser Hintergrund
# ============================================================

def smart_crop_book(img_cv):
    """Findet das Buch im Foto und schneidet es sauber heraus."""
    height, width = img_cv.shape[:2]

    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)

    kernel = np.ones((3, 3), np.uint8)
    edges_dilated = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(
        edges_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return simple_center_crop(img_cv)

    min_area = width * height * 0.15
    valid_contours = [c for c in contours if cv2.contourArea(c) > min_area]

    if not valid_contours:
        return simple_center_crop(img_cv)

    largest = max(valid_contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(largest)

    padding_px = 10
    x = max(0, x - padding_px)
    y = max(0, y - padding_px)
    w = min(width - x, w + padding_px * 2)
    h = min(height - y, h + padding_px * 2)

    cropped = img_cv[y:y+h, x:x+w]
    img_pil = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))

    img_pil = ImageOps.pad(
        img_pil, (1200, 1600),
        color=(255, 255, 255), centering=(0.5, 0.5)
    )
    return img_pil


def simple_center_crop(img_cv):
    """Fallback: Center-Crop auf 3:4 + weisser Hintergrund."""
    height, width = img_cv.shape[:2]
    target_ratio = 3 / 4
    current_ratio = width / height

    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        start_x = (width - new_width) // 2
        cropped = img_cv[:, start_x:start_x + new_width]
    else:
        new_height = int(width / target_ratio)
        start_y = (height - new_height) // 2
        cropped = img_cv[start_y:start_y + new_height, :]

    img_pil = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
    img_pil = img_pil.resize((1200, 1600), Image.LANCZOS)
    return img_pil


@app.route('/crop-book', methods=['POST'])
def crop_book():
    """Smart Crop fuer Buch-Fotos: Buch erkennen, zuschneiden, weisser BG."""
    image_bytes = None
    try:
        start = time.time()

        if 'image' in request.files:
            image_bytes = request.files['image'].read()
        else:
            image_bytes = request.data

        if not image_bytes:
            return jsonify({'error': 'no image data'}), 400

        nparr = np.frombuffer(image_bytes, np.uint8)
        img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img_cv is None:
            return jsonify({'error': 'invalid image'}), 400

        result_img = smart_crop_book(img_cv)

        output = io.BytesIO()
        result_img.save(output, format='JPEG', quality=92)
        output.seek(0)

        elapsed = time.time() - start
        print(f">>> crop-book: {elapsed:.2f}s", flush=True)

        return send_file(output, mimetype='image/jpeg',
                         download_name='book_cropped.jpg')

    except Exception as e:
        print(f">>> crop-book error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        if image_bytes:
            return send_file(io.BytesIO(image_bytes), mimetype='image/jpeg',
                             download_name='book_original.jpg')
        return jsonify({'error': str(e)}), 500


# ============================================================
# /resize — Resize ohne BG-Entfernung
# Fuer Buecher, Glas, und andere skip-BG Items
# ============================================================
@app.route('/resize', methods=['POST'])
def resize_image():
    """Resize image to max_size on longest side + optional rotation."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided. Use field name: image'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    max_size = int(request.args.get('max_size', '2400'))
    jpeg_quality = int(request.args.get('quality', '85'))
    output_format = request.args.get('format', 'jpeg').lower()
    rotate_degrees = int(request.args.get('rotate', '0'))

    try:
        start = time.time()
        input_bytes = file.read()
        img = Image.open(io.BytesIO(input_bytes))

        # Rotation
        if rotate_degrees and rotate_degrees != 0:
            img = img.rotate(-rotate_degrees, expand=True)

        # Resize laengste Seite
        if max_size > 0 and max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_w = int(img.size[0] * ratio)
            new_h = int(img.size[1] * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # sRGB
        try:
            from PIL.ImageCms import profileToProfile, createProfile
            srgb = createProfile('sRGB')
            if img.info.get('icc_profile'):
                from io import BytesIO as BIO
                from PIL.ImageCms import ImageCmsProfile
                img = profileToProfile(img, ImageCmsProfile(BIO(img.info['icc_profile'])), srgb)
        except Exception:
            pass

        output_buf = io.BytesIO()
        if output_format == 'png':
            img.save(output_buf, format='PNG')
            mimetype = 'image/png'
            ext = 'png'
        else:
            if img.mode == 'RGBA':
                bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg.convert("RGB")
            elif img.mode != 'RGB':
                img = img.convert("RGB")
            img.save(output_buf, format='JPEG', quality=jpeg_quality)
            mimetype = 'image/jpeg'
            ext = 'jpg'

        output_buf.seek(0)
        elapsed = time.time() - start
        print(f">>> resize: {img.size[0]}x{img.size[1]}, {elapsed:.2f}s", flush=True)

        return Response(
            output_buf.getvalue(),
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename=resized.{ext}',
                'X-Processing-Time': f'{elapsed:.2f}s',
                'X-Output-Size': f'{img.size[0]}x{img.size[1]}',
            }
        )

    except Exception as e:
        print(f">>> resize error: {e}", flush=True)
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f">>> Starting Flask on 0.0.0.0:{port}", flush=True)
    sys.stdout.flush()
    app.run(host='0.0.0.0', port=port)

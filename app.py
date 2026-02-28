from flask import Flask, request, Response, jsonify
from PIL import Image
from rembg import remove, new_session
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

DEFAULT_MODEL = "birefnet-general"

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
    use_alpha_matting = request.args.get('alpha_matting', 'false').lower() == 'true'
    bgcolor_hex = request.args.get('bgcolor', 'FFFFFF')
    jpeg_quality = int(request.args.get('quality', '95'))
    output_format = request.args.get('format', 'jpeg').lower()

    if model_name not in AVAILABLE_MODELS:
        return jsonify({
            'error': f'Unknown model: {model_name}',
            'available': list(AVAILABLE_MODELS.keys()),
        }), 400

    try:
        start = time.time()

        session = get_session(model_name)
        input_bytes = file.read()

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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f">>> Starting Flask on 0.0.0.0:{port}", flush=True)
    sys.stdout.flush()
    app.run(host='0.0.0.0', port=port)

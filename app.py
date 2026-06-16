import os
import json
from flask import Flask, jsonify, request, send_from_directory, render_template_string
from cryptography.fernet import Fernet

app = Flask(__name__, static_folder='static')

BASE_DIR = os.path.dirname(__file__)
RECORDINGS_FOLDER = os.path.join(BASE_DIR, 'recordings')
ENCRYPTION_KEY = os.environ.get('SECRET_KEY')


def get_cipher():
    if not ENCRYPTION_KEY:
        raise RuntimeError("Missing SECRET_KEY environment variable!")
    return Fernet(ENCRYPTION_KEY.encode())


# Helper to determine localized pathings
def get_paths(lang):
    # Sanitize lang variable to prevent path traversal exploits
    safe_lang = "".join([c for c in lang if c.isalpha()]).lower()
    data_file = os.path.join(BASE_DIR, f'prompts_{safe_lang}.enc')
    lang_upload_dir = os.path.join(RECORDINGS_FOLDER, safe_lang)
    os.makedirs(lang_upload_dir, exist_ok=True)
    return data_file, lang_upload_dir


# --- DECRYPT MULTI-LANG DATASETS ON THE FLY ---
def read_jsonl(lang):
    data_file, _ = get_paths(lang)
    if not os.path.exists(data_file):
        return []
    cipher = get_cipher()
    with open(data_file, 'rb') as f:
        encrypted_data = f.read()
    decrypted_bytes = cipher.decrypt(encrypted_data)
    return [json.loads(line) for line in decrypted_bytes.decode('utf-8').split('\n') if line.strip()]


# --- RE-ENCRYPT MULTI-LANG DATASETS ON SAVE ---
def write_jsonl(lang, data):
    data_file, _ = get_paths(lang)
    cipher = get_cipher()
    plain_text = "".join([json.dumps(item) + '\n' for item in data])
    encrypted_data = cipher.encrypt(plain_text.encode('utf-8'))
    with open(data_file, 'wb') as f:
        f.write(encrypted_data)


# --- ROUTING STATIC HTML LAYOUTS ---

@app.route('/')
def home():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/<lang>/speaker')
def speaker_page(lang):
    return send_from_directory(BASE_DIR, 'speaker.html')


@app.route('/<lang>/reviewer')
def reviewer_page(lang):
    return send_from_directory(BASE_DIR, 'reviewer.html')


@app.route('/recordings/<lang>/<filename>')
def serve_recording(lang, filename):
    _, lang_upload_dir = get_paths(lang)
    return send_from_directory(lang_upload_dir, filename)


# --- MULTI-LANGUAGE DYNAMIC API ENDPOINTS ---

@app.route('/api/<lang>/next-prompt', methods=['GET'])
def get_next_prompt(lang):
    data = read_jsonl(lang)
    unrecorded = [item for item in data if not item['recorded']]
    if unrecorded:
        return jsonify(unrecorded[0])
    return jsonify({"done": True, "message": "All sentences in this language have been recorded!"})


@app.route('/upload/<lang>/<int:prompt_id>', methods=['POST'])
def upload_audio(lang, prompt_id):
    if 'audio' not in request.files:
        return "Missing audio", 400
    file = request.files['audio']

    _, lang_upload_dir = get_paths(lang)
    filename = f"prompt_{prompt_id}.wav"
    file.save(os.path.join(lang_upload_dir, filename))

    data = read_jsonl(lang)
    for item in data:
        if item['id'] == prompt_id:
            item['recorded'] = True
            break
    write_jsonl(lang, data)
    return jsonify({"success": True})


@app.route('/api/<lang>/review-list', methods=['GET'])
def get_review_list(lang):
    data = read_jsonl(lang)
    to_review = [item for item in data if item['recorded'] and not item['checked']]
    return jsonify(to_review)


@app.route('/api/<lang>/review-action/<int:prompt_id>', methods=['POST'])
def review_action(lang, prompt_id):
    req_data = request.get_json()
    action = req_data.get('action')

    data = read_jsonl(lang)
    _, lang_upload_dir = get_paths(lang)

    for item in data:
        if item['id'] == prompt_id:
            if action == 'approve':
                item['checked'] = True
            elif action == 'reject':
                item['recorded'] = False
                item['checked'] = False
                try:
                    os.remove(os.path.join(lang_upload_dir, f"prompt_{prompt_id}.wav"))
                except FileNotFoundError:
                    pass
            break
    write_jsonl(lang, data)
    return jsonify({"success": True})


if __name__ == '__main__':
    app.run(port=5000, debug=True)
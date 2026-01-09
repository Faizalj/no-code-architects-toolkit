from flask import Blueprint, request, jsonify, send_file
from google import genai
from google.genai import types
import os
import uuid
import struct
import mimetypes

# สร้าง Blueprint เพื่อให้ NCA Toolkit มองเห็น
gemini_tts_bp = Blueprint('gemini_tts', __name__)

# --- Helper Functions จากโค้ดเดิมของคุณ ---
def parse_audio_mime_type(mime_type: str):
    bits_per_sample = 16
    rate = 24000
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except: pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except: pass
    return {"bits_per_sample": bits_per_sample, "rate": rate}

def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size
    
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", chunk_size, b"WAVE", b"fmt ", 16, 1, num_channels,
        sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size
    )
    return header + audio_data

# --- API Endpoint ---
@gemini_tts_bp.route('/v1/audio/gemini-tts', methods=['POST'])
def generate_gemini_speech():
    try:
        # 1. รับค่าจาก Request
        data = request.json
        text = data.get('text')
        voice_name = data.get('voice_name', 'Fenrir') # Default เป็น Fenrir ตามที่คุณชอบ
        api_key = os.getenv("GEMINI_API_KEY") # ดึง Key จาก Env ของ Coolify

        if not text:
            return jsonify({"error": "No text provided"}), 400
        if not api_key:
            return jsonify({"error": "GEMINI_API_KEY not found in environment variables"}), 500

        # 2. ตั้งค่า Gemini Client
        client = genai.Client(api_key=api_key)
        
        # 3. เตรียม Config
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=text)],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
            temperature=1,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        )

        # 4. เรียกใช้ Gemini Model
        # หมายเหตุ: ใช้ model ตัวเดียวกับที่คุณใช้
        response_stream = client.models.generate_content_stream(
            model="gemini-2.5-flash-preview-tts",
            contents=contents,
            config=generate_content_config,
        )

        # 5. วนลูปเอาข้อมูลเสียง (Logic เดิมของคุณ)
        audio_bytes = None
        for chunk in response_stream:
            if (chunk.candidates and chunk.candidates[0].content and 
                chunk.candidates[0].content.parts):
                
                part = chunk.candidates[0].content.parts[0]
                if part.inline_data and part.inline_data.data:
                    raw_data = part.inline_data.data
                    mime_type = part.inline_data.mime_type
                    # แปลงเป็น WAV
                    audio_bytes = convert_to_wav(raw_data, mime_type)
                    break # เอา chunk แรกที่มีเสียง (ปกติมาทีเดียว)

        if not audio_bytes:
            return jsonify({"error": "No audio generated from Gemini"}), 500

        # 6. บันทึกไฟล์ชั่วคราว
        filename = f"gemini_{uuid.uuid4()}.wav"
        save_path = os.path.join("/tmp", filename)
        
        with open(save_path, "wb") as f:
            f.write(audio_bytes)

        # 7. ส่งไฟล์กลับ
        return send_file(save_path, mimetype="audio/wav")

    except Exception as e:
        return jsonify({"error": str(e)}), 500

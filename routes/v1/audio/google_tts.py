from flask import Blueprint, request, jsonify, send_file
from app_utils import *
import logging
import os
import uuid
import struct
from google import genai
from google.genai import types
from services.authentication import authenticate 
from services.cloud_storage import upload_file

# ชื่อ Blueprint ที่ระบบ Auto-scan จะหาเจอ
blueprint = Blueprint("v1_audio_gemini_tts", __name__)
logger = logging.getLogger(__name__)

# --- Helper สำหรับแปลงเสียง (จากโค้ดเดิมของคุณ) ---
def parse_audio_mime_type(mime_type: str):
    bits_per_sample = 16
    rate = 24000
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try: rate = int(param.split("=", 1)[1])
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
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", chunk_size, b"WAVE", b"fmt ", 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample, b"data", data_size)
    return header + audio_data

# --- API Endpoint ---
@blueprint.route("/v1/audio/gemini-tts", methods=["POST"])
@authenticate
@validate_payload({
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "voice_name": {"type": "string"},
    },
    "required": ["text"],
    "additionalProperties": False,
})
@queue_task_wrapper(bypass_queue=True)
def generate_gemini_speech(job_id, data):
    text = data.get('text')
    voice_name = data.get('voice_name', 'Fenrir')
    api_key = os.getenv("GEMINI_API_KEY")

    logger.info(f"Job {job_id}: Generating Gemini TTS...")

    try:
        if not api_key:
            raise Exception("Missing GEMINI_API_KEY")

        client = genai.Client(api_key=api_key)
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=text)])]
        
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
        )

        response_stream = client.models.generate_content_stream(
            model="gemini-2.5-flash-preview-tts",
            contents=contents,
            config=generate_content_config,
        )

        audio_bytes = None
        for chunk in response_stream:
            if chunk.candidates and chunk.candidates[0].content.parts:
                part = chunk.candidates[0].content.parts[0]
                if part.inline_data:
                    audio_bytes = convert_to_wav(part.inline_data.data, part.inline_data.mime_type)
                    break

        if not audio_bytes:
            raise Exception("No audio generated from Gemini")

        # เซฟไฟล์ลง /tmp ก่อน
        filename = f"gemini_{uuid.uuid4()}.wav"
        save_path = os.path.join("/tmp", filename)
        with open(save_path, "wb") as f:
            f.write(audio_bytes)


        # ใช้ฟังก์ชันอัปโหลดของ NCA (ซึ่งจะเก็บ Local ถ้าไม่มี Cloud)
        try:
            cloud_url = upload_file(save_path)
            
            # ถ้าระบบคืนค่าเป็น URL มาให้ (ไม่ว่าจะ Local หรือ Cloud)
            if isinstance(cloud_url, str) and (cloud_url.startswith('http') or cloud_url.startswith('/static')):
                return cloud_url, "/v1/audio/gemini-tts", 200
        
        except ValueError as e:
            # ไม่มี cloud storage ที่ตั้งค่าไว้ - ส่งไฟล์โดยตรงแทน
            logger.warning(f"Job {job_id}: No cloud storage configured ({str(e)}), returning file directly")
        
        # กรณีฉุกเฉิน: ถ้า upload_file พังหรือไม่คืน URL ให้ส่งไฟล์กลับตรงๆ เลย
        return send_file(save_path, mimetype="audio/wav")

    except Exception as e:
        logger.error(f"Job {job_id}: Error - {str(e)}")
        return str(e), "/v1/audio/gemini-tts", 500

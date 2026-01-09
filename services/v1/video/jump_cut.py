# Copyright (c) 2025 Stephen G. Pope
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.



import os
import uuid
import logging
from typing import List, Tuple, Dict
from services.v1.media.silence import detect_silence
from services.v1.media.metadata import get_media_metadata
from services.media_downloader import download_media

logger = logging.getLogger(__name__)


def get_speech_intervals(
    total_duration: float,
    silence_intervals: List[Dict],
    min_speech_duration: float = 0.3,
    padding_before: float = 0.1,
    padding_after: float = 0.1
) -> List[Tuple[float, float]]:
    """
    แปลงช่วงเงียบเป็นช่วงที่มีเสียงพูด
    
    Args:
        total_duration: ความยาววิดีโอทั้งหมด (วินาที)
        silence_intervals: รายการช่วงเงียบ [{"start": x, "end": y}, ...]
        min_speech_duration: ช่วงพูดสั้นกว่านี้จะถูกตัดทิ้ง (วินาที)
        padding_before: เผื่อเวลาก่อนเริ่มพูด (วินาที)
        padding_after: เผื่อเวลาหลังพูดจบ (วินาที)
    
    Returns:
        รายการช่วงที่มีเสียงพูด [(start, end), ...]
    """
    
    speech_intervals = []
    current_time = 0.0
    
    # เรียงช่วงเงียบตาม start time
    sorted_silences = sorted(silence_intervals, key=lambda x: x['start'])
    
    for silence in sorted_silences:
        silence_start = silence['start']
        silence_end = silence['end']
        
        # ช่วงก่อนความเงียบ = ช่วงที่มีเสียง
        if current_time < silence_start:
            speech_start = max(0, current_time - padding_before)
            speech_end = min(total_duration, silence_start + padding_after)
            
            # เช็คว่าช่วงนี้ยาวพอหรือไม่
            if (speech_end - speech_start) >= min_speech_duration:
                speech_intervals.append((speech_start, speech_end))
        
        current_time = silence_end
    
    # ช่วงสุดท้าย (หลังความเงียบสุดท้าย ถึงจบวิดีโอ)
    if current_time < total_duration:
        speech_start = max(0, current_time - padding_before)
        speech_end = total_duration
        
        if (speech_end - speech_start) >= min_speech_duration:
            speech_intervals.append((speech_start, speech_end))
    
    # ถ้าไม่มีช่วงเงียบเลย = วิดีโอทั้งหมดมีเสียง
    if not sorted_silences and total_duration >= min_speech_duration:
        speech_intervals.append((0.0, total_duration))
    
    logger.info(f"Found {len(speech_intervals)} speech intervals from {len(silence_intervals)} silence intervals")
    
    return speech_intervals


def build_ffmpeg_select_filter(speech_intervals: List[Tuple[float, float]]) -> str:
    """
    สร้าง FFmpeg select filter สำหรับเลือกเฉพาะช่วงที่มีเสียง
    
    Args:
        speech_intervals: รายการช่วงที่มีเสียง [(start, end), ...]
    
    Returns:
        FFmpeg filter string
    """
    
    if not speech_intervals:
        raise ValueError("No speech intervals to process")
    
    # สร้าง condition สำหรับ select filter
    conditions = []
    for start, end in speech_intervals:
        conditions.append(f"between(t,{start:.3f},{end:.3f})")
    
    select_expr = '+'.join(conditions)
    
    # Video และ Audio ต้องใช้ filter แยกกัน
    video_filter = f"select='{select_expr}',setpts=N/FRAME_RATE/TB"
    audio_filter = f"aselect='{select_expr}',asetpts=N/SR/TB"
    
    return video_filter, audio_filter


def process_jump_cut(
    media_url: str,
    job_id: str,
    silence_threshold: str = '-30dB',
    min_silence_duration: float = 0.5,
    min_speech_duration: float = 0.3,
    padding_before: float = 0.1,
    padding_after: float = 0.1,
    output_codec: str = 'libx264',
    output_crf: int = 23
) -> str:
    """
    ประมวลผล jump cut video - ตัดช่วงเงียบออกอัตโนมัติ
    
    Args:
        media_url: URL ของวิดีโอต้นฉบับ
        job_id: Job ID
        silence_threshold: ค่า threshold สำหรับตรวจจับความเงียบ (dB)
        min_silence_duration: ความเงียบขั้นต่ำที่จะถือว่าเป็นช่วงเงียบ (วินาที)
        min_speech_duration: ช่วงพูดสั้นกว่านี้จะถูกตัดทิ้ง (วินาที)
        padding_before: เผื่อเวลาก่อนเริ่มพูด (วินาที)
        padding_after: เผื่อเวลาหลังพูดจบ (วินาที)
        output_codec: Video codec สำหรับ output
        output_crf: CRF quality (0-51, ต่ำ = คุณภาพสูง)
    
    Returns:
        ไฟล์ output path
    """
    
    logger.info(f"Job {job_id}: Starting jump cut process for {media_url}")
    
    # 1. ดาวน์โหลดวิดีโอ
    logger.info(f"Job {job_id}: Downloading video...")
    local_file = download_media(media_url, job_id)
    
    # 2. ดึง metadata เพื่อรู้ความยาววิดีโอ
    logger.info(f"Job {job_id}: Getting video metadata...")
    metadata = get_media_metadata(media_url, job_id)
    total_duration = float(metadata.get('duration', 0))
    
    if total_duration == 0:
        raise ValueError("Cannot determine video duration")
    
    logger.info(f"Job {job_id}: Video duration: {total_duration:.2f}s")
    
    # 3. ตรวจจับช่วงเงียบ
    logger.info(f"Job {job_id}: Detecting silence intervals...")
    silence_data = detect_silence(
        media_url=media_url,
        noise_threshold=silence_threshold,
        min_duration=min_silence_duration,
        mono=True,
        job_id=job_id
    )
    
    silence_intervals = silence_data.get('silence_intervals', [])
    logger.info(f"Job {job_id}: Found {len(silence_intervals)} silence intervals")
    
    # 4. แปลงเป็นช่วงที่มีเสียง
    logger.info(f"Job {job_id}: Calculating speech intervals...")
    speech_intervals = get_speech_intervals(
        total_duration=total_duration,
        silence_intervals=silence_intervals,
        min_speech_duration=min_speech_duration,
        padding_before=padding_before,
        padding_after=padding_after
    )
    
    if not speech_intervals:
        raise ValueError("No speech detected in video - result would be empty")
    
    logger.info(f"Job {job_id}: Processing {len(speech_intervals)} speech segments")
    
    # 5. สร้าง FFmpeg filter
    video_filter, audio_filter = build_ffmpeg_select_filter(speech_intervals)
    
    # 6. สร้างไฟล์ output
    output_filename = f"jump_cut_{uuid.uuid4()}.mp4"
    output_path = os.path.join("/tmp", output_filename)
    
    # 7. รัน FFmpeg
    logger.info(f"Job {job_id}: Running FFmpeg with jump cut filters...")
    
    import subprocess
    
    cmd = [
        'ffmpeg',
        '-i', local_file,
        '-vf', video_filter,
        '-af', audio_filter,
        '-c:v', output_codec,
        '-crf', str(output_crf),
        '-c:a', 'aac',
        '-b:a', '128k',
        '-y',  # Overwrite
        output_path
    ]
    
    logger.info(f"Job {job_id}: FFmpeg command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes timeout
        )
        
        if result.returncode != 0:
            logger.error(f"Job {job_id}: FFmpeg error: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")
        
        logger.info(f"Job {job_id}: Jump cut completed successfully")
        logger.info(f"Job {job_id}: Original intervals: {len(silence_intervals)} silences")
        logger.info(f"Job {job_id}: Result intervals: {len(speech_intervals)} speech segments")
        
        # Cleanup input file
        if os.path.exists(local_file):
            os.remove(local_file)
        
        return output_path
        
    except subprocess.TimeoutExpired:
        logger.error(f"Job {job_id}: FFmpeg timeout")
        raise RuntimeError("Video processing timeout (>10 minutes)")
    
    except Exception as e:
        logger.error(f"Job {job_id}: Error during FFmpeg processing: {str(e)}")
        raise

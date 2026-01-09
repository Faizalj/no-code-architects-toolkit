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
import logging
from flask import Blueprint
from app_utils import validate_payload, queue_task_wrapper
from services.authentication import authenticate
from services.v1.video.jump_cut import process_jump_cut
from services.cloud_storage import upload_file

logger = logging.getLogger(__name__)

v1_video_jump_cut_bp = Blueprint('v1_video_jump_cut', __name__)


@v1_video_jump_cut_bp.route('/v1/video/jump-cut', methods=['POST'])
@authenticate
@validate_payload({
    "type": "object",
    "properties": {
        "video_url": {"type": "string", "format": "uri"},
        "silence_threshold": {"type": "string"},  # e.g. "-30dB"
        "min_silence_duration": {"type": "number", "minimum": 0.1},
        "min_speech_duration": {"type": "number", "minimum": 0.1},
        "padding_before": {"type": "number", "minimum": 0},
        "padding_after": {"type": "number", "minimum": 0},
        "output_codec": {"type": "string"},
        "output_crf": {"type": "integer", "minimum": 0, "maximum": 51},
        "webhook_url": {"type": "string", "format": "uri"},
        "id": {"type": "string"}
    },
    "required": ["video_url"],
    "additionalProperties": False
})
@queue_task_wrapper(bypass_queue=False)
def jump_cut_video(job_id, data):
    """
    Auto jump cut - ตัดช่วงเงียบออกอัตโนมัติ
    
    ทำให้วิดีโอกระชับขึ้นโดยตัดช่วงที่ไม่มีเสียงพูดออก
    เหมาะสำหรับ tutorial videos, podcasts, interviews
    
    Request:
    {
        "video_url": "https://example.com/video.mp4",
        
        // Silence detection settings
        "silence_threshold": "-30dB",          // default: -30dB
        "min_silence_duration": 0.5,           // default: 0.5s
        
        // Jump cut settings
        "min_speech_duration": 0.3,            // default: 0.3s
        "padding_before": 0.1,                 // default: 0.1s
        "padding_after": 0.1,                  // default: 0.1s
        
        // Output settings
        "output_codec": "libx264",             // default: libx264
        "output_crf": 23,                      // default: 23
        
        // Optional
        "webhook_url": "https://...",
        "id": "custom-id"
    }
    
    Response:
    {
        "video_url": "https://storage.../jump_cut_xxx.mp4",
        "job_id": "xxx",
        "original_duration": 120.5,
        "final_duration": 85.2,
        "time_saved": 35.3,
        "segments_removed": 15
    }
    """
    
    video_url = data['video_url']
    
    # Parameters with defaults
    silence_threshold = data.get('silence_threshold', '-30dB')
    min_silence_duration = data.get('min_silence_duration', 0.5)
    min_speech_duration = data.get('min_speech_duration', 0.3)
    padding_before = data.get('padding_before', 0.1)
    padding_after = data.get('padding_after', 0.1)
    output_codec = data.get('output_codec', 'libx264')
    output_crf = data.get('output_crf', 23)
    
    logger.info(f"Job {job_id}: Starting jump cut for {video_url}")
    logger.info(f"Job {job_id}: Settings - threshold: {silence_threshold}, "
                f"min_silence: {min_silence_duration}s, min_speech: {min_speech_duration}s")
    
    try:
        # Process jump cut
        output_path = process_jump_cut(
            media_url=video_url,
            job_id=job_id,
            silence_threshold=silence_threshold,
            min_silence_duration=min_silence_duration,
            min_speech_duration=min_speech_duration,
            padding_before=padding_before,
            padding_after=padding_after,
            output_codec=output_codec,
            output_crf=output_crf
        )
        
        logger.info(f"Job {job_id}: Jump cut completed, uploading to storage...")
        
        # Upload to cloud storage
        cloud_url = upload_file(output_path)
        
        # Get file info for response
        from services.v1.media.metadata import get_media_metadata
        
        original_metadata = get_media_metadata(video_url, job_id)
        final_metadata = get_media_metadata(cloud_url, job_id)
        
        original_duration = float(original_metadata.get('duration', 0))
        final_duration = float(final_metadata.get('duration', 0))
        time_saved = original_duration - final_duration
        
        # Cleanup
        if os.path.exists(output_path):
            os.remove(output_path)
        
        logger.info(f"Job {job_id}: Success! Reduced from {original_duration:.1f}s to {final_duration:.1f}s "
                    f"(saved {time_saved:.1f}s)")
        
        # Return result
        result = {
            "video_url": cloud_url,
            "original_duration": round(original_duration, 2),
            "final_duration": round(final_duration, 2),
            "time_saved": round(time_saved, 2),
            "compression_ratio": round((time_saved / original_duration * 100), 1) if original_duration > 0 else 0
        }
        
        return result, "/v1/video/jump-cut", 200
        
    except ValueError as e:
        logger.error(f"Job {job_id}: Validation error - {str(e)}")
        return str(e), "/v1/video/jump-cut", 400
        
    except Exception as e:
        logger.error(f"Job {job_id}: Error during jump cut - {str(e)}")
        return str(e), "/v1/video/jump-cut", 500

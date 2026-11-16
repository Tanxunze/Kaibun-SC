"""Locally authored voice errors; provider bodies and credentials stay private."""

class VoiceError(ValueError):
    pass

def voice_failure(error):
    return str(error) if isinstance(error, VoiceError) else '语音生成失败，请稍后重试'

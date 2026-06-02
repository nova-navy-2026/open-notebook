from api.chat_agents.base import make_agent


AGENT = make_agent(
    name="transcription",
    handler="transcription",
    description="Transcrever áudio/vídeo, diarizar, identificar falantes.",
    routing_guidance="Usa quando o utilizador quer transcrição, diarização, oradores/falantes ou fala para texto.",
    parameters={"diarize": "true se o utilizador pedir falantes/oradores"},
    fallback_keywords=("transcrever", "transcricao", "transcription", "transcribe", "diarizar", "speaker", "orador", "falante"),
    file_type_prefixes=("audio/", "video/"),
)


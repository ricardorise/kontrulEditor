from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KONTRUL_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://kontrul:kontrul@localhost:5432/kontrul"
    redis_url: str = "redis://localhost:6379/0"
    data_dir: Path = Path("./data")
    api_token: str = "dev-token-change-me"
    preview_height: int = 720
    preview_preset: str = "veryfast"
    preview_crf: int = 28
    final_preset: str = "medium"
    final_crf: int = 18
    max_fps: int = 60
    job_stale_s: int = 180            # job "running" sem heartbeat por este tempo = worker perdido
    heartbeat_s: int = 15
    render_timeout_s: int = 6 * 3600
    max_active_render_jobs: int = 3   # por projeto (429 acima disso)
    max_active_asr_jobs: int = 2
    # Pool > threads do servidor (anyio=40): senão requisições seguram conexão esperando thread p/ fechar a sessão (deadlock)
    db_pool_size: int = 30
    db_max_overflow: int = 30
    db_pool_timeout_s: int = 10
    # ---- LLM (opcional). Padrão "none": nada sai da máquina. Provedores: anthropic | openai | openrouter | ollama
    llm_provider: str = "none"
    llm_model: str = ""                   # anthropic tem padrão; openai/openrouter/ollama exigem o nome do modelo
    llm_base_url: str = ""                # sobrescreve a URL do provedor (proxy, Azure/compatível OpenAI, etc.)
    llm_timeout_s: int = 120
    llm_max_tokens: int = 4096
    llm_window_words: int = 700           # tamanho de cada janela de transcrição enviada ao LLM
    llm_max_windows: int = 40             # teto de chamadas por análise (controle de custo)
    anthropic_api_key: str = Field(default="", validation_alias=AliasChoices("KONTRUL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    openai_api_key: str = Field(default="", validation_alias=AliasChoices("KONTRUL_OPENAI_API_KEY", "OPENAI_API_KEY"))
    openrouter_api_key: str = Field(default="", validation_alias=AliasChoices("KONTRUL_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"))
    ollama_host: str = Field(default="http://localhost:11434", validation_alias=AliasChoices("KONTRUL_OLLAMA_HOST", "OLLAMA_HOST"))
    ollama_num_ctx: int = 8192
    env: str = "development"          # "production" exige token forte
    max_upload_bytes: int = 20 * 1024**3
    whisper_model: str = "large-v3"
    asr_device: str = "auto"              # auto (GPU se houver, senão CPU) | cuda (exige GPU; falha alto) | cpu
    whisper_language: str = "pt"
    hf_token: str = ""


settings = Settings()

"""The constrained Claude API call (§3.6).

Contract with the rest of the system:

- Input is the §3.6 payload — computed values only. Raw respondent-level data
  never reaches this module, which is what §5's KVKK requirement turns on.
- The system prompt forbids computing, and pins the model to the fixed sentence
  template for the test at hand.
- The output is NOT trusted. `app.interpretation.service` validates every
  numeric token against the payload before anything is shown to a user.

If no API key is configured, or the call fails, the caller falls back to the
deterministic template. The product must work without the LLM — the LLM only
makes the prose read more naturally.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.config import settings
from app.interpretation.templates import PROMPT_TEMPLATES

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sen bir akademik istatistik raporlama asistanısın. Görevin, SANA VERİLEN hesaplanmış istatistiksel sonuçları Türkçe, APA 7 stilinde tek bir yorum paragrafına dönüştürmektir.

MUTLAK KURALLAR:
1. HİÇBİR HESAPLAMA YAPMA. Sana verilen JSON'daki sayıları olduğu gibi kullan.
2. JSON'da BULUNMAYAN hiçbir sayıyı metne yazma. Yıl, kaynak, yüzde, örneklem sayısı, hiçbir yeni sayı ekleme.
3. Sana verilen cümle şablonuna sadık kal. Şablonun dışına çıkma, yeni cümle türü ekleme.
4. Sonuçları yorumlarken nedensellik iddiasında bulunma; yalnızca bulguyu betimle.
5. Kaynak gösterme, alıntı yapma, literatür tartışması yapma.
6. Yalnızca yorum paragrafını döndür. Başlık, madde işareti, açıklama veya markdown biçimlendirmesi ekleme.

Sayıları JSON'daki değerlerle birebir aynı yaz. p değerleri için APA kuralına uy: p < .001 ise "p < .001" yaz."""


@dataclass
class LLMResponse:
    text: str
    model: str
    used_llm: bool
    error: Optional[str] = None


def _user_prompt(payload: dict[str, Any]) -> str:
    template = PROMPT_TEMPLATES.get(payload["analysis_type"], "")
    return (
        f"Analiz türü: {payload['test_name_tr']}\n\n"
        f"Kullanman gereken cümle şablonu:\n{template}\n\n"
        f"Hesaplanmış sonuçlar (JSON):\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"Bu sonuçları yukarıdaki şablona göre Türkçe, APA 7 stilinde tek bir "
        f"paragraf hâlinde yorumla. Şablondaki değişkenleri JSON'daki değerlerle "
        f"doldur. JSON'da olmayan hiçbir sayıyı kullanma."
    )


def generate_interpretation(payload: dict[str, Any]) -> LLMResponse:
    """Ask Claude to phrase the interpretation. Never raises — returns an
    `LLMResponse` with `used_llm=False` when the call cannot be made."""
    if not settings.anthropic_api_key:
        return LLMResponse(text="", model="", used_llm=False,
                           error="ANTHROPIC_API_KEY yapılandırılmamış")

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            temperature=0,  # phrasing should be reproducible for a given result
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_prompt(payload)}],
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        ).strip()
        return LLMResponse(text=text, model=settings.anthropic_model, used_llm=True)
    except Exception as exc:  # noqa: BLE001 — the LLM is optional by design
        logger.warning("Claude interpretation call failed: %s", exc)
        return LLMResponse(text="", model=settings.anthropic_model,
                           used_llm=False, error=str(exc))

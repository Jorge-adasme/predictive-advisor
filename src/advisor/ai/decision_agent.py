from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from advisor.config import Settings, get_settings


@dataclass
class AIDecision:
    ticker: str
    action: str  # buy | hold | avoid
    conviction: float  # 0..1
    summary: str
    rationale: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    approve_trade: bool = False
    provider: str = "local"
    model: str = "committee-v1"
    as_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DecisionAgent:
    """Capa de IA que decide encima del motor cuantitativo.

    Arquitectura:
      cuant (score/news/earnings/risk) → contexto → IA → decisión + gate autopilot

    Providers:
      - local: comité heurístico explicable (siempre disponible)
      - openai: GPT vía API (ADVISOR_AI_API_KEY)
      - anthropic: Claude vía API
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.settings, "ai_enabled", True))

    @property
    def provider(self) -> str:
        return str(getattr(self.settings, "ai_provider", "local") or "local").lower()

    def decide_many(
        self,
        *,
        market: dict[str, Any],
        news: dict[str, Any] | None,
        items: list[dict[str, Any]],
        max_items: int = 12,
    ) -> list[AIDecision]:
        out: list[AIDecision] = []
        for item in items[:max_items]:
            out.append(self.decide(market=market, news=news, item=item))
        return out

    def decide(
        self,
        *,
        market: dict[str, Any],
        news: dict[str, Any] | None,
        item: dict[str, Any],
    ) -> AIDecision:
        if not self.enabled:
            pred = item.get("prediction") or {}
            plan = item.get("plan") or {}
            return AIDecision(
                ticker=str(pred.get("ticker") or ""),
                action=str(plan.get("action") or "hold"),
                conviction=0.5,
                summary="IA desactivada: se usa solo el plan cuantitativo.",
                approve_trade=str(plan.get("action")) == "buy",
                provider="off",
                model="none",
                as_of=datetime.now(timezone.utc).isoformat(),
            )

        provider = self.provider
        if provider in {"openai", "anthropic"} and getattr(self.settings, "ai_api_key", ""):
            try:
                return self._decide_llm(provider=provider, market=market, news=news, item=item)
            except Exception as exc:
                local = self._decide_local(market=market, news=news, item=item)
                local.rationale = [f"Fallback local tras error LLM: {exc}"] + list(local.rationale)
                return local
        return self._decide_local(market=market, news=news, item=item)

    def _context_blob(
        self,
        market: dict[str, Any],
        news: dict[str, Any] | None,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        pred = item.get("prediction") or {}
        plan = item.get("plan") or {}
        factors = pred.get("factors") or {}
        news = news or {}
        ticker = pred.get("ticker")
        story = next(
            (s for s in (news.get("ticker_stories") or []) if s.get("ticker") == ticker),
            None,
        )
        return {
            "market": {
                "regime": market.get("regime"),
                "regime_score": market.get("regime_score"),
                "ret_20d": market.get("benchmark_return_20d"),
                "vol_20d": market.get("benchmark_volatility_20d"),
                "news_sentiment": market.get("news_sentiment", news.get("market_sentiment")),
                "news_urgency": market.get("news_urgency", news.get("market_urgency")),
            },
            "ticker": ticker,
            "name": pred.get("name"),
            "sector": pred.get("sector"),
            "quant": {
                "score": pred.get("score"),
                "probability_up": pred.get("probability_up"),
                "expected_return": pred.get("expected_return"),
                "confidence": pred.get("confidence"),
                "news_factor": factors.get("news_factor"),
                "meta_label_prob": factors.get("meta_label_prob"),
                "ic_spearman": factors.get("ic_spearman"),
                "ir_proxy": factors.get("ir_proxy"),
                "earnings_blackout": factors.get("earnings_blackout"),
                "days_to_earnings": factors.get("days_to_earnings"),
            },
            "plan": {
                "action": plan.get("action"),
                "edge_net_pct": plan.get("edge_net_pct"),
                "position_pct": plan.get("position_pct"),
                "stop_pct": plan.get("stop_pct"),
                "invalidation": plan.get("invalidation"),
            },
            "reasons": pred.get("reasons") or [],
            "risks": pred.get("risks") or [],
            "ticker_story": story,
            "top_headlines": (news.get("headlines") or [])[:5],
        }

    def _decide_local(
        self,
        *,
        market: dict[str, Any],
        news: dict[str, Any] | None,
        item: dict[str, Any],
    ) -> AIDecision:
        """Comité local: sintetiza cuant + noticias en una decisión explícita."""
        ctx = self._context_blob(market, news, item)
        q = ctx["quant"]
        plan = ctx["plan"]
        regime = str((ctx["market"] or {}).get("regime") or "neutral")
        score = float(q.get("score") or 0)
        edge = float(plan.get("edge_net_pct") or 0)
        prob = float(q.get("probability_up") or 0)
        news_f = float(q.get("news_factor") or 0)
        meta = float(q.get("meta_label_prob") or 0)
        earn_bo = float(q.get("earnings_blackout") or 0) >= 1
        story = ctx.get("ticker_story") or {}
        gov = bool(story.get("governance"))

        points = 0.0
        rationale: list[str] = []
        risks: list[str] = []

        if edge > 0.004:
            points += 1.2
            rationale.append(f"Edge neto atractivo ({edge:.2%}).")
        elif edge > 0:
            points += 0.5
            rationale.append(f"Edge neto leve ({edge:.2%}).")
        else:
            points -= 1.2
            risks.append(f"Sin edge neto ({edge:.2%}).")

        if score >= 0.35:
            points += 1.0
            rationale.append(f"Score cuant sólido ({score:.2f}).")
        elif score >= 0.15:
            points += 0.4
        else:
            points -= 0.8
            risks.append(f"Score débil ({score:.2f}).")

        if prob >= 0.55:
            points += 0.7
            rationale.append(f"Probabilidad alcista {prob:.0%}.")
        elif prob < 0.48:
            points -= 0.7
            risks.append(f"Probabilidad alcista baja ({prob:.0%}).")

        if news_f <= -0.35 or gov:
            points -= 1.3
            risks.append(
                "Noticias adversas"
                + (" / riesgo de gobernanza" if gov else "")
                + f" (news={news_f:+.2f})."
            )
            if story.get("headline"):
                risks.append(f"Titular clave: {story['headline'][:100]}")
        elif news_f >= 0.35:
            points += 0.6
            rationale.append(f"Noticias favorables ({news_f:+.2f}).")

        if regime == "risk_off":
            points -= 0.6
            risks.append("Régimen risk_off: priorizar capital.")
        elif regime == "risk_on":
            points += 0.35
            rationale.append("Régimen risk_on favorece momentum.")

        if earn_bo:
            points -= 1.5
            risks.append("Blackout de earnings.")

        if 0 < meta < 0.5:
            points -= 0.4
            risks.append(f"Meta-label flojo ({meta:.0%}).")
        elif meta >= 0.58:
            points += 0.4
            rationale.append(f"Meta-label OK ({meta:.0%}).")

        # Decisión
        if points >= 1.6 and edge > 0 and not earn_bo and not (gov and news_f < -0.2):
            action = "buy"
            approve = True
            summary = "La IA aprueba comprar: edge + score alineados y sin vetos duros."
        elif points <= -0.8 or earn_bo or (gov and news_f <= -0.25):
            action = "avoid"
            approve = False
            summary = "La IA recomienda NO invertir: riesgos/noticias dominan al edge."
        else:
            action = "hold"
            approve = False
            summary = "La IA sugiere vigilar: hay señal, pero no convicción suficiente para ejecutar."

        conviction = float(max(0.15, min(0.92, 0.45 + points / 8.0)))
        if action == "avoid":
            conviction = float(max(conviction, 0.55))

        return AIDecision(
            ticker=str(ctx["ticker"]),
            action=action,
            conviction=round(conviction, 3),
            summary=summary,
            rationale=rationale or ["Señal mixta del comité local."],
            risks=risks or ["Riesgo de mercado residual."],
            approve_trade=approve,
            provider="local",
            model="committee-v1",
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    def _decide_llm(
        self,
        *,
        provider: str,
        market: dict[str, Any],
        news: dict[str, Any] | None,
        item: dict[str, Any],
    ) -> AIDecision:
        ctx = self._context_blob(market, news, item)
        system = (
            "Eres un gestor de portafolio cuantitativo-discrecional. "
            "Debes decidir buy, hold o avoid para UNA acción. "
            "Prioriza expectancy neta tras costos, noticias recientes (14d) y event risk. "
            "Responde SOLO JSON válido con keys: "
            "action, conviction, summary, rationale (array), risks (array), approve_trade (bool)."
        )
        user = (
            "Contexto de decisión:\n"
            + json.dumps(ctx, ensure_ascii=False, default=str)
            + "\n\nReglas: avoid si earnings blackout o escándalo grave; "
            "buy solo con edge neto>0 y sin vetos; hold si dudoso."
        )
        model = str(getattr(self.settings, "ai_model", "") or "")
        raw = ""
        if provider == "openai":
            model = model or "gpt-4o-mini"
            raw = self._call_openai(system=system, user=user, model=model)
        else:
            model = model or "claude-3-5-haiku-latest"
            raw = self._call_anthropic(system=system, user=user, model=model)

        parsed = self._parse_llm_json(raw)
        action = str(parsed.get("action") or "hold").lower()
        if action not in {"buy", "hold", "avoid"}:
            action = "hold"
        conviction = float(parsed.get("conviction") or 0.5)
        conviction = max(0.05, min(0.95, conviction))
        approve = bool(parsed.get("approve_trade"))
        if action != "buy":
            approve = False

        return AIDecision(
            ticker=str(ctx["ticker"]),
            action=action,
            conviction=round(conviction, 3),
            summary=str(parsed.get("summary") or "Decisión LLM."),
            rationale=[str(x) for x in (parsed.get("rationale") or [])][:6],
            risks=[str(x) for x in (parsed.get("risks") or [])][:6],
            approve_trade=approve,
            provider=provider,
            model=model,
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    def _call_openai(self, *, system: str, user: str, model: str) -> str:
        key = self.settings.ai_api_key
        base = str(getattr(self.settings, "ai_base_url", "") or "https://api.openai.com/v1")
        payload = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _call_anthropic(self, *, system: str, user: str, model: str) -> str:
        key = self.settings.ai_api_key
        payload = {
            "model": model,
            "max_tokens": 700,
            "temperature": 0.2,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        parts = data.get("content") or []
        texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
        return "\n".join(texts)

    @staticmethod
    def _parse_llm_json(raw: str) -> dict[str, Any]:
        raw = (raw or "").strip()
        try:
            return json.loads(raw)
        except Exception:
            match = re.search(r"\{.*\}", raw, flags=re.S)
            if not match:
                return {}
            try:
                return json.loads(match.group(0))
            except Exception:
                return {}

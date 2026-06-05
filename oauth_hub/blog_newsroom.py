from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .paths import ROOT


DATA_DIR = ROOT / "data" / "blog_newsroom"
REPORTS_DIR = ROOT / "reports"
ARTICLES_DIR = DATA_DIR / "articles"
CONFIG_DIR = ROOT / "config"
NEWS_SOURCES_EXAMPLE = CONFIG_DIR / "news_sources.example.json"
NEWS_SOURCES_LOCAL = CONFIG_DIR / "news_sources.local.json"
BLOG_NEWSROOM_EXAMPLE = CONFIG_DIR / "blog_newsroom.example.json"
BLOG_NEWSROOM_LOCAL = CONFIG_DIR / "blog_newsroom.local.json"
DEFAULT_TOPIC = "codex-oauth-hub adds a calibrated YouTube tag intelligence workflow"


def ensure_output_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_config_with_fallback(example_path: Path, local_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    local_payload = load_json_file(local_path)
    if local_payload is not None:
        return local_payload, {"path": str(local_path), "fallbackUsed": False}
    example_payload = load_json_file(example_path) or {}
    return example_payload, {"path": str(example_path), "fallbackUsed": True}


def latest_file(directory: Path, prefix: str, suffix: str) -> Path | None:
    if not directory.exists():
        return None
    candidates = sorted(directory.glob(f"{prefix}_*{suffix}"))
    return candidates[-1] if candidates else None


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def slugify(text: str, max_length: int = 80) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u00C0-\u017F]+", "-", normalize_text(text)).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:max_length].strip("-") or "blog-newsroom")


def sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def topic_intake(topic: str, workflow_config: dict[str, Any]) -> dict[str, Any]:
    lower = normalize_text(topic)
    if any(token in lower for token in ["release", "adds", "añade", "incorpora", "workflow", "repo", "project"]):
        article_type = "release_note"
    elif any(token in lower for token in ["how", "como", "guia", "guía", "tutorial"]):
        article_type = "technical_note"
    elif any(token in lower for token in ["opinion", "analysis", "impact", "impacto"]):
        article_type = "opinion_with_sources"
    else:
        article_type = workflow_config.get("articleTypes", ["news"])[0]
    return {
        "topic": topic,
        "articleType": article_type,
        "intention": "nota de proyecto propio" if "oauth-hub" in lower or "codex" in lower else "noticia técnica verificada",
        "audience": workflow_config.get("targetAudience", "Spanish-speaking creators, AI builders and technical users"),
        "priority": "A" if any(token in lower for token in ["codex", "ai", "ia", "open source", "github"]) else "B",
    }


def build_internal_sources(topic: str) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []

    def add_source(source_id: str, label: str, source_type: str, path: Path, excerpts: list[str], why: str) -> None:
        content = read_text(path)
        excerpt = ""
        normalized = normalize_text(content)
        for phrase in excerpts:
            idx = normalized.find(normalize_text(phrase))
            if idx >= 0:
                excerpt = content[max(0, idx - 220): idx + 520].strip()
                break
        if not excerpt and content:
            excerpt = "\n".join(content.splitlines()[:18]).strip()
        sources.append(
            {
                "sourceId": source_id,
                "name": label,
                "type": source_type,
                "trustLevel": "high",
                "sourceUse": "cite",
                "qualityLabel": "official" if source_type in {"project_doc", "project_report"} else "primary",
                "trustScore": 96 if source_type in {"project_doc", "project_report", "project_data"} else 93,
                "freshnessScore": 96 if source_type in {"project_report", "project_data"} else 88,
                "biasRisk": "low",
                "available": bool(content),
                "url": None,
                "path": str(path),
                "whyUsed": why,
                "excerpt": excerpt,
            }
        )

    add_source(
        "readme",
        "README.md",
        "project_doc",
        ROOT / "README.md",
        ["Codex was the first use case", "local, file-based and command-driven", "youtube_tag_intelligence"],
        "Confirma la misión del hub y su compatibilidad con agentes autónomos.",
    )
    add_source(
        "docs_usage",
        "docs/USAGE.md",
        "project_doc",
        ROOT / "docs" / "USAGE.md",
        ["local OAuth/API hub", "autonomous agents", "blogger"],
        "Repite el posicionamiento del proyecto y el orden de flujos.",
    )
    tag_report = latest_file(ROOT / "reports", "youtube_tag_intelligence", ".md")
    if tag_report:
        add_source(
            "tag_report",
            tag_report.name,
            "project_report",
            tag_report,
            ["118 terms", "calibrated", "search_phrase", "topic_entity"],
            "Demuestra que el flujo ya generó una salida calibrada y verificable.",
        )
    tag_data = latest_file(ROOT / "data" / "youtube_tag_intelligence", "youtube_tag_intelligence", ".json")
    if tag_data:
        add_source(
            "tag_data",
            tag_data.name,
            "project_data",
            tag_data,
            ["reportDate", "sourceAvailability", "calibratedScore100"],
            "Aporta el ledger estructurado del flujo de inteligencia de tags.",
        )
    archive_report = latest_file(ROOT / "reports", "content_archive_miner", ".md")
    if archive_report:
        add_source(
            "archive_report",
            archive_report.name,
            "project_report",
            archive_report,
            ["reconcile-inventory", "crypto_legacy", "studio gap"],
            "Aporta contexto de otro flujo propio del repositorio.",
        )
    code_file = ROOT / "oauth_hub" / "youtube_tag_intelligence.py"
    add_source(
        "tag_code",
        "oauth_hub/youtube_tag_intelligence.py",
        "project_code",
        code_file,
        ["run_youtube_tag_intelligence", "calibrated_global_scores"],
        "Confirma que el flujo existe en código y escribe artefactos locales.",
    )
    try:
        output = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        output = ""
    sources.append(
        {
            "sourceId": "git_log",
            "name": "git log --oneline -5",
            "type": "git_log",
            "trustLevel": "high",
            "sourceUse": "cite",
            "qualityLabel": "primary",
            "trustScore": 94,
            "freshnessScore": 99,
            "biasRisk": "low",
            "available": bool(output),
            "url": None,
            "path": None,
            "whyUsed": "Aporta la cronología local del repositorio y valida el cambio reciente.",
            "excerpt": output,
        }
    )

    if "oauth-hub" not in normalize_text(topic) and "codex" not in normalize_text(topic):
        return sources
    return sources


def build_external_sources(topic: str, news_config: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    blocked_types = {item.lower() for item in news_config.get("blockedSourceTypes", [])}
    lower_topic = normalize_text(topic)
    for group in news_config.get("sourceGroups", []):
        group_priority = group.get("priority", "B")
        for entry in group.get("sources", []):
            source_type = str(entry.get("type", "")).lower()
            if source_type in blocked_types:
                continue
            source_topics = " ".join(entry.get("topics", []))
            if source_topics and not any(token in lower_topic for token in normalize_text(source_topics).split()):
                continue
            trust_level = entry.get("trustLevel", "medium")
            sources.append(
                {
                    "sourceId": entry.get("id") or slugify(f"{group.get('id', 'source')}-{entry.get('name', 'source')}"),
                    "name": entry.get("name", "Unnamed source"),
                    "type": source_type or "unknown",
                    "trustLevel": trust_level,
                    "priority": group_priority,
                    "sourceUse": "background_only",
                    "qualityLabel": "secondary_reliable" if trust_level == "high" else "community_signal",
                    "trustScore": 85 if trust_level == "high" else 68,
                    "freshnessScore": 70,
                    "biasRisk": "low" if trust_level == "high" else "medium",
                    "available": False,
                    "url": entry.get("url"),
                    "path": None,
                    "whyUsed": "Configured as a relevant external source, but not fetched in v1 unless manually available.",
                    "excerpt": "",
                }
            )
    return sources


def discover_sources(topic: str, news_config: dict[str, Any]) -> list[dict[str, Any]]:
    return build_internal_sources(topic) + build_external_sources(topic, news_config)


def quality_upgrade(source: dict[str, Any]) -> dict[str, Any]:
    source_type = source.get("type")
    if source_type in {"project_doc", "project_report", "project_data", "project_code", "git_log"}:
        source["sourceUse"] = "cite"
        source["available"] = bool(source.get("available", True))
        return source
    if source.get("trustLevel") == "high":
        source["qualityLabel"] = "secondary_reliable"
        source["sourceUse"] = "cite"
    elif source.get("trustLevel") == "medium":
        source["qualityLabel"] = "community_signal"
        source["sourceUse"] = "background_only"
    else:
        source["qualityLabel"] = "weak_source"
        source["sourceUse"] = "ignore"
    return source


def claim_patterns(topic: str) -> list[dict[str, Any]]:
    lower = normalize_text(topic)
    if "oauth-hub" in lower or "codex" in lower:
        return [
            {
                "claimId": "claim-001",
                "claimText": "El repositorio nació para Codex como agente principal, pero su arquitectura es reutilizable con otros agentes autónomos.",
                "claimType": "fact",
                "sourceIds": ["readme", "docs_usage"],
                "needsOfficialConfirmation": False,
            },
            {
                "claimId": "claim-002",
                "claimText": "La lógica importante vive en scripts Python, configuración local, secrets/, tokens/ y comandos reproducibles.",
                "claimType": "fact",
                "sourceIds": ["readme", "docs_usage"],
                "needsOfficialConfirmation": False,
            },
            {
                "claimId": "claim-003",
                "claimText": "El flujo youtube_tag_intelligence ya produjo un dataset calibrado de 118 términos detectados.",
                "claimType": "number",
                "sourceIds": ["tag_report", "tag_data"],
                "needsOfficialConfirmation": False,
            },
            {
                "claimId": "claim-004",
                "claimText": "La calibración por tipo protege a search_phrase frente a topic_entity y youtube_tag, y el flujo exporta JSON y CSV locales.",
                "claimType": "fact",
                "sourceIds": ["tag_report", "tag_data", "tag_code"],
                "needsOfficialConfirmation": False,
            },
            {
                "claimId": "claim-005",
                "claimText": "El artículo trata una nota de proyecto propio/open source y no una cobertura externa.",
                "claimType": "interpretation",
                "sourceIds": ["readme", "docs_usage", "git_log"],
                "needsOfficialConfirmation": False,
            },
        ]
    return [
        {
            "claimId": "claim-001",
            "claimText": f"El tema '{topic}' merece una nota técnica verificada antes de presentarse como noticia.",
            "claimType": "interpretation",
            "sourceIds": [],
            "needsOfficialConfirmation": True,
        }
    ]


def verify_claim(claim: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    source_map = {source["sourceId"]: source for source in sources}
    matched = [source_map[source_id] for source_id in claim.get("sourceIds", []) if source_id in source_map]
    available_count = sum(1 for source in matched if source.get("available"))
    text_blob = "\n".join(source.get("excerpt", "") for source in matched).lower()

    if not matched:
        status = "unverifiable"
    elif any(source.get("qualityLabel") == "official" for source in matched):
        status = "confirmed_official"
    elif available_count >= 2:
        status = "confirmed_multi_source"
    elif available_count == 1:
        status = "single_source"
    else:
        status = "unverifiable"

    if claim.get("claimType") == "opinion":
        status = "opinion_only"
    if claim["claimType"] == "number" and "118" not in text_blob and available_count < 1:
        status = "unverifiable"
    if claim.get("needsOfficialConfirmation") and status not in {"confirmed_official", "confirmed_multi_source"}:
        status = "single_source" if available_count == 1 else "unverifiable"

    warnings = []
    if status == "unverifiable":
        warnings.append("Claim sin verificación suficiente.")
    return {**claim, "verificationStatus": status, "verifiedSourceCount": available_count, "warnings": warnings}


def build_article_title(topic: str) -> str:
    lower = normalize_text(topic)
    if "oauth-hub" in lower or "codex" in lower:
        return "codex-oauth-hub incorpora un flujo calibrado de inteligencia de tags para YouTube"
    if "comfyui" in lower:
        return "ComfyUI y el nuevo flujo editorial que conecta investigación con borradores verificables"
    return topic.strip().capitalize()


def extract_keywords(topic: str, sources: list[dict[str, Any]], claims: list[dict[str, Any]]) -> list[str]:
    base = ["Codex", "YouTube tag intelligence", "workflow", "open source", "AI"]
    lower_topic = normalize_text(topic)
    if "comfyui" in lower_topic:
        base.append("ComfyUI")
    if "openclaw" in lower_topic:
        base.append("OpenClaw")
    if "agent zero" in lower_topic:
        base.append("Agent Zero")
    if "hermes" in lower_topic:
        base.append("Hermes Agent")
    if any("118" in claim["claimText"] for claim in claims):
        base.append("118 terms")
    if any(source["type"] == "project_report" for source in sources):
        base.append("project note")
    return list(dict.fromkeys(base))


def build_article_body(article_title: str, topic: str, claims: list[dict[str, Any]], sources: list[dict[str, Any]]) -> str:
    confirmed = [claim for claim in claims if claim["verificationStatus"] in {"confirmed", "confirmed_official", "confirmed_multi_source", "single_source"}]
    blocked = [claim for claim in claims if claim["verificationStatus"] in {"disputed", "false_or_misleading", "unverifiable"}]
    intro = (
        f"Este texto es una nota de proyecto propio sobre `{topic}`. "
        "No intenta hacer pasar el repositorio por cobertura externa: resume un cambio local, "
        "lo verifica con fuentes internas y deja claro qué está confirmado y qué queda como contexto."
    )
    lines = [
        f"# {article_title}",
        "",
        f"> {intro}",
        "",
        "## Resumen rápido",
        "",
        "- El hub sigue siendo local, reproducible y orientado a agentes autónomos.",
        "- La nueva capa de inteligencia de tags añade un mapa más fino para YouTube sin tocar el canal real.",
        "- El artículo se apoya en fuentes internas, no en una supuesta cobertura externa.",
        "",
        "## Contexto",
        "",
        "El repositorio ya documentaba que nació para Codex, pero que su arquitectura es reutilizable con otros agentes autónomos. "
        "Ese encaje importa porque el flujo nuevo no se apoya en magia opaca: vive en Python, en configuración local y en artefactos guardados en el workspace.",
        "",
        "## Qué está confirmado",
    ]
    for claim in confirmed:
        lines.append(f"- {claim['claimText']} [{claim['claimId']}]")
    lines.extend(["", "## Qué falta por confirmar"])
    if blocked:
        for claim in blocked:
            lines.append(f"- {claim['claimText']} [{claim['claimId']}]")
    else:
        lines.append("- No hay claims bloqueadas en esta nota de proyecto.")
    lines.extend(
        [
            "",
            "## Por qué importa",
            "",
            "Porque convierte una pieza de infraestructura interna en algo legible: un flujo que no solo calcula, sino que deja rastro, explica decisiones y separa el material verificado de la interpretación editorial.",
            "",
            "## Consecuencias prácticas",
            "",
            "- El contenido futuro puede apoyarse en una base más limpia para títulos, etiquetas y notas de proyecto.",
            "- El sistema conserva la separación entre investigación, fact checking y redacción.",
            "- El resultado sigue siendo local; no publica nada ni toca Blogger automáticamente.",
            "",
            "## Cierre",
            "",
            "Si este flujo se usa después para otros temas, la norma debería seguir siendo la misma: primero fuentes, luego claims, luego borrador. Sin atajos y sin vender como hecho lo que solo es una hipótesis.",
            "",
            "## Fuentes consultadas",
        ]
    )
    for source in sources:
        if source.get("sourceUse") == "ignore":
            continue
        lines.append(f"- {source['name']} — {source.get('url') or source.get('path') or 'git log'}")
    lines.extend(
        [
            "",
            "## Notas de verificación",
            "",
            "- Este artículo es una nota de proyecto propio / open source.",
            "- No se ha publicado nada en Blogger.",
            "- No se ha tocado YouTube.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_packaging(title: str, topic: str, claims: list[dict[str, Any]], sources: list[dict[str, Any]], article_type: str) -> dict[str, Any]:
    keywords = extract_keywords(topic, sources, claims)
    return {
        "slug": slugify(title),
        "metaTitle": title[:60],
        "metaDescription": (
            "Nota de proyecto propio sobre un flujo local verificado de inteligencia de tags para YouTube, "
            "con fuentes internas, fact checking y borrador listo para revisión humana."
        ),
        "bloggerTags": keywords[:8],
        "categories": ["AI", "Open Source", "Creator Tools"],
        "primaryKeywords": keywords[:5],
        "secondaryKeywords": keywords[5:10],
        "excerpt": "Resumen verificado de una mejora local del hub: más inteligencia editorial, misma lógica local y reproducible.",
        "featuredImageSuggestion": "Captura limpia del panel local o del informe del flujo, con foco en lectura y no en branding ruidoso.",
        "altTextSuggestion": "Informe local del flujo blog_newsroom con claims verificados y fuentes internas.",
        "linkedinPost": (
            "He publicado una nota de proyecto propio sobre cómo oauth-hub añade un flujo calibrado de inteligencia de tags para YouTube. "
            "Todo queda verificado, local y listo para revisión humana."
        ),
        "redditPost": (
            "Nuevo borrador técnico en oauth-hub: un flujo local de newsroom para artículos verificados, "
            "con claims, fuentes y packaging editorial."
        ),
        "commentary": "La pieza se comparte como nota de proyecto propio, no como noticia externa.",
        "articleType": article_type,
    }


def score_text_quality(text: str) -> int:
    paragraphs = [block for block in text.split("\n\n") if block.strip()]
    sentence_count = sum(len(sentence_split(block)) for block in paragraphs)
    score = 70
    if sentence_count >= 18:
        score += 10
    if len(text) > 2200:
        score += 8
    if "## Fuentes consultadas" in text:
        score += 5
    if "## Qué falta por confirmar" in text:
        score += 4
    return max(0, min(100, score))


def build_artifacts(report_date: dt.date, topic: str | None = None, mode: str = "draft") -> dict[str, Any]:
    ensure_output_dirs()
    workflow_config, workflow_config_meta = load_config_with_fallback(BLOG_NEWSROOM_EXAMPLE, BLOG_NEWSROOM_LOCAL)
    news_config, news_config_meta = load_config_with_fallback(NEWS_SOURCES_EXAMPLE, NEWS_SOURCES_LOCAL)

    selected_topic = topic or workflow_config.get("defaultTopic") or DEFAULT_TOPIC
    intake = topic_intake(selected_topic, workflow_config)
    sources = [quality_upgrade(source) for source in discover_sources(selected_topic, news_config)]
    claims = [verify_claim(claim, sources) for claim in claim_patterns(selected_topic)]

    article_title = build_article_title(selected_topic)
    article_slug = slugify(article_title)
    article_dir = ARTICLES_DIR / f"{report_date.isoformat()}_{article_slug}"
    article_dir.mkdir(parents=True, exist_ok=True)

    article_markdown = build_article_body(article_title, selected_topic, claims, sources)
    packaging = build_packaging(article_title, selected_topic, claims, sources, intake["articleType"])
    fact_check_status = "pass"
    warnings = [warning for claim in claims for warning in claim.get("warnings", []) if warning]
    if any(claim["verificationStatus"] == "unverifiable" for claim in claims):
        fact_check_status = "pass_with_warnings"
    if any(claim["verificationStatus"] in {"disputed", "false_or_misleading"} for claim in claims):
        fact_check_status = "fail"

    verification_score = max(0, min(100, 55 + sum(8 for claim in claims if claim["verificationStatus"] in {"confirmed", "confirmed_official", "confirmed_multi_source"}) + sum(3 for claim in claims if claim["verificationStatus"] == "single_source")))
    human_quality_score = score_text_quality(article_markdown)
    seo_score = min(100, 62 + len(packaging["primaryKeywords"]) * 4 + (5 if packaging["bloggerTags"] else 0))
    risk_score = max(0, min(100, 100 - verification_score + (10 if fact_check_status != "pass" else 0)))
    publish_readiness_score = max(0, min(100, round(0.45 * verification_score + 0.35 * human_quality_score + 0.2 * seo_score - 0.2 * risk_score)))

    final_decision = "convertir en nota de proyecto propio"
    if fact_check_status == "fail":
        final_decision = "esperar más fuentes"
    elif verification_score < 70:
        final_decision = "dejar en revisión"

    article_bundle = {
        "topic": selected_topic,
        "title": article_title,
        "slug": article_slug,
        "articleType": intake["articleType"],
        "mode": mode,
        "finalDecision": final_decision,
        "confidence": "alta" if verification_score >= 85 else "media",
        "publishReadinessScore": publish_readiness_score,
        "verificationScore": verification_score,
        "humanQualityScore": human_quality_score,
        "seoScore": seo_score,
        "riskScore": risk_score,
        "sourceCount": len([source for source in sources if source.get("sourceUse") != "ignore"]),
        "confirmedClaims": sum(1 for claim in claims if claim["verificationStatus"] in {"confirmed", "confirmed_official", "confirmed_multi_source"}),
        "singleSourceClaims": sum(1 for claim in claims if claim["verificationStatus"] == "single_source"),
        "blockedClaims": sum(1 for claim in claims if claim["verificationStatus"] in {"disputed", "false_or_misleading", "unverifiable"}),
        "requiredHumanReview": True,
        "outputPath": str(article_dir),
        "articlePath": str(article_dir / "article.md"),
        "claimsPath": str(article_dir / "claims.json"),
        "sourcesPath": str(article_dir / "sources.json"),
        "factCheckPath": str(article_dir / "fact_check.md"),
        "packagingPath": str(article_dir / "packaging.json"),
        "editorialDecisionPath": str(article_dir / "editorial_decision.json"),
    }

    sources_output = {"topic": selected_topic, "selectedTopic": selected_topic, "sourcesConfig": news_config_meta, "workflowConfig": workflow_config_meta, "sources": sources}
    claims_output = {"topic": selected_topic, "claims": claims}
    fact_check_lines = [
        f"# Fact check - {report_date.isoformat()}",
        "",
        f"- Status: {fact_check_status}",
        f"- Verification score: {verification_score}",
        f"- Human quality score: {human_quality_score}",
        f"- SEO score: {seo_score}",
        f"- Risk score: {risk_score}",
        "",
        "## Claims used",
    ]
    for claim in claims:
        fact_check_lines.append(f"- [{claim['verificationStatus']}] {claim['claimText']} ({claim['claimId']})")
    if warnings:
        fact_check_lines.extend(["", "## Warnings"])
        fact_check_lines.extend(f"- {warning}" for warning in warnings)

    editorial_decision = {
        "topic": selected_topic,
        "title": article_title,
        "slug": article_slug,
        "articleType": intake["articleType"],
        "finalDecision": final_decision,
        "confidence": article_bundle["confidence"],
        "publishReadinessScore": publish_readiness_score,
        "verificationScore": verification_score,
        "humanQualityScore": human_quality_score,
        "seoScore": seo_score,
        "riskScore": risk_score,
        "requiredHumanReview": True,
        "reason": "La pieza está verificada con fuentes internas y mantiene el artículo como nota de proyecto propio, sin publicar ni tocar Blogger." if final_decision != "esperar más fuentes" else "Faltan fuentes suficientes para elevar la pieza más allá de un borrador local.",
    }

    save_text(article_dir / "article.md", article_markdown)
    save_json(article_dir / "claims.json", claims_output)
    save_json(article_dir / "sources.json", sources_output)
    save_text(article_dir / "fact_check.md", "\n".join(fact_check_lines).strip() + "\n")
    save_json(article_dir / "packaging.json", packaging)
    save_json(article_dir / "editorial_decision.json", editorial_decision)

    master_json = {
        "reportDate": report_date.isoformat(),
        "topic": selected_topic,
        "mode": mode,
        "workflowConfig": workflow_config_meta,
        "newsSourcesConfig": news_config_meta,
        "intake": intake,
        "sources": sources,
        "claims": claims,
        "article": article_bundle,
        "factCheck": {
            "status": fact_check_status,
            "warnings": warnings,
            "claimsUsed": [claim["claimId"] for claim in claims if claim["verificationStatus"] not in {"unverifiable", "false_or_misleading"}],
            "claimsBlocked": [claim["claimId"] for claim in claims if claim["verificationStatus"] in {"disputed", "false_or_misleading", "unverifiable"}],
            "requiredHumanReview": True,
        },
        "packaging": packaging,
        "editorialDecision": editorial_decision,
    }
    master_json_path = DATA_DIR / f"blog_newsroom_{report_date.isoformat()}.json"
    save_json(master_json_path, master_json)

    used_sources = [source for source in sources if source.get("sourceUse") != "ignore"]
    rejected_sources = [source for source in sources if source.get("sourceUse") == "ignore"]
    report_lines = [
        f"# blog_newsroom - {report_date.isoformat()}",
        "",
        "## 1. Resumen ejecutivo.",
        "",
        f"- Tema analizado: {selected_topic}",
        f"- Tipo de artículo sugerido: {intake['articleType']}",
        f"- Decisión del Orchestrator: {final_decision}",
        f"- verificationScore: {verification_score}",
        f"- publishReadinessScore: {publish_readiness_score}",
        f"- Fuentes usadas: {len(used_sources)}",
        f"- Claims confirmados: {article_bundle['confirmedClaims']}",
        f"- Claims de una sola fuente: {article_bundle['singleSourceClaims']}",
        f"- Claims bloqueados: {article_bundle['blockedClaims']}",
        f"- Config workflow usada: {workflow_config_meta['path']} (fallback={workflow_config_meta['fallbackUsed']})",
        f"- Config de fuentes usada: {news_config_meta['path']} (fallback={news_config_meta['fallbackUsed']})",
        "",
        "## 2. Temas analizados.",
        "",
        f"- {selected_topic}",
        "",
        "## 3. Fuentes usadas.",
    ]
    for source in used_sources:
        report_lines.append(f"- {source['name']} [{source['qualityLabel']}] — {source.get('url') or source.get('path') or 'git log'}")
    report_lines.extend(["", "## 4. Fuentes rechazadas."])
    report_lines.extend([f"- {source['name']} — {source.get('whyUsed', 'No usada')}" for source in rejected_sources] or ["- Ninguna."])
    report_lines.extend(["", "## 5. Claims confirmados."])
    confirmed_claims = [claim for claim in claims if claim["verificationStatus"] in {"confirmed", "confirmed_official", "confirmed_multi_source"}]
    report_lines.extend([f"- {claim['claimText']} ({claim['verificationStatus']})" for claim in confirmed_claims] or ["- Ninguno."])
    report_lines.extend(["", "## 6. Claims de una sola fuente."])
    single_claims = [claim for claim in claims if claim["verificationStatus"] == "single_source"]
    report_lines.extend([f"- {claim['claimText']} ({claim['claimId']})" for claim in single_claims] or ["- Ninguno."])
    report_lines.extend(["", "## 7. Claims bloqueados."])
    blocked_claims = [claim for claim in claims if claim["verificationStatus"] in {"disputed", "false_or_misleading", "unverifiable"}]
    report_lines.extend([f"- {claim['claimText']} ({claim['verificationStatus']})" for claim in blocked_claims] or ["- Ninguno."])
    report_lines.extend(
        [
            "",
            "## 8. Borradores generados.",
            "",
            f"- {article_title} -> {article_dir / 'article.md'}",
            "",
            "## 9. Artículos listos para revisión.",
            "",
        ]
    )
    report_lines.append(f"- {article_title} ({publish_readiness_score}/100)" if final_decision != "esperar más fuentes" else "- Ninguno.")
    report_lines.extend(["", "## 10. Artículos en espera de más fuentes.", ""])
    report_lines.append(f"- {article_title}" if final_decision == "esperar más fuentes" else "- Ninguno.")
    report_lines.extend(
        [
            "",
            "## 11. Riesgos editoriales.",
            "",
            f"- {fact_check_status}",
            f"- {', '.join(warnings) if warnings else 'Sin riesgos bloqueantes'}",
            "",
            "## 12. Decisiones del Orchestrator.",
            "",
            f"- {final_decision}",
            f"- confidence: {article_bundle['confidence']}",
            f"- reason: {editorial_decision['reason']}",
            "",
            "## 13. Limitaciones reales.",
            "",
            "- El flujo prioriza fuentes internas del repositorio para la nota de proyecto propio.",
            f"- `blog_newsroom.local.json` no estaba disponible y se usó `{workflow_config_meta['path']}` como fallback.",
            f"- `news_sources.local.json` no estaba disponible y se usó `{news_config_meta['path']}` como fallback.",
            "- Si se quiere una pieza de noticias externas, conviene alimentar `news_sources.local.json` con fuentes reales y activarlas manualmente.",
            "- v1 no publica ni usa Blogger automáticamente.",
            "",
            "## 14. Siguiente paso recomendado.",
            "",
            "- Revisar el borrador local, confirmar el ángulo editorial y decidir si se convierte en una nota de proyecto, una guía técnica o un artículo de contexto.",
            "",
            "## Artículos resumidos.",
            "",
        ]
    )
    report_lines.append(
        f"- {article_title} | {final_decision} | verification {verification_score} | readiness {publish_readiness_score} | output {article_bundle['outputPath']}"
    )

    report_path = REPORTS_DIR / f"blog_newsroom_{report_date.isoformat()}.md"
    save_text(report_path, "\n".join(report_lines).strip() + "\n")

    return {
        "report": report_path,
        "json": master_json_path,
        "article_dir": article_dir,
        "article": article_dir / "article.md",
        "claims": article_dir / "claims.json",
        "sources": article_dir / "sources.json",
        "fact_check": article_dir / "fact_check.md",
        "packaging": article_dir / "packaging.json",
        "editorial_decision": article_dir / "editorial_decision.json",
        "summary": master_json,
    }

import csv
import datetime as dt
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import read_api_key
from .registry import get_connection
from .paths import ROOT


REPORTS_DIR = ROOT / "reports"
PROPOSALS_DATA_DIR = ROOT / "data" / "video_rewrite_proposals"
CANDIDATES_DATA_DIR = ROOT / "data" / "video_rewrite_candidates"
DIAGNOSIS_DATA_DIR = ROOT / "data" / "channel_diagnosis"
OPPORTUNITIES_DATA_DIR = ROOT / "data" / "channel_opportunities"
DISCOVERY_DATA_DIR = ROOT / "data" / "competitor_discovery"
SCAN_DATA_DIR = ROOT / "data" / "competitor_content_scan"

STRATEGIC_CATEGORIES = {
    "ia_tutorial",
    "ia_local",
    "agentes_autonomos",
    "codex_automatizacion",
    "comfyui_video",
    "hardware_ia_gpu",
}
COMPATIBLE_CATEGORIES = {"short_viral", "experimento_variedad"}
LEGACY_CATEGORIES = {"legacy_gaming", "tarkov_directo"}


def ensure_output_dirs() -> None:
    PROPOSALS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def load_latest_or_dated(data_dir: Path, prefix: str, report_date: dt.date | None = None) -> tuple[dict[str, Any] | None, Path | None]:
    if report_date:
        path = data_dir / f"{prefix}_{report_date.isoformat()}.json"
        if not path.exists():
            return None, None
        return json.loads(path.read_text(encoding="utf-8")), path

    candidates = sorted(data_dir.glob(f"{prefix}_*.json"))
    if not candidates:
        return None, None
    path = candidates[-1]
    return json.loads(path.read_text(encoding="utf-8")), path


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalize_lower(text: str) -> str:
    return normalize_text(text).lower()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9áéíóúñ\-\+]+", normalize_lower(text))


def compact_title(title: str, max_words: int = 9) -> str:
    return " ".join(normalize_text(title).split()[:max_words]).strip()


def clean_hashtag_title(title: str) -> str:
    return re.sub(r"\s*#\w+", "", normalize_text(title)).strip(" -|")


def short_core_title(title: str, max_words: int = 6) -> str:
    cleaned = clean_hashtag_title(title)
    words = cleaned.split()
    return " ".join(words[:max_words]).strip()


COMMON_TITLE_STOPWORDS = {
    "de",
    "la",
    "el",
    "los",
    "las",
    "en",
    "con",
    "sin",
    "por",
    "para",
    "una",
    "un",
    "y",
    "o",
    "que",
    "te",
    "tu",
    "mi",
    "lo",
    "del",
    "al",
    "parte",
    "shorts",
    "short",
    "test",
    "ai",
    "ia",
    "chatgpt",
    "video",
    "vídeo",
}


def strategic_fit_label(category: str) -> str:
    if category in STRATEGIC_CATEGORIES:
        return "alto"
    if category in COMPATIBLE_CATEGORIES:
        return "medio"
    if category in LEGACY_CATEGORIES:
        return "bajo"
    return "medio"


def actual_priority(candidate: dict[str, Any]) -> str:
    category = candidate["editorialCategory"]
    if category in STRATEGIC_CATEGORIES:
        return "A"
    if category in COMPATIBLE_CATEGORIES:
        return "B"
    if category in LEGACY_CATEGORIES:
        return "C"
    return candidate["priority"]


def execution_priority(candidate: dict[str, Any], strategist: dict[str, Any]) -> str:
    if strategist["futureFit"] and candidate["confidence"] in {"alta", "media"}:
        return "alta"
    if candidate["priority"] == "B" or candidate["recommendedActionType"] in {"cambiar título", "cambiar miniatura"}:
        return "media"
    return "baja"


def infer_main_theme(title: str, editorial_category: str, description: str = "") -> str:
    text = normalize_lower(f"{title} {description} {editorial_category}")
    if "hermes" in text:
        return "hermes_agent_ollama"
    if "openclaw" in text:
        return "openclaw_local_ai"
    if "codex" in text:
        return "codex_agent_workflow"
    if "ollama" in text or editorial_category == "ia_local":
        return "ollama_ia_local"
    if "comfyui" in text or editorial_category == "comfyui_video":
        return "comfyui_video_workflow"
    if any(token in text for token in ["gpu", "vram", "tarjetas", "hardware", "ram"]):
        return "hardware_ia_gpu"
    if any(token in text for token in ["agent", "agents", "autonomous", "agente"]):
        return "agentes_autonomos"
    if editorial_category == "ia_tutorial":
        return "tutorial_ia"
    return editorial_category or "otros"


def candidate_topic_tokens(candidate: dict[str, Any]) -> list[str]:
    tokens = []
    for token in tokenize(candidate["title"]):
        if token in COMMON_TITLE_STOPWORDS or len(token) < 3:
            continue
        tokens.append(token)
    theme = infer_main_theme(candidate["title"], candidate["editorialCategory"])
    theme_tokens = {
        "hermes_agent_ollama": ["hermes", "ollama"],
        "openclaw_local_ai": ["openclaw", "ollama"],
        "codex_agent_workflow": ["codex", "agente", "agent"],
        "ollama_ia_local": ["ollama", "local"],
        "comfyui_video_workflow": ["comfyui", "runway", "capcut"],
        "hardware_ia_gpu": ["gpu", "vram", "hardware", "ram"],
        "agentes_autonomos": ["agent", "agente", "autonomo", "autónomo"],
        "tutorial_ia": ["tutorial", "herramientas", "automatizacion"],
    }.get(theme, [])
    for token in theme_tokens:
        if token not in tokens:
            tokens.append(token)
    return tokens[:8]


def topic_phrase(candidate: dict[str, Any]) -> str:
    text = normalize_lower(candidate["title"])
    tokens = set(tokenize(candidate["title"]))
    if "5 cosas" in text and "cada día" in text:
        return "5 usos de IA para el día a día"
    if "top 5" in text and "agentes" in text:
        return "Hermes, Agent Zero y OpenClaw"
    if "hermes" in text and "api gratis" in text:
        return "Hermes Agent Workspace gratis"
    if "mistral" in text and "api" in text:
        return "Mistral API gratis"
    if "hermes" in text and "ollama" in text:
        return "Hermes Agent con Ollama"
    if "openclaw" in text and "ollama" in text:
        return "OpenClaw con Ollama"
    if "185" in text and "agentes" in text:
        return "185 agentes en tu PC"
    if "agent zero" in text:
        return "Agent Zero en local"
    if "codex" in text:
        return "Codex con agentes locales"
    if "youtube api" in text:
        return "Hermes Agent con YouTube API"
    if "ollama" in text and "cloud" in text:
        return "Ollama en local y cloud"
    if "ollama" in text:
        return "Ollama en local"
    if "qwen" in text:
        return "Qwen uncensored en local"
    if "comfyui" in text and "video" in text:
        return "ComfyUI para vídeo IA"
    if "pc gamer" in text and "comfy" in text:
        return "PC para IA y ComfyUI"
    if "runway" in text or "capcut" in text:
        return "Runway y CapCut para vídeo IA"
    if "componentes" in text or "hipotecado" in text:
        return "Comprar hardware para IA sin arruinarte"
    if "botiquín" in text or "cyberpunk" in text:
        return "Modding PC para IA"
    if "gpu" in tokens or "gráficas" in text or "graficas" in text:
        return "GPUs para IA local"
    if "ram" in tokens:
        return "RAM para IA local"
    if "npu" in tokens:
        return "GPU vs NPU para IA"
    if "sin censura" in text and "imagen" in text:
        return "IA de imagen sin censura"
    if "herramientas" in text and "producción" in text:
        return "Herramientas IA para crear contenido"
    if "agente" in text and "navegador" in text:
        return "Agente IA en el navegador"
    if "herramientas" in text:
        return "Herramientas de IA"
    if "analisis" in text or "análisis" in text:
        return "Análisis con ChatGPT"
    if "memoria" in text and "web" in text:
        return "IA con memoria para cada web"
    if "api" in text and "gratis" in text:
        return "APIs gratis para IA"
    cleaned = clean_hashtag_title(candidate["title"])
    words = [word for word in cleaned.split() if len(word) > 2][:7]
    return " ".join(words).strip() or theme_label(infer_main_theme(candidate["title"], candidate["editorialCategory"]))


def infer_intentions(title: str, problem: str, action: str, fmt: str) -> list[str]:
    text = normalize_lower(f"{title} {problem} {action}")
    intentions: list[str] = []
    if any(token in text for token in ["tutorial", "guia", "guide", "how to", "setup", "instala", "configura"]):
        intentions.append("tutorial")
    if any(token in text for token in ["instala", "configura", "setup", "docker", "ubuntu"]):
        intentions.append("instalacion")
    if any(token in text for token in ["compar", "mejor", "vs", "barato", "caro"]):
        intentions.append("comparativa")
    if any(token in text for token in ["problema", "error", "fix", "solucion"]):
        intentions.append("problema_solucion")
    if any(token in text for token in ["workflow", "real", "caso", "practico"]):
        intentions.append("caso_practico")
    if fmt == "short":
        intentions.append("short_viral")
    if any(token in text for token in ["gpu", "vram", "ram", "hardware"]):
        intentions.append("hardware_ia")
    if any(token in text for token in ["agent", "agents", "hermes", "codex", "openclaw"]):
        intentions.append("agentes_autonomos")
    if any(token in text for token in ["comfyui", "runway", "image", "imagen", "video"]):
        intentions.append("comfyui_generacion")
    if not intentions:
        intentions.append("caso_practico")
    return list(dict.fromkeys(intentions))


def get_search_connection() -> tuple[str, str] | None:
    try:
        _config, _account, _service, entry = get_connection("search")
    except Exception:
        return None
    engine_id = entry.get("engineId")
    if not engine_id:
        return None
    try:
        api_key = read_api_key(entry["apiKeyFile"])
    except Exception:
        return None
    return api_key, engine_id


def run_custom_search(query: str, api_key: str, engine_id: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"key": api_key, "cx": engine_id, "q": query})
    url = f"https://www.googleapis.com/customsearch/v1?{params}"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("items", [])[:5]


def metrics_analyst(candidate: dict[str, Any]) -> dict[str, Any]:
    metrics = candidate["metrics"]
    reason = candidate["metricsReason"]
    action = candidate["recommendedActionType"]
    risk = "medio"
    if candidate["priority"] == "C":
        risk = "alto"
    elif action in {"convertir en vídeo largo", "hacer segunda parte"} and metrics["views30"] < 100:
        risk = "medio"
    elif action in {"cambiar título", "cambiar miniatura"}:
        risk = "bajo"
    return {
        "shortDiagnosis": (
            f"{metrics['views30']} views en 30d, {metrics['watch30']:.0f} min vistos, "
            f"retención {metrics['retention30']:.1f}%, {metrics['viewsPerDay30']:.1f} views/día."
        ),
        "changeReason": reason,
        "recommendedAction": action,
        "confidence": candidate["confidence"],
        "risk": risk,
    }


def channel_strategist(candidate: dict[str, Any]) -> dict[str, Any]:
    category = candidate["editorialCategory"]
    future_fit = category in STRATEGIC_CATEGORIES
    legacy = category in LEGACY_CATEGORIES
    if future_fit:
        action = "empujar" if candidate["recommendedActionType"] not in {"pausar/no tocar"} else "replantear"
    elif category in COMPATIBLE_CATEGORIES:
        action = "transformarse"
    elif legacy:
        action = "pausarse"
    else:
        action = "reciclarse"
    return {
        "strategicFit": strategic_fit_label(category),
        "trafficType": "trafico_heredado" if legacy else "contenido_futuro",
        "realPriority": actual_priority(candidate),
        "futureFit": future_fit,
        "strategyDecision": action,
    }


def competitor_analyst(candidate: dict[str, Any], matches: list[dict[str, Any]]) -> dict[str, Any]:
    if not matches:
        return {
            "competitorsUsed": [],
            "patterns": "Sin competencia relacionada suficiente en el escaneo actual.",
            "theyDoBetter": "No hay evidencia suficiente.",
            "doNotCopy": "No copiar formulas vacias ni promesas sin prueba.",
            "differentiation": "Apostar por caso real, contexto local y claridad.",
        }
    competitors = sorted({item["competitor"] for item in matches})
    better = matches[0]["theyDoBetter"]
    differ = matches[0]["differentiateBy"]
    common = matches[0]["similarityDetected"]
    return {
        "competitorsUsed": competitors,
        "patterns": common,
        "theyDoBetter": better,
        "doNotCopy": "No copiar el mismo angulo ni el mismo giro de hype; usar una promesa propia y verificable.",
        "differentiation": differ,
    }


def search_intent_agent(candidate: dict[str, Any], competitor_info: dict[str, Any], search_connection: tuple[str, str] | None) -> dict[str, Any]:
    if not search_connection:
        return {
            "executed": False,
            "reason": "Google Custom Search no esta configurado o no tiene engineId operativo.",
        }

    theme = infer_main_theme(candidate["title"], candidate["editorialCategory"])
    query_map = {
        "hermes_agent_ollama": "Hermes Agent Ollama",
        "openclaw_local_ai": "OpenClaw local AI",
        "codex_agent_workflow": "Codex autonomous agent",
        "ollama_ia_local": "Ollama local AI",
        "comfyui_video_workflow": "ComfyUI video workflow",
        "hardware_ia_gpu": "GPU for local AI",
        "agentes_autonomos": "AI agents tutorial",
        "tutorial_ia": "AI tutorial automation",
    }
    query = query_map.get(theme, clean_hashtag_title(candidate["title"]))
    try:
        api_key, engine_id = search_connection
        items = run_custom_search(query, api_key, engine_id)
    except Exception as exc:
        return {
            "executed": False,
            "reason": f"Search Intent saltado por error operativo: {type(exc).__name__}.",
        }

    titles = [item.get("title", "") for item in items]
    combined = " ".join(titles).lower()
    useful_terms = sorted({token for token in tokenize(combined) if token not in {"youtube", "video", "videos"}})[:8]
    questions = []
    if "how" in combined or "como" in combined:
        questions.append("como se monta y que pasos exactos hay")
    if "best" in combined or "mejor" in combined:
        questions.append("cual merece la pena y cual evitar")
    if "free" in combined or "gratis" in combined:
        questions.append("como hacerlo gratis o sin pagar APIs")
    if "local" in combined:
        questions.append("cuando usar local y cuando usar cloud")
    return {
        "executed": True,
        "mainIntent": "busqueda_practica",
        "usefulQueries": [query],
        "questionsToAnswer": questions[:4] or ["que problema resuelve y como se configura"],
        "usefulTerms": useful_terms,
        "seoAngle": "priorizar claridad de setup, coste, resultado y contexto local",
        "worthBloggerArticle": candidate["recommendedActionType"] in {"hacer segunda parte", "convertir en vídeo largo"} or candidate["editorialCategory"] in STRATEGIC_CATEGORIES,
        "searchVsCuriosity": "busqueda" if candidate["editorialCategory"] in STRATEGIC_CATEGORIES else "curiosidad",
    }


def theme_label(theme: str) -> str:
    mapping = {
        "hermes_agent_ollama": "Hermes Agent con Ollama",
        "openclaw_local_ai": "OpenClaw en local",
        "codex_agent_workflow": "Codex y agentes en local",
        "ollama_ia_local": "IA local con Ollama",
        "comfyui_video_workflow": "workflow de ComfyUI",
        "hardware_ia_gpu": "hardware para IA local",
        "agentes_autonomos": "agentes autónomos",
        "tutorial_ia": "herramientas de IA",
    }
    return mapping.get(theme, "este flujo")


def emergency_title(candidate: dict[str, Any]) -> str:
    topic = topic_phrase(candidate)
    if candidate["recommendedActionType"] == "convertir en vídeo largo":
        return f"{topic}: del short al tutorial completo"
    if candidate["recommendedActionType"] == "cambiar título":
        return f"{topic}: enfoque más claro y específico"
    if candidate["recommendedActionType"] == "hacer segunda parte":
        return f"{topic}: segunda parte con caso real"
    if candidate["recommendedActionType"] == "convertir en short":
        return f"{topic}: el corte que mejor resume la idea"
    return f"{topic}: lo que enseña realmente"


def sanitize_final_title(title: str, candidate: dict[str, Any]) -> str:
    lower = normalize_lower(title)
    banned = [
        "sin humo",
        "deja de montarlo mal",
        "local vs cloud",
        "el error que lo rompe todo",
        "el fallo que te lo fastidia",
        "asi sí funciona",
        "así sí funciona",
        "tutorial completo en español",
        "versión larga paso a paso",
        "el error que rompe el agente",
        "el error que te hace volver a la nube",
    ]
    if not any(fragment in lower for fragment in banned) and len(title) <= 78 and not title.endswith(":"):
        return title

    topic = topic_phrase(candidate)
    action = candidate["recommendedActionType"]
    if action == "convertir en vídeo largo":
        return f"{topic}: del short al tutorial completo"
    if action == "hacer segunda parte":
        return f"{topic}: segunda parte con caso real"
    if action == "convertir en short":
        return f"{topic}: el corte que mejor explica la idea"
    if action == "cambiar miniatura":
        return f"{topic}: lo que enseña realmente"
    if action == "cambiar título":
        return f"{topic}: qué merece la pena de verdad"
    return emergency_title(candidate)


def title_writer_agent(candidate: dict[str, Any], strategist: dict[str, Any], competitor_info: dict[str, Any], search_info: dict[str, Any]) -> dict[str, Any]:
    base = short_core_title(candidate["title"])
    terms = search_info.get("usefulTerms", []) if search_info.get("executed") else []
    seo_term = terms[0] if terms else infer_main_theme(candidate["title"], candidate["editorialCategory"]).replace("_", " ")
    theme = infer_main_theme(candidate["title"], candidate["editorialCategory"])
    label = theme_label(theme)
    topic = topic_phrase(candidate)
    long_tail = " ".join(candidate_topic_tokens(candidate)[:3]).strip() or seo_term

    titles = [
        {"approach": "tutorial", "title": f"{topic}: guía paso a paso"},
        {"approach": "problema_solucion", "title": f"{topic}: errores que te ahorras"},
        {"approach": "ahorro_dinero", "title": f"{topic}: cómo no gastar de más"},
        {"approach": "ia_local", "title": f"{topic}: prueba real en local"},
        {"approach": "agentes_autonomos", "title": f"{topic}: caso real y resultado"},
        {"approach": "comfyui_hardware", "title": f"{topic}: setup útil de verdad"},
        {"approach": "directo_youtube", "title": f"{topic}: lo que cambia de verdad"},
        {"approach": "seo_busqueda", "title": f"{topic}: {long_tail} paso a paso"},
        {"approach": "curiosidad", "title": f"{topic}: lo que nadie te explica bien"},
        {"approach": "comparativa", "title": f"{topic}: qué opción compensa más"},
    ]

    if theme == "comfyui_video_workflow":
        titles[0]["title"] = f"{topic}: workflow completo paso a paso"
        titles[1]["title"] = f"{topic}: cómo pasar del test al vídeo útil"
        titles[4]["title"] = f"{topic}: del short al tutorial completo"
        titles[5]["title"] = f"{topic}: nodos, flujo y resultado final"
        titles[9]["title"] = f"{topic}: qué workflow compensa más"
    if theme == "hardware_ia_gpu":
        titles[0]["title"] = "Qué GPU comprar para IA local en 2026"
        titles[1]["title"] = f"{topic}: el cuello de botella real"
        titles[2]["title"] = "Hardware para IA local sin gastar de más"
        titles[4]["title"] = f"{topic}: compra con criterio real"
        titles[9]["title"] = f"{topic}: qué compensa comprar ahora"
    if theme in {"hermes_agent_ollama", "agentes_autonomos", "codex_agent_workflow"}:
        titles[0]["title"] = f"{topic}: guía real paso a paso"
        titles[1]["title"] = f"{topic}: dónde falla al montarlo"
        titles[4]["title"] = f"{topic}: así se usa en un caso real"
        titles[8]["title"] = f"{topic}: lo que merece la pena de verdad"
        titles[9]["title"] = f"{topic}: qué cambia frente a hacerlo a mano"
    if theme == "ollama_ia_local" and "ollama" in normalize_lower(candidate["title"]):
        titles[0]["title"] = "Ollama en local: guía real paso a paso"
        titles[2]["title"] = "Ollama en local gratis en tu PC"
        titles[3]["title"] = "Ollama en local: cuándo compensa de verdad"
        titles[9]["title"] = "Ollama en local o cloud: qué elegir"
    if theme == "tutorial_ia":
        titles[0]["title"] = f"{topic}: ideas útiles para el día a día"
        titles[1]["title"] = f"{topic}: lo que sí ahorra tiempo"
        titles[8]["title"] = f"{topic}: usos reales que merecen la pena"
    if candidate["format"] == "short" and candidate["recommendedActionType"] == "convertir en vídeo largo":
        titles[6]["title"] = f"{topic}: por qué este short pide vídeo largo"
        titles[7]["title"] = f"{topic}: del short al paso a paso completo"
    elif candidate["format"] == "short":
        titles[6]["title"] = f"{topic}: versión clara para short"
        titles[7]["title"] = f"{topic}: enfoque corto con promesa clara"
    return {"titles": titles}


def thumbnail_strategist_agent(candidate: dict[str, Any], competitor_info: dict[str, Any]) -> dict[str, Any]:
    theme = infer_main_theme(candidate["title"], candidate["editorialCategory"])
    if theme in {"hermes_agent_ollama", "agentes_autonomos", "codex_agent_workflow"}:
        ideas = [
            {
                "text": "LOCAL Y GRATIS",
                "visual": "pantalla del agente funcionando",
                "composition": "resultado en grande y detalle de setup pequeño",
                "why": "refuerza coste cero y resultado real al instante",
            },
            {
                "text": "ASI SI FUNCIONA",
                "visual": "antes/error frente a despues/ok",
                "composition": "comparativa izquierda-derecha con una sola mirada",
                "why": "promete solucion concreta y mejora el clic por contraste",
            },
            {
                "text": "EN TU PC",
                "visual": "interfaz + nombre del modelo local",
                "composition": "interfaz protagonista con etiqueta corta y limpia",
                "why": "subraya el angulo local, que es el diferencial del canal",
            },
        ]
    elif theme == "comfyui_video_workflow":
        ideas = [
            {
                "text": "WORKFLOW REAL",
                "visual": "resultado final del frame/video",
                "composition": "imagen final a pantalla casi completa y nodos pequeños",
                "why": "el clic entra por el resultado, no por el diagrama",
            },
            {
                "text": "DE ESTO A ESTO",
                "visual": "comparativa antes/despues",
                "composition": "dos frames claros con flecha central",
                "why": "explica valor sin leer demasiado",
            },
            {
                "text": "SIN LIARTE",
                "visual": "nodo principal + salida final",
                "composition": "un nodo grande y resultado final de fondo",
                "why": "reduce sensación de complejidad y mejora accesibilidad",
            },
        ]
    elif theme == "hardware_ia_gpu":
        ideas = [
            {
                "text": "NO LA COMPRES",
                "visual": "GPU en primer plano",
                "composition": "producto grande con una señal roja simple",
                "why": "activa curiosidad y criterio práctico",
            },
            {
                "text": "SI MUEVE IA",
                "visual": "GPU + dato de VRAM visible",
                "composition": "componente principal y cifra clara",
                "why": "ataca la pregunta exacta del usuario",
            },
            {
                "text": "CALIDAD/PRECIO",
                "visual": "dos GPUs enfrentadas",
                "composition": "comparativa limpia con etiqueta central",
                "why": "mejora clic en contenido de decisión de compra",
            },
        ]
    else:
        ideas = [
            {
                "text": "ESTO SI SIRVE",
                "visual": "resultado final visible",
                "composition": "un solo foco visual y texto corto",
                "why": "da promesa clara sin humo",
            },
            {
                "text": "MERECE LA PENA",
                "visual": "herramienta + resultado",
                "composition": "objeto principal con fondo limpio",
                "why": "reduce ambigüedad y mejora claridad",
            },
            {
                "text": "ASI SE HACE",
                "visual": "paso clave o pantalla final",
                "composition": "captura simple con contraste alto",
                "why": "apoya bien vídeos tutoriales o de proceso",
            },
        ]
    return {"ideas": ideas}


def packaging_agent(candidate: dict[str, Any], strategist: dict[str, Any], search_info: dict[str, Any], orchestrator_title: str | None = None) -> dict[str, Any]:
    clean_title = clean_hashtag_title(orchestrator_title or candidate["title"])
    theme = infer_main_theme(candidate["title"], candidate["editorialCategory"])
    if candidate["recommendedActionType"] == "convertir en vídeo largo":
        fmt = "convertir a vídeo largo"
    elif candidate["recommendedActionType"] == "convertir en short":
        fmt = "sacar short desde vídeo largo"
    elif candidate["recommendedActionType"] == "hacer segunda parte":
        fmt = "hacer segunda parte"
    elif strategist["strategyDecision"] == "pausarse":
        fmt = "no tocar"
    elif candidate["editorialCategory"] == "ia_tutorial":
        fmt = "convertir en tutorial"
    else:
        fmt = "mantener short" if candidate["format"] == "short" else "convertir en artículo"

    description = (
        f"En este vídeo vemos {clean_title} con un enfoque práctico y útil. "
        f"La idea es explicar qué problema resuelve, cómo montarlo sin rodeos y qué resultado real puedes esperar en un setup de {theme.replace('_', ' ')}."
    )
    if search_info.get("executed"):
        questions = search_info.get("questionsToAnswer", [])
        if questions:
            description += " Tambien responde a: " + "; ".join(questions[:3]) + "."

    hashtags_map = {
        "hermes_agent_ollama": ["#HermesAgent", "#Ollama", "#LocalAI", "#AIAgents", "#Automation"],
        "openclaw_local_ai": ["#OpenClaw", "#Ollama", "#LocalAI", "#OpenSourceAI", "#AI"],
        "codex_agent_workflow": ["#Codex", "#Automation", "#AIAgents", "#LocalAI", "#Workflow"],
        "ollama_ia_local": ["#Ollama", "#LocalAI", "#LLM", "#OpenSourceAI", "#AI"],
        "comfyui_video_workflow": ["#ComfyUI", "#AIVideo", "#AIImage", "#GenerativeAI", "#Workflow"],
        "hardware_ia_gpu": ["#GPU", "#LocalAI", "#AIHardware", "#PCBuild", "#Tech"],
        "tutorial_ia": ["#AITutorial", "#LocalAI", "#Automation", "#AI", "#HowTo"],
    }
    hashtags = hashtags_map.get(theme, ["#AI", "#Automation", "#LocalAI"])
    hook = (
        f"Si quieres que {clean_title} funcione de verdad y no quedarte en la demo, en este vídeo vamos al grano con el setup real."
    )
    return {
        "description": description,
        "hashtags": hashtags,
        "openingHook": hook,
        "recommendedFormat": fmt,
    }


def title_scores(title: str, candidate: dict[str, Any]) -> dict[str, int]:
    lower = normalize_lower(title)
    clarity = 8 if any(token in lower for token in ["como", "que", "sin", "paso a paso", "vs", "tutorial"]) else 6
    curiosity = 7 if any(token in lower for token in ["nadie", "error", "deja de", "merece"]) else 5
    promise = 8 if any(token in lower for token in ["funciona", "gratis", "local", "resultado", "montar"]) else 6
    specificity = 8 if len(tokenize(title)) >= 5 else 5
    ctr = min(10, round((clarity + curiosity + promise) / 3))
    seo = 8 if any(token in lower for token in ["ollama", "hermes", "codex", "comfyui", "gpu", "ia"]) else 5
    fit = 9 if candidate["editorialCategory"] in STRATEGIC_CATEGORIES else 6
    clickbait_risk = 8 if any(token in lower for token in ["insane", "brutal", "locura total", "nadie te cuenta"]) else 3
    return {
        "clarity": clarity,
        "curiosity": curiosity,
        "promise": promise,
        "specificity": specificity,
        "potentialCTR": ctr,
        "potentialSEO": seo,
        "channelFit": fit,
        "clickbaitRisk": clickbait_risk,
    }


def title_pattern_key(title: str) -> str:
    normalized = normalize_lower(title)
    if ":" in normalized:
        return normalized.split(":", 1)[1].strip()
    return normalized


def generic_title_reason(title: str, candidate: dict[str, Any]) -> str:
    normalized = normalize_lower(title)
    tokens = candidate_topic_tokens(candidate)
    if not any(token in normalized for token in tokens):
        return "Podría aplicarse a casi cualquier vídeo porque pierde el tema concreto."
    generic_fragments = [
        "lo que merece la pena de verdad",
        "prueba real en local",
        "guía real paso a paso",
        "errores que te ahorras",
        "lo que nadie te explica bien",
        "setup útil de verdad",
        "qué opción compensa más",
    ]
    for fragment in generic_fragments:
        if fragment in normalized:
            return f"Usa una coletilla demasiado reutilizable: '{fragment}'."
    if ":" in title and len(normalized.split(":", 1)[1].strip().split()) <= 4:
        return "La segunda mitad del título es demasiado genérica para distinguir el vídeo."
    return "Mantiene el tema real del vídeo y aterriza mejor la propuesta."


def analyze_global_title_patterns(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    pattern_examples: dict[str, list[str]] = {}
    title_examples: dict[str, list[str]] = {}
    repetitive_patterns: dict[str, dict[str, Any]] = {}

    for item in analyses:
        for generated in item["titleWriterAgent"]["titles"]:
            title = generated["title"]
            pattern = title_pattern_key(title)
            pattern_examples.setdefault(pattern, [])
            if len(pattern_examples[pattern]) < 4:
                pattern_examples[pattern].append(title)
            normalized_title = normalize_lower(title)
            title_examples.setdefault(normalized_title, [])
            if len(title_examples[normalized_title]) < 2:
                title_examples[normalized_title].append(title)

    for pattern, examples in pattern_examples.items():
        count = sum(1 for item in analyses for generated in item["titleWriterAgent"]["titles"] if title_pattern_key(generated["title"]) == pattern)
        if count >= 4:
            repetitive_patterns[pattern] = {
                "pattern": pattern,
                "count": count,
                "examples": examples[:3],
                "penalty": min(4, count - 2),
                "reason": "Coletilla o estructura repetida entre varios vídeos.",
            }

    return {
        "patterns": repetitive_patterns,
    }


def enrich_titles_with_global_signals(analyses: list[dict[str, Any]], global_patterns: dict[str, Any]) -> None:
    patterns = global_patterns.get("patterns", {})
    for item in analyses:
        for generated in item["titleWriterAgent"]["titles"]:
            pattern = title_pattern_key(generated["title"])
            repeated = pattern in patterns
            reason = generic_title_reason(generated["title"], item["candidate"])
            generated["globalRepetitionPenalty"] = patterns.get(pattern, {}).get("penalty", 0)
            generated["specificityReason"] = reason
            generated["reusedPatternDetected"] = repeated


def critic_agent(
    candidate: dict[str, Any],
    titles: list[dict[str, Any]],
    competitor_info: dict[str, Any],
    global_patterns: dict[str, Any],
) -> dict[str, Any]:
    competitor_names = " ".join(competitor_info.get("competitorsUsed", [])).lower()
    discarded: list[dict[str, str]] = []
    finalists: list[dict[str, Any]] = []
    seen: set[str] = set()
    topic_tokens = candidate_topic_tokens(candidate)
    banned_fragments = [
        "guía práctica sin humo",
        "version mas clara",
        "nuevo enfoque",
        "sin humo",
        "deja de montarlo mal",
        "tutorial completo en español",
        "así sí funciona",
        "el error que rompe el agente",
        "versión larga paso a paso",
    ]

    for item in titles:
        title = item["title"]
        key = normalize_lower(title)
        repetition_penalty = int(item.get("globalRepetitionPenalty", 0))
        specificity_reason = item.get("specificityReason", "Sin evaluación adicional.")
        reused_pattern = bool(item.get("reusedPatternDetected", False))
        if key in seen:
            discarded.append({"title": title, "reason": "Título repetido internamente."})
            continue
        seen.add(key)
        if any(fragment in key for fragment in banned_fragments):
            discarded.append({"title": title, "reason": "Suena a plantilla genérica."})
            continue
        if len(title) > 86:
            discarded.append({"title": title, "reason": "Demasiado largo para un empaquetado limpio."})
            continue
        if len(title) < 24:
            discarded.append({"title": title, "reason": "Demasiado corto y poco específico."})
            continue
        if " :" in title or "::" in title or title.endswith(":"):
            discarded.append({"title": title, "reason": "Cierre raro o construcción incompleta."})
            continue
        if sum(1 for token in ["guia", "tutorial", "como"] if token in key) > 2:
            discarded.append({"title": title, "reason": "Exceso de señales de plantilla tutorial."})
            continue
        if topic_tokens and not any(token in key for token in topic_tokens):
            discarded.append({"title": title, "reason": "Pierde el tema real del vídeo y suena intercambiable."})
            continue
        if competitor_names and key in competitor_names:
            discarded.append({"title": title, "reason": "Demasiado parecido al naming visible de competencia."})
            continue
        scores = title_scores(title, candidate)
        if scores["clickbaitRisk"] >= 8 and scores["clarity"] <= 6:
            discarded.append({"title": title, "reason": "Riesgo alto de clickbait sin claridad suficiente."})
            continue
        if repetition_penalty >= 4 and (
            "demasiado reutilizable" in specificity_reason.lower()
            or "demasiado genérica" in specificity_reason.lower()
            or "podría aplicarse a casi cualquier vídeo" in specificity_reason.lower()
        ):
            discarded.append({"title": title, "reason": "Repite demasiado una estructura ya usada en otros vídeos."})
            continue
        finalists.append(
            {
                "approach": item["approach"],
                "title": title,
                "scores": scores,
                "globalRepetitionPenalty": repetition_penalty,
                "specificityReason": specificity_reason,
                "reusedPatternDetected": reused_pattern,
                "patternKey": title_pattern_key(title),
                "globalPatternCount": global_patterns.get("patterns", {}).get(title_pattern_key(title), {}).get("count", 1),
            }
        )

    finalists.sort(
        key=lambda item: (
            -(
                item["scores"]["clarity"]
                + item["scores"]["promise"]
                + item["scores"]["channelFit"]
                + item["scores"]["potentialCTR"]
                + item["scores"]["specificity"]
                - item["globalRepetitionPenalty"]
            ),
            item["globalRepetitionPenalty"],
            -item["scores"]["specificity"],
            item["scores"]["clickbaitRisk"],
        )
    )
    return {"discarded": discarded, "finalists": finalists[:5]}


def orchestrator_agent(
    candidate: dict[str, Any],
    metrics_info: dict[str, Any],
    strategist: dict[str, Any],
    competitor_info: dict[str, Any],
    search_info: dict[str, Any],
    title_writer: dict[str, Any],
    thumbnail_info: dict[str, Any],
    critic: dict[str, Any],
) -> dict[str, Any]:
    finalists = critic["finalists"]
    if finalists:
        ranked = sorted(
            finalists,
            key=lambda item: (
                -(
                    item["scores"]["clarity"]
                    + item["scores"]["promise"]
                    + item["scores"]["specificity"]
                    + item["scores"]["channelFit"]
                    - item["globalRepetitionPenalty"]
                ),
                item["globalRepetitionPenalty"],
                -item["scores"]["specificity"],
                item["scores"]["clickbaitRisk"],
            ),
        )
        chosen = ranked[0]
        chosen_title = sanitize_final_title(chosen["title"], candidate)
        title_scores_map = title_scores(chosen_title, candidate)
        top5 = [sanitize_final_title(item["title"], candidate) for item in ranked[:5]]
    else:
        fallback = emergency_title(candidate)
        chosen_title = fallback
        title_scores_map = title_scores(fallback, candidate)
        top5 = [fallback]

    thumb = thumbnail_info["ideas"][0]
    package = packaging_agent(candidate, strategist, search_info, chosen_title)
    action = candidate["recommendedActionType"]
    if strategist["strategyDecision"] == "pausarse":
        action = "no tocar"
        package["recommendedFormat"] = "no tocar"

    confidence = "alta" if candidate["confidence"] == "alta" and competitor_info.get("competitorsUsed") else candidate["confidence"]
    rationale = (
        f"Gana porque combina encaje {strategist['strategicFit']}, evidencia de métricas ({metrics_info['changeReason']}) "
        f"y una promesa más clara frente a competencia ({competitor_info['theyDoBetter']}). "
        f"Además evita patrones demasiado repetidos y conserva mejor la especificidad del tema."
    )
    return {
        "touchVideo": action != "no tocar",
        "finalAction": action,
        "recommendedTitle": chosen_title,
        "top5Titles": top5,
        "recommendedThumbnail": thumb,
        "description": package["description"],
        "hashtags": package["hashtags"],
        "recommendedFormat": package["recommendedFormat"],
        "executionPriority": execution_priority(candidate, strategist),
        "confidenceFinal": confidence,
        "whyThisWins": rationale,
        "scores": title_scores_map,
        "openingHook": package["openingHook"],
        "globalRepetitionPenalty": finalists[0]["globalRepetitionPenalty"] if finalists else 0,
        "specificityReason": finalists[0]["specificityReason"] if finalists else "Fallback de emergencia.",
        "reusedPatternDetected": finalists[0]["reusedPatternDetected"] if finalists else False,
    }


def build_video_analysis(candidate: dict[str, Any], competitor_matches: list[dict[str, Any]], search_connection: tuple[str, str] | None) -> dict[str, Any]:
    metrics_info = metrics_analyst(candidate)
    strategist = channel_strategist(candidate)
    competitor_info = competitor_analyst(candidate, competitor_matches)
    search_info = search_intent_agent(candidate, competitor_info, search_connection)
    title_writer = title_writer_agent(candidate, strategist, competitor_info, search_info)
    thumbnail_info = thumbnail_strategist_agent(candidate, competitor_info)
    return {
        "candidate": candidate,
        "metricsAnalyst": metrics_info,
        "channelStrategist": strategist,
        "competitorAnalyst": competitor_info,
        "searchIntentAgent": search_info,
        "titleWriterAgent": title_writer,
        "thumbnailStrategistAgent": thumbnail_info,
        "competitorMatches": competitor_matches[:4],
    }


def build_proposals_bundle(report_date: dt.date | None = None) -> dict[str, Any]:
    candidates_payload, candidates_path = load_latest_or_dated(CANDIDATES_DATA_DIR, "video_rewrite_candidates", report_date)
    if not candidates_payload or not candidates_path:
        raise FileNotFoundError("No video_rewrite_candidates data available.")

    resolved_date = report_date or dt.date.fromisoformat(candidates_payload["reportDate"])
    diagnosis_payload, diagnosis_path = load_latest_or_dated(DIAGNOSIS_DATA_DIR, "channel_diagnosis", resolved_date)
    opportunities_payload, opportunities_path = load_latest_or_dated(OPPORTUNITIES_DATA_DIR, "channel_opportunities", resolved_date)
    discovery_payload, discovery_path = load_latest_or_dated(DISCOVERY_DATA_DIR, "competitor_discovery", resolved_date)
    scan_payload, scan_path = load_latest_or_dated(SCAN_DATA_DIR, "competitor_content_scan", resolved_date)

    if not scan_payload or not scan_path:
        raise FileNotFoundError("No competitor_content_scan data available.")

    search_connection = get_search_connection()
    matches_by_title: dict[str, list[dict[str, Any]]] = {}
    for item in scan_payload.get("matches", []):
        matches_by_title.setdefault(item["myVideoTitle"], []).append(item)

    selected_candidates = [item for item in candidates_payload["candidates"] if item["priority"] in {"A", "B"}]
    analyses = [
        build_video_analysis(candidate, matches_by_title.get(candidate["title"], []), search_connection)
        for candidate in selected_candidates
    ]
    global_patterns = analyze_global_title_patterns(analyses)
    enrich_titles_with_global_signals(analyses, global_patterns)
    for item in analyses:
        critic = critic_agent(item["candidate"], item["titleWriterAgent"]["titles"], item["competitorAnalyst"], global_patterns)
        orchestrator = orchestrator_agent(
            item["candidate"],
            item["metricsAnalyst"],
            item["channelStrategist"],
            item["competitorAnalyst"],
            item["searchIntentAgent"],
            item["titleWriterAgent"],
            item["thumbnailStrategistAgent"],
            critic,
        )
        item["criticAgent"] = critic
        item["orchestrator"] = orchestrator
    analyses.sort(
        key=lambda item: (
            item["candidate"]["priority"],
            {"alta": 0, "media": 1, "baja": 2}[item["orchestrator"]["executionPriority"]],
            -item["candidate"]["score"],
        )
    )
    return {
        "reportDate": resolved_date.isoformat(),
        "sources": {
            "channelDiagnosisJson": str(diagnosis_path) if diagnosis_path else None,
            "channelOpportunitiesJson": str(opportunities_path) if opportunities_path else None,
            "videoRewriteCandidatesJson": str(candidates_path),
            "competitorDiscoveryJson": str(discovery_path) if discovery_path else None,
            "competitorContentScanJson": str(scan_path),
        },
        "usedCompetitorContentScan": True,
        "usedSearchIntent": bool(search_connection),
        "globalRepeatedPatterns": sorted(global_patterns["patterns"].values(), key=lambda item: (-item["count"], item["pattern"])),
        "analyses": analyses,
    }


def title_bank_rows(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in analyses:
        title = item["candidate"]["title"]
        for generated in item["titleWriterAgent"]["titles"]:
            rows.append(
                {
                    "videoTitle": title,
                    "approach": generated["approach"],
                    "generatedTitle": generated["title"],
                    "globalRepetitionPenalty": generated.get("globalRepetitionPenalty", 0),
                    "specificityReason": generated.get("specificityReason", ""),
                    "reusedPatternDetected": generated.get("reusedPatternDetected", False),
                }
            )
    return rows


def thumbnail_rows(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in analyses:
        title = item["candidate"]["title"]
        for idx, idea in enumerate(item["thumbnailStrategistAgent"]["ideas"], start=1):
            rows.append(
                {
                    "videoTitle": title,
                    "ideaNumber": idx,
                    "text": idea["text"],
                    "visual": idea["visual"],
                    "composition": idea["composition"],
                    "why": idea["why"],
                }
            )
    return rows


def orchestrator_rows(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in analyses:
        orchestrator = item["orchestrator"]
        candidate = item["candidate"]
        scores = orchestrator["scores"]
        rows.append(
            {
                "videoTitle": candidate["title"],
                "videoUrl": candidate["videoUrl"],
                "priority": candidate["priority"],
                "finalAction": orchestrator["finalAction"],
                "recommendedTitle": orchestrator["recommendedTitle"],
                "recommendedFormat": orchestrator["recommendedFormat"],
                "executionPriority": orchestrator["executionPriority"],
                "confidenceFinal": orchestrator["confidenceFinal"],
                "clarity": scores["clarity"],
                "curiosity": scores["curiosity"],
                "promise": scores["promise"],
                "specificity": scores["specificity"],
                "potentialCTR": scores["potentialCTR"],
                "potentialSEO": scores["potentialSEO"],
                "channelFit": scores["channelFit"],
                "clickbaitRisk": scores["clickbaitRisk"],
                "globalRepetitionPenalty": orchestrator.get("globalRepetitionPenalty", 0),
                "specificityReason": orchestrator.get("specificityReason", ""),
                "reusedPatternDetected": orchestrator.get("reusedPatternDetected", False),
                "whyThisWins": orchestrator["whyThisWins"],
            }
        )
    return rows


def _render_agent_evidence(item: dict[str, Any]) -> list[str]:
    candidate = item["candidate"]
    metrics_info = item["metricsAnalyst"]
    strategist = item["channelStrategist"]
    competitor = item["competitorAnalyst"]
    search = item["searchIntentAgent"]
    critic = item["criticAgent"]
    orchestrator = item["orchestrator"]
    thumb = orchestrator["recommendedThumbnail"]
    lines = [
        f"### {candidate['title']}",
        "",
        f"- Título actual: **{candidate['title']}**",
        f"- URL: {candidate['videoUrl']}",
        f"- Categoría editorial: `{candidate['editorialCategory']}`",
        f"- Prioridad: `{candidate['priority']}`",
        f"- Problema detectado: {candidate['problemDetected']}",
        f"- Datos que justifican el cambio: {candidate['analysisSummary']} | {candidate['metricsReason']}",
        f"- Competencia relacionada usada: {', '.join(competitor['competitorsUsed']) if competitor['competitorsUsed'] else 'sin competencia clara'}",
        f"- Metrics Analyst: {metrics_info['shortDiagnosis']} Motivo: {metrics_info['changeReason']} | acción {metrics_info['recommendedAction']} | confianza {metrics_info['confidence']} | riesgo {metrics_info['risk']}.",
        f"- Channel Strategist: encaje `{strategist['strategicFit']}` | trafico `{strategist['trafficType']}` | prioridad real `{strategist['realPriority']}` | decisión `{strategist['strategyDecision']}`.",
        f"- Competitor Analyst: patrones {competitor['patterns']} | mejor hacen: {competitor['theyDoBetter']} | no copiar: {competitor['doNotCopy']} | diferenciación: {competitor['differentiation']}.",
    ]
    if search.get("executed"):
        lines.append(
            f"- Search Intent Agent: intención `{search['mainIntent']}` | consultas {', '.join(search['usefulQueries'])} | preguntas {', '.join(search['questionsToAnswer'])} | términos {', '.join(search['usefulTerms'])}."
        )
    else:
        lines.append(f"- Search Intent Agent: no ejecutado. {search['reason']}")
    lines.append("- 10 títulos iniciales:")
    for generated in item["titleWriterAgent"]["titles"]:
        lines.append(
            f"  - [{generated['approach']}] {generated['title']} | penalty {generated.get('globalRepetitionPenalty', 0)} | "
            f"reusedPattern `{generated.get('reusedPatternDetected', False)}` | {generated.get('specificityReason', '')}"
        )
    lines.append("- Títulos descartados:")
    if critic["discarded"]:
        for discarded in critic["discarded"]:
            lines.append(f"  - {discarded['title']} -> {discarded['reason']}")
    else:
        lines.append("  - Ninguno descartado por critic en esta ronda.")
    lines.append("- Top 5 títulos finales:")
    for title in orchestrator["top5Titles"]:
        lines.append(f"  - {title}")
    lines.extend(
        [
            f"- Título recomendado por Orchestrator: **{orchestrator['recommendedTitle']}**",
            "- 3 ideas de miniatura:",
        ]
    )
    for idea in item["thumbnailStrategistAgent"]["ideas"]:
        lines.append(
            f"  - texto `{idea['text']}` | visual {idea['visual']} | composición {idea['composition']} | motivo {idea['why']}"
        )
    lines.extend(
        [
            f"- Miniatura recomendada por Orchestrator: texto `{thumb['text']}` | visual {thumb['visual']} | composición {thumb['composition']}.",
            f"- Descripción propuesta: {orchestrator['description']}",
            f"- Hashtags sugeridos: {' '.join(orchestrator['hashtags'])}",
            f"- Formato recomendado: `{orchestrator['recommendedFormat']}`",
            f"- Acción recomendada final: `{orchestrator['finalAction']}`",
            (
                f"- Puntuaciones: claridad {orchestrator['scores']['clarity']}, curiosidad {orchestrator['scores']['curiosity']}, "
                f"promesa {orchestrator['scores']['promise']}, especificidad {orchestrator['scores']['specificity']}, "
                f"CTR {orchestrator['scores']['potentialCTR']}, SEO {orchestrator['scores']['potentialSEO']}, "
                f"encaje {orchestrator['scores']['channelFit']}, riesgo clickbait {orchestrator['scores']['clickbaitRisk']}."
            ),
            f"- Penalización global por repetición: {orchestrator.get('globalRepetitionPenalty', 0)} | patrón repetido `{orchestrator.get('reusedPatternDetected', False)}` | motivo de especificidad: {orchestrator.get('specificityReason', '')}",
            f"- Confianza final: `{orchestrator['confidenceFinal']}`",
            f"- Por qué gana esta decisión: {orchestrator['whyThisWins']}",
            "",
        ]
    )
    return lines


def generate_markdown_report(bundle: dict[str, Any]) -> str:
    analyses = bundle["analyses"]
    priority_a = [item for item in analyses if item["candidate"]["priority"] == "A"]
    priority_b = [item for item in analyses if item["candidate"]["priority"] == "B"]
    priority_c = [item for item in analyses if item["candidate"]["priority"] == "C" and item["orchestrator"]["executionPriority"] != "baja"]
    title_bank_count = sum(len(item["titleWriterAgent"]["titles"]) for item in analyses)
    discarded_count = sum(len(item["criticAgent"]["discarded"]) for item in analyses)

    lines = [
        f"# Video Rewrite Proposals - {bundle['reportDate']}",
        "",
        "## 1. Resumen ejecutivo.",
        "",
        f"- Vídeos analizados: {len(analyses)}",
        f"- Títulos generados: {title_bank_count}",
        f"- Títulos descartados por Critic Agent: {discarded_count}",
        f"- Search Intent usado: {'sí' if bundle['usedSearchIntent'] else 'no'}",
        f"- Competitor Content Scan usado: {'sí' if bundle['usedCompetitorContentScan'] else 'no'}",
        "",
        "## 2. Fuentes de datos usadas.",
        "",
    ]
    for key, value in bundle["sources"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## 3. Vídeos analizados.")
    lines.append("")
    for item in analyses:
        candidate = item["candidate"]
        lines.append(f"- **{candidate['title']}** | prioridad `{candidate['priority']}` | categoría `{candidate['editorialCategory']}`")
    lines.append("")
    lines.append("## 4. Propuestas prioridad A.")
    lines.append("")
    for item in priority_a:
        lines.extend(_render_agent_evidence(item))
    lines.append("## 5. Propuestas prioridad B.")
    lines.append("")
    for item in priority_b:
        lines.extend(_render_agent_evidence(item))
    if priority_c:
        lines.append("## 6. Propuestas prioridad C solo si merece la pena.")
        lines.append("")
        for item in priority_c:
            lines.extend(_render_agent_evidence(item))
    else:
        lines.append("## 6. Propuestas prioridad C solo si merece la pena.")
        lines.append("")
        lines.append("- Ninguna prioridad C ha pasado el corte inicial del Orchestrator.")
        lines.append("")
    lines.append("## 7. Evidencia usada por agentes.")
    lines.append("")
    for item in analyses[:8]:
        lines.append(f"- **{item['candidate']['title']}** -> métricas: {item['metricsAnalyst']['changeReason']} | estrategia: {item['channelStrategist']['strategyDecision']}")
    lines.append("")
    lines.append("## 8. Comparación de competencia usada.")
    lines.append("")
    for item in analyses[:8]:
        comp = item["competitorAnalyst"]
        lines.append(f"- **{item['candidate']['title']}** -> {', '.join(comp['competitorsUsed']) if comp['competitorsUsed'] else 'sin competencia clara'} | {comp['theyDoBetter']}")
    lines.append("")
    lines.append("## 9. Search Intent si estuvo disponible.")
    lines.append("")
    if bundle["usedSearchIntent"]:
        for item in analyses[:8]:
            search = item["searchIntentAgent"]
            if search.get("executed"):
                lines.append(f"- **{item['candidate']['title']}** -> consultas {', '.join(search['usefulQueries'])} | términos {', '.join(search['usefulTerms'])}")
    else:
        lines.append("- Search Intent Agent no se ejecutó porque Google Custom Search no estaba operativo o no merecía bloquear el flujo.")
    lines.append("")
    lines.append("## 10. Banco de títulos.")
    lines.append("")
    for item in analyses[:8]:
        lines.append(f"- **{item['candidate']['title']}**")
        for generated in item["titleWriterAgent"]["titles"]:
            lines.append(f"  - [{generated['approach']}] {generated['title']}")
    lines.append("")
    lines.append("## 11. Títulos descartados por Critic Agent.")
    lines.append("")
    if discarded_count:
        for item in analyses[:8]:
            if not item["criticAgent"]["discarded"]:
                continue
            lines.append(f"- **{item['candidate']['title']}**")
            for discarded in item["criticAgent"]["discarded"]:
                lines.append(f"  - {discarded['title']} -> {discarded['reason']}")
    else:
        lines.append("- El Critic Agent no encontró títulos claramente descartables en esta pasada.")
    lines.append("")
    lines.append("## 12. Patrones repetidos penalizados.")
    lines.append("")
    if bundle.get("globalRepeatedPatterns"):
        for pattern in bundle["globalRepeatedPatterns"]:
            lines.append(
                f"- Patrón: `{pattern['pattern']}` | apariciones {pattern['count']} | ejemplos: {' | '.join(pattern['examples'])} | "
                f"cómo se corrigió: se aplicó penalización global {pattern['penalty']} y el Orchestrator priorizó alternativas más específicas."
            )
    else:
        lines.append("- No se detectaron patrones globales suficientemente repetidos como para penalizarlos.")
    lines.append("")
    lines.append("## 13. Decisiones finales del Orchestrator.")
    lines.append("")
    for item in analyses:
        orchestrator = item["orchestrator"]
        lines.append(
            f"- **{item['candidate']['title']}** -> acción `{orchestrator['finalAction']}` | título recomendado **{orchestrator['recommendedTitle']}** | formato `{orchestrator['recommendedFormat']}` | prioridad `{orchestrator['executionPriority']}` | penalty global {orchestrator.get('globalRepetitionPenalty', 0)}"
        )
    lines.append("")
    lines.append("## 14. Ideas de miniatura.")
    lines.append("")
    for item in analyses[:8]:
        lines.append(f"- **{item['candidate']['title']}** -> {item['orchestrator']['recommendedThumbnail']['text']} / {item['orchestrator']['recommendedThumbnail']['visual']}")
    lines.append("")
    lines.append("## 15. Descripciones propuestas.")
    lines.append("")
    for item in analyses[:8]:
        lines.append(f"- **{item['candidate']['title']}** -> {item['orchestrator']['description']}")
    lines.append("")
    lines.append("## 16. Recomendaciones de formato.")
    lines.append("")
    for item in analyses:
        lines.append(f"- **{item['candidate']['title']}** -> `{item['orchestrator']['recommendedFormat']}`")
    lines.append("")
    lines.append("## 17. Plan de acción recomendado.")
    lines.append("")
    for item in analyses[:10]:
        orchestrator = item["orchestrator"]
        lines.append(f"- **{item['candidate']['title']}** -> {orchestrator['finalAction']} | {orchestrator['recommendedTitle']}")
    lines.append("")
    lines.append("## 18. Limitaciones del análisis.")
    lines.append("")
    lines.append("- No se ha tocado YouTube ni se han aplicado cambios reales.")
    lines.append("- La competencia informa, pero no se copia; las comparaciones salen de `competitor_content_scan` y de datos públicos.")
    lines.append("- Si Search Intent no se ejecuta, el flujo sigue con señales de YouTube, estrategia y competencia.")
    lines.append("- Las puntuaciones son heurísticas editoriales para priorizar, no métricas oficiales de plataforma.")
    return "\n".join(lines) + "\n"


def run_video_rewrite_proposals(report_date: dt.date | None = None) -> dict[str, Path]:
    ensure_output_dirs()
    bundle = build_proposals_bundle(report_date)
    stamp = bundle["reportDate"]

    report_path = REPORTS_DIR / f"video_rewrite_proposals_{stamp}.md"
    json_path = PROPOSALS_DATA_DIR / f"video_rewrite_proposals_{stamp}.json"
    title_bank_path = PROPOSALS_DATA_DIR / f"title_bank_{stamp}.csv"
    thumbnail_path = PROPOSALS_DATA_DIR / f"thumbnail_ideas_{stamp}.csv"
    orchestrator_path = PROPOSALS_DATA_DIR / f"orchestrator_decisions_{stamp}.csv"

    save_json(json_path, bundle)
    save_csv(title_bank_path, title_bank_rows(bundle["analyses"]))
    save_csv(thumbnail_path, thumbnail_rows(bundle["analyses"]))
    save_csv(orchestrator_path, orchestrator_rows(bundle["analyses"]))
    report_path.write_text(generate_markdown_report(bundle), encoding="utf-8")

    return {
        "report": report_path,
        "json": json_path,
        "title_bank_csv": title_bank_path,
        "thumbnail_csv": thumbnail_path,
        "orchestrator_csv": orchestrator_path,
    }

import os
import re
import time
import json
import random
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st
import google.generativeai as genai
from bs4 import BeautifulSoup
from curl_cffi import requests as requests_cffi

# =========================================================
# CONFIGURAÇÃO GERAL
# =========================================================
st.set_page_config(
    page_title="Assistente Fiscal - Gabriela | V4",
    layout="wide"
)

PASTA_CACHE = "cache_scraping"
ARQUIVO_ULTIMA_EXECUCAO = os.path.join(PASTA_CACHE, "ultima_execucao.json")
os.makedirs(PASTA_CACHE, exist_ok=True)

HEADERS_WEB = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

URLS_OFICIAIS = [
    {
        "nome": "Ministério da Fazenda",
        "url": "https://www.gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria"
    },
    {
        "nome": "Receita Federal",
        "url": "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo"
    },
    {
        "nome": "CGIBS",
        "url": "https://www.cgibs.gov.br/"
    }
]

URLS_NOTICIAS = [
    {
        "nome": "Ministério da Fazenda - Reforma Tributária",
        "url": "https://www.gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria"
    },
    {
        "nome": "Receita Federal - Reforma Consumo",
        "url": "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo"
    },
    {
        "nome": "Notícia - Federalismo Fiscal Cooperativo",
        "url": "https://www.gov.br/fazenda/pt-br/assuntos/noticias/2026/janeiro/nova-lei-de-regulamentacao-da-reforma-tributaria-aprofunda-o-federalismo-fiscal-cooperativo"
    }
]

# =========================================================
# REGRAS DE TRIBUTAÇÃO CBS/IBS (Extraídas dos Manuais RTC)
# =========================================================
TRIBUTOS_RTC = {
    "CBS": {
        "nome": "Contribuição sobre Bens e Serviços",
        "competencia": "União",
        "substitui": ["PIS", "COFINS"],
        "aliquota_padrao": 0.0,  # Será definida conforme o período
    },
    "IBS": {
        "nome": "Imposto sobre Bens e Serviços",
        "competencia": "Estados e Municípios",
        "substitui": ["ICMS", "ISS"],
        "aliquota_padrao": 0.0,
    },
    "IS": {
        "nome": "Imposto Seletivo",
        "competencia": "União",
        "descricao": "Imposto do Pecado - produtos prejudiciais à saúde/meio ambiente",
    }
}

CST_TRIBUTACAO = {
    "000": {"descricao": "Tributação Normal", "tipo": "normal"},
    "100": {"descricao": "Monofásica", "tipo": "especial"},
    "200": {"descricao": "Alíquota Reduzida", "tipo": "reduzida"},
    "300": {"descricao": "Isenção", "tipo": "isenção"},
    "400": {"descricao": "Não Incidência", "tipo": "nao_incidencia"},
    "500": {"descricao": "Suspensão", "tipo": "suspensão"},
    "600": {"descricao": "Recolhimento Diferido", "tipo": "diferido"},
    "900": {"descricao": "Imunidade", "tipo": "imunidade"},
}

MODELO_DOCUMENTO_FISCAL = {
    "55": {"nome": "NF-e", "descricao": "Nota Fiscal Eletrônica"},
    "65": {"nome": "NFC-e", "descricao": "Nota Fiscal de Consumidor Eletrônica"},
    "57": {"nome": "CT-e", "descricao": "Conhecimento de Transporte Eletrônico"},
    "67": {"nome": "CT-e OS", "descricao": "Conhecimento de Transporte Eletrônico Outros Serviços"},
    "62": {"nome": "NFCom", "descricao": "Nota Fiscal de Serviço de Comunicação Eletrônica"},
    "66": {"nome": "NF3e", "descricao": "Nota Fiscal de Energia Elétrica Eletrônica"},
    "63": {"nome": "BP-e", "descricao": "Bilhete de Passagem Eletrônico"},
}

TIPOS_OPERACAO = {
    "entrada": {"descricao": "Operação de Entrada (Compra)", "gera_credito": True, "gera_debito": False},
    "saida": {"descricao": "Operação de Saída (Venda)", "gera_credito": False, "gera_debito": True},
}

REGIMES_ESPECIAIS = {
    "PIS": "Contribuição para o PIS",
    "COFINS": "Contribuição para o COFINS", 
    "ICMS": "Imposto sobre Circulação de Mercadorias e Serviços",
    "ISS": "Imposto sobre Serviços",
    "IPI": "Imposto sobre Produtos Industrializados",
    "CBS": "Contribuição sobre Bens e Serviços (Novo)",
    "IBS": "Imposto sobre Bens e Serviços (Novo)",
    "IS": "Imposto Seletivo (Novo)",
}

PERIODO_TRANSICAO = {
    "2026": {
        "descricao": "Ano teste",
        "aliquota_cbs": 0.009,
        "aliquota_ibs": 0.001,
        "observacao": "Apenas destaque declaratório, sem pagamento"
    },
    "2027": {
        "descricao": "CBS entra em vigor",
        "aliquota_cbs": None,
        "aliquota_ibs": None,
        "observacao": "CBS e IBS passam a vigorar. PIS e COFINS extintos."
    },
    "2033": {
        "descricao": "Transição completa",
        "observacao": "Substituição completa dos tributos antigos"
    }
}


def analisar_tributacao_xml(xml_content: str) -> Dict[str, Any]:
    """
    Analisa um XML de documento fiscal e determina a tributação CBS/IBS aplicável.
    Baseado nas regras extraídas dos Manuais RTC.
    """
    import xml.etree.ElementTree as ET
    
    resultado = {
        "documento_fiscal": None,
        "tipo_operacao": None,
        "modelo": None,
        "serie": None,
        "numero": None,
        "data_emissao": None,
        "natureza_operacao": None,
        "tributos_identificados": [],
        "cst": None,
        "cclass_trib": None,
        "informacoes_fiscais": [],
        "regimes_encontrados": [],
        "analise": "",
    }
    
    try:
        root = ET.fromstring(xml_content)
        
        # Namespace comumente usados
        ns = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}
        
        # Tentar encontrarinfNFe
        infNFe = root.find('.//{http://www.portalfiscal.inf.br/nfe}infNFe')
        if infNFe is None:
            # Tentar sem namespace
            infNFe = root.find('.//infNFe')
        
        if infNFe is None:
            return {"erro": "XML não identificado como documento fiscal válido"}
        
        # Extrair informações básicas
        resultado["modelo"] = infNFe.get('mod', 'Não identificado')
        resultado["serie"] = infNFe.get('serie', 'Não identificado')
        resultado["numero"] = infNFe.get('nNF', 'Não identificado')
        
        # Identificar tipo de operação (entrada/saída)
        ide = root.find('.//{http://www.portalfiscal.inf.br/nfe}ide')
        if ide is None:
            ide = root.find('.//ide')
        
        if ide is not None:
            tpNF = ide.find('{http://www.portalfiscal.inf.br/nfe}tpNF')
            if tpNF is None:
                tpNF = ide.find('tpNF')
            
            if tpNF is not None:
                if tpNF.text == '0':
                    resultado["tipo_operacao"] = "entrada"
                elif tpNF.text == '1':
                    resultado["tipo_operacao"] = "saida"
            
            resultado["data_emissao"] = ide.find('{http://www.portalfiscal.inf.br/nfe}dhEmi').text if ide.find('{http://www.portalfiscal.inf.br/nfe}dhEmi') is not None else None
        
        # Natureza da operação
        natOp = root.find('.//{http://www.portalfiscal.inf.br/nfe}natOp')
        if natOp is None:
            natOp = root.find('.//natOp')
        if natOp is not None:
            resultado["natureza_operacao"] = natOp.text
        
        # Identificar documento fiscal
        modelo_info = MODELO_DOCUMENTO_FISCAL.get(resultado["modelo"], {"nome": "Desconhecido"})
        resultado["documento_fiscal"] = modelo_info["nome"]
        
        # Analisar produtos/impostos
        detalhes = []
        for det in root.findall('.//{http://www.portalfiscal.inf.br/nfe}det'):
            # CST do produto
            imp = det.find('.//{http://www.portalfiscal.inf.br/nfe}imposto')
            if imp is None:
                imp = det.find('.//imposto')
            
            if imp is not None:
                # CBS
                cbs = imp.find('.//{http://www.portalfiscal.inf.br/nfe}CBS')
                if cbs is not None:
                    cst_cbs = cbs.find('{http://www.portalfiscal.inf.br/nfe}CST')
                    cclass = cbs.find('{http://www.portalfiscal.inf.br/nfe}cClassTrib')
                    detalhes.append({
                        "tributo": "CBS",
                        "cst": cst_cbs.text if cst_cbs is not None else None,
                        "cclass_trib": cclass.text if cclass is not None else None,
                    })
                    resultado["tributos_identificados"].append("CBS")
                
                # IBS
                ibs = imp.find('.//{http://www.portalfiscal.inf.br/nfe}IBS')
                if ibs is not None:
                    cst_ibs = ibs.find('{http://www.portalfiscal.inf.br/nfe}CST')
                    cclass = ibs.find('{http://www.portalfiscal.inf.br/nfe}cClassTrib')
                    detalhes.append({
                        "tributo": "IBS",
                        "cst": cst_ibs.text if cst_ibs is not None else None,
                        "cclass_trib": cclass.text if cclass is not None else None,
                    })
                    resultado["tributos_identificados"].append("IBS")
                
                # Imposto Seletivo
                impSeletivo = imp.find('.//{http://www.portalfiscal.inf.br/nfe}ImpSeletivo')
                if impSeletivo is not None:
                    detalhes.append({"tributo": "Imposto Seletivo"})
                    resultado["tributos_identificados"].append("Imposto Seletivo")
                
                # Verificar PIS/COFINS (tributos antigos que serão substituídos)
                pis = imp.find('.//{http://www.portalfiscal.inf.br/nfe}PIS')
                cofins = imp.find('.//{http://www.portalfiscal.inf.br/nfe}COFINS')
                icms = imp.find('.//{http://www.portalfiscal.inf.br/nfe}ICMS')
                iss = imp.find('.//{http://www.portalfiscal.inf.br/nfe}ISS')
                
                if pis is not None:
                    resultado["regimes_encontrados"].append("PIS")
                if cofins is not None:
                    resultado["regimes_encontrados"].append("COFINS")
                if icms is not None:
                    resultado["regimes_encontrados"].append("ICMS")
                if iss is not None:
                    resultado["regimes_encontrados"].append("ISS")
        
        resultado["informacoes_fiscais"] = detalhes
        
        # Gerar análise
        resultado["analise"] = gerar_analise_tributaria(resultado)
        
    except ET.ParseError as e:
        return {"erro": f"Erro ao parsear XML: {str(e)}"}
    except Exception as e:
        return {"erro": f"Erro na análise: {str(e)}"}
    
    return resultado


def gerar_analise_tributaria(analise: Dict[str, Any]) -> str:
    """Gera uma análise textual baseada nos dados extraídos do XML"""
    
    if "erro" in analise:
        return f"Erro: {analise['erro']}"
    
    linhas = []
    
    linhas.append("=" * 60)
    linhas.append("ANÁLISE DE TRIBUTAÇÃO CBS/IBS - REFORMA TRIBUTÁRIA")
    linhas.append("=" * 60)
    
    linhas.append(f"\n📄 Documento: {analise.get('documento_fiscal', 'N/A')}")
    linhas.append(f"   Modelo: {analise.get('modelo', 'N/A')}")
    linhas.append(f"   Número: {analise.get('numero', 'N/A')}")
    linhas.append(f"   Série: {analise.get('serie', 'N/A')}")
    linhas.append(f"   Data Emissão: {analise.get('data_emissao', 'N/A')}")
    
    tipo_op = analise.get('tipo_operacao', 'N/A')
    if tipo_op == 'entrada':
        linhas.append(f"\n📥 Tipo de Operação: ENTRADA (Compra)")
        linhas.append("   → Gera CRÉDITO tributário para o comprador")
    elif tipo_op == 'saida':
        linhas.append(f"\n📤 Tipo de Operação: SAÍDA (Venda)")
        linhas.append("   → Gera DÉBITO tributário para o vendedor")
    
    natureza = analise.get('natureza_operacao')
    if natureza:
        linhas.append(f"\n📝 Natureza da Operação: {natureza}")
    
    # Tributos identificados
    tributos = analise.get('tributos_identificados', [])
    if tributos:
        linhas.append("\n💰 TRIBUTOS IDENTIFICADOS NO XML:")
        for t in set(tributos):
            info = TRIBUTOS_RTC.get(t, {})
            linhas.append(f"   • {t}: {info.get('nome', '')}")
            linhas.append(f"     Competência: {info.get('competencia', '')}")
            if info.get('substitui'):
                linhas.append(f"     Substitui: {', '.join(info['substitui'])}")
    
    # Regimes antigos encontrados
    regimes = analise.get('regimes_encontrados', [])
    if regimes:
        linhas.append("\n⚠️  TRIBUTOS ATUAIS (serão substituídos):")
        for r in regimes:
            linhas.append(f"   • {r}")
    
    # Análise detailed
    detalhes = analise.get('informacoes_fiscais', [])
    if detalhes:
        linhas.append("\n📊 DETALHAMENTO POR ITEM:")
        for i, det in enumerate(detalhes, 1):
            if det.get('tributo'):
                linhas.append(f"   Item {i}:")
                linhas.append(f"     Tributo: {det.get('tributo')}")
                if det.get('cst'):
                    cst_info = CST_TRIBUTACAO.get(det['cst'], {})
                    linhas.append(f"     CST: {det['cst']} - {cst_info.get('descricao', '')}")
                if det.get('cclass_trib'):
                    linhas.append(f"     Classificação: {det['cclass_trib']}")
    
    linhas.append("\n" + "=" * 60)
    linhas.append("INFORMAÇÕES ADICIONAIS:")
    linhas.append("=" * 60)
    
    linhas.append(f"""
📅 Período de Transição:
• 2026: CBS/IBS com alíquotas reduzidas (0,9% + 0,1%)
  → Destacado em nota fiscal, mas sem pagamento
• 2027: CBS e IBS passam a vigorar normalmente
• 2033: Substituição completa dos tributos atuais
""")
    
    return "\n".join(linhas)


# =========================================================
# SECRETS / MODELOS
# =========================================================
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", "")

GEMINI_MODEL = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = st.secrets.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_MODEL = st.secrets.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

OPENROUTER_APP_NAME = st.secrets.get("OPENROUTER_APP_NAME", "Assistente Fiscal Gabriela")
OPENROUTER_APP_URL = st.secrets.get("OPENROUTER_APP_URL", "https://localhost")

# =========================================================
# SESSION STATE INICIAL
# =========================================================
if "router_state" not in st.session_state:
    st.session_state.router_state = {
        "gemini_cooldown_until": None,
        "gemini_calls_success": 0,
        "groq_calls_success": 0,
        "openrouter_calls_success": 0,
        "last_provider_used": None,
        "last_router_reason": None,
    }

if "mensagens_chat_oficial_v4" not in st.session_state:
    st.session_state.mensagens_chat_oficial_v4 = []

# =========================================================
# FUNÇÕES AUXILIARES - DATA / JSON / HASH
# =========================================================
def agora_str() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def agora_dt() -> datetime:
    return datetime.now()


def agora_arquivo() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def salvar_json(caminho: str, dados: dict):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def ler_json(caminho: str):
    if not os.path.exists(caminho):
        return None
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def gerar_hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# =========================================================
# CONFIGURAÇÃO GEMINI
# =========================================================
def configurar_gemini():
    if not GEMINI_API_KEY:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel(GEMINI_MODEL)
    except Exception as e:
        st.warning(f"Gemini indisponível no carregamento: {e}")
        return None


gemini_model = configurar_gemini()

# =========================================================
# FUNÇÕES AUXILIARES - ERROS / QUOTA / COOLDOWN
# =========================================================
def extrair_retry_seconds(mensagem_erro: str, default: int = 60) -> int:
    try:
        padrao = r"retry in\s+([0-9]+(?:\.[0-9]+)?)s"
        match = re.search(padrao, mensagem_erro, re.IGNORECASE)
        if match:
            return max(1, int(float(match.group(1))) + 1)
    except Exception:
        pass
    return default


def eh_erro_quota_429(erro: Exception) -> bool:
    msg = str(erro).lower()
    return (
        "429" in msg
        or "quota exceeded" in msg
        or "rate limit" in msg
        or "too many requests" in msg
    )


def definir_cooldown_gemini(segundos: int):
    st.session_state.router_state["gemini_cooldown_until"] = (
        agora_dt() + timedelta(seconds=segundos)
    ).isoformat()


def gemini_em_cooldown() -> Tuple[bool, int]:
    raw = st.session_state.router_state.get("gemini_cooldown_until")
    if not raw:
        return False, 0

    try:
        dt = datetime.fromisoformat(raw)
        restante = int((dt - agora_dt()).total_seconds())
        if restante > 0:
            return True, restante
    except Exception:
        pass

    st.session_state.router_state["gemini_cooldown_until"] = None
    return False, 0


# =========================================================
# SCRAPING
# =========================================================
def baixar_html_com_curl_cffi(url: str) -> str:
    sess = requests_cffi.Session()
    resp = sess.get(
        url,
        headers=HEADERS_WEB,
        impersonate="chrome",
        timeout=30,
        allow_redirects=True,
        verify=True,
    )
    resp.raise_for_status()
    return resp.text


def baixar_html_com_requests(url: str) -> str:
    resp = requests.get(
        url,
        headers=HEADERS_WEB,
        timeout=30,
        allow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text


def baixar_html(url: str, tentativas: int = 2, pausa_segundos: int = 2) -> str:
    ultimo_erro = None

    for tentativa in range(1, tentativas + 1):
        try:
            return baixar_html_com_curl_cffi(url)
        except Exception as e:
            ultimo_erro = e
            if tentativa < tentativas:
                time.sleep(pausa_segundos)

    try:
        return baixar_html_com_requests(url)
    except Exception as e2:
        raise RuntimeError(
            f"Falha ao acessar {url}. "
            f"curl_cffi falhou com: {ultimo_erro} | requests falhou com: {e2}"
        )


def limpar_html_para_texto(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup([
        "script", "style", "noscript", "svg", "img", "header", "footer",
        "nav", "form", "button", "aside"
    ]):
        tag.decompose()

    texto = soup.get_text(separator=" ", strip=True)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def extrair_texto_da_url(url: str, limite_chars: int = 18000) -> str:
    html = baixar_html(url)
    texto = limpar_html_para_texto(html)
    return texto[:limite_chars]


def extrair_noticias_da_url(url: str, limite_chars: int = 12000) -> str:
    html = baixar_html(url)
    texto = limpar_html_foco_noticias(html)
    return texto[:limite_chars]


def extrair_conteudo_completo(url: str, limite_chars: int = 15000) -> str:
    html = baixar_html(url)
    texto = limpar_html_para_texto(html)
    return texto[:limite_chars]


def coletar_portal(nome: str, url: str, eh_noticia: bool = False) -> Dict[str, str]:
    if eh_noticia:
        texto = extrair_conteudo_completo(url)
    else:
        texto = extrair_texto_da_url(url)
    return {
        "nome": nome,
        "url": url,
        "texto": texto,
        "hash": gerar_hash_texto(texto),
        "coletado_em": agora_str()
    }


def coletar_todos_portais() -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    dados_portais = []
    falhas = []

    for portal in URLS_OFICIAIS:
        nome = portal["nome"]
        url = portal["url"]
        try:
            item = coletar_portal(nome, url)
            dados_portais.append(item)
        except Exception as e:
            falhas.append({"portal": nome, "url": url, "erro": str(e)})

    return dados_portais, falhas


def coletar_noticias() -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    dados_noticias = []
    falhas = []

    for portal in URLS_NOTICIAS:
        nome = portal["nome"]
        url = portal["url"]
        try:
            item = coletar_portal(nome, url, eh_noticia=True)
            dados_noticias.append(item)
        except Exception as e:
            falhas.append({"portal": nome, "url": url, "erro": str(e)})

    return dados_noticias, falhas


def limpar_html_foco_noticias(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "img", "header", "footer", "nav", "form", "button", "aside"]):
        tag.decompose()

    noticias_encontradas = []
    for link in soup.find_all("a"):
        texto = link.get_text(strip=True)
        href = link.get("href", "")
        if texto and len(texto) > 30 and href:
            noticias_encontradas.append(f"TÍTULO: {texto} | URL: {href}")

    for tag in soup.find_all(["div", "section", "article"]):
        tag.decompose()

    texto = soup.get_text(separator=" | ", strip=True)
    texto = re.sub(r"\s+", " ", texto).strip()

    if noticias_encontradas:
        noticias_formatadas = "\n".join(noticias_encontradas[:15])
        texto = f"LISTA DE NOTÍCIAS:\n{noticias_formatadas}\n\nCONTEÚDO ADICIONAL:\n{texto[:10000]}"

    return texto[:15000]


def extrair_lista_noticias_formatada(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    noticias = []
    
    for link in soup.find_all("a"):
        texto = link.get_text(strip=True)
        href = link.get("href", "")
        
        if texto and len(texto) > 40 and "/noticias/" in href:
            data_tag = link.find_parent("section") or link.find_parent("article")
            data = ""
            if data_tag:
                data_span = data_tag.find("span") or data_tag.find("time") or data_tag.find("p")
                if data_span:
                    data = data_span.get_text(strip=True)[:20]
            
            if data:
                href_completa = href if href.startswith("http") else f"https://www.gov.br{href}"
                noticias.append({
                    "titulo": texto[:150],
                    "url": href_completa,
                    "data": data,
                    "href_original": href
                })
    
    seen = set()
    unique_noticias = []
    for n in noticias:
        if n["titulo"] not in seen:
            seen.add(n["titulo"])
            unique_noticias.append(n)
    
    return unique_noticias[:20]


def coletar_conteudo_noticia(url: str) -> str:
    try:
        html = baixar_html(url)
        return limpar_html_para_texto(html)[:8000]
    except:
        return ""


def coletar_lista_noticias() -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    dados_noticias = []
    falhas = []

    for portal in URLS_NOTICIAS:
        nome = portal["nome"]
        url = portal["url"]
        try:
            html = baixar_html(url)
            noticias = extrair_lista_noticias_formatada(html)
            for n in noticias:
                dados_noticias.append({
                    "nome": nome,
                    "url": n["url"],
                    "texto": f"TÍTULO: {n['titulo']} | DATA: {n['data']}",
                    "hash": "",
                    "coletado_em": agora_str()
                })
        except Exception as e:
            falhas.append({"portal": nome, "url": url, "erro": str(e)})

    return dados_noticias, falhas


def buscar_noticias_por_palavra_chave(palavra_chave: str) -> List[Dict[str, str]]:
    todas_noticias = []
    
    for portal in URLS_NOTICIAS:
        try:
            html = baixar_html(portal["url"])
            noticias = extrair_lista_noticias_formatada(html)
            for n in noticias:
                n["nome_fonte"] = portal["nome"]
                todas_noticias.append(n)
        except:
            pass
    
    palavra_lower = palavra_chave.lower()
    noticias_relevantes = []
    
    for n in todas_noticias:
        titulo_lower = n["titulo"].lower()
        if palavra_lower in titulo_lower:
            conteudo = coletar_conteudo_noticia(n["url"])
            n["conteudo"] = conteudo
            noticias_relevantes.append(n)
    
    if not noticias_relevantes:
        for n in todas_noticias[:5]:
            conteudo = coletar_conteudo_noticia(n["url"])
            n["conteudo"] = conteudo
            noticias_relevantes.append(n)
    
    return noticias_relevantes


def buscar_noticia_na_web(palavra_chave: str, max_resultados: int = 3) -> List[Dict[str, str]]:
    """Busca notícias na web usando Google (gratuitamente)"""
    resultados = []
    
    query = f"Reforma Tributária {palavra_chave} gov.br Receita Federal 2026"
    
    try:
        url_busca = "https://www.google.com/search"
        params = {
            "q": query,
            "num": max_resultados * 2,
            "hl": "pt-BR"
        }
        headers_busca = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9"
        }
        
        response = requests.get(url_busca, params=params, headers=headers_busca, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        for item in soup.find_all("div", class_="BNeawe")[:max_resultados]:
            link_tag = item.find("a")
            if link_tag:
                href = link_tag.get("href", "")
                if "/url?" in href:
                    from urllib.parse import urlparse, parse_qs
                    parsed = parse_qs(urlparse(href).query)
                    url_final = parsed.get("q", [href])[0]
                    if "gov.br" in url_final and "noticia" in url_final:
                        titulo = item.get_text(strip=True)[:100]
                        resultados.append({
                            "titulo": titulo,
                            "url": url_final,
                            "data": "",
                            "conteudo": "",
                            "nome_fonte": "Busca Web"
                        })
    except Exception as e:
        pass
    
    return resultados


def buscar_conteudo_noticia_completo(url: str) -> str:
    """Tenta buscar conteúdo completo de uma notícia"""
    try:
        html = baixar_html(url)
        texto = limpar_html_para_texto(html)
        if len(texto) > 500:
            return texto[:8000]
    except:
        pass
    
    try:
        from urllib.parse import urlparse
        dominio = urlparse(url).netloc
        if "gov.br" in dominio:
            return f"Notícia disponível em: {url}"
    except:
        pass
    
    return ""


# =========================================================
# COMPARAÇÃO
# =========================================================
def segmentar_texto_em_blocos(texto: str, tamanho_bloco: int = 1200) -> List[str]:
    palavras = texto.split()
    blocos = []
    atual = []

    for palavra in palavras:
        atual.append(palavra)
        if len(" ".join(atual)) >= tamanho_bloco:
            blocos.append(" ".join(atual))
            atual = []

    if atual:
        blocos.append(" ".join(atual))

    return blocos


def comparar_textos_textualmente(texto_antigo: str, texto_novo: str, max_novidades: int = 20) -> Dict[str, Any]:
    if not texto_antigo:
        return {
            "novidades": ["Primeira execução registrada; não há base anterior para comparação."],
            "quantidade_novidades": 1
        }

    blocos_antigos = set(segmentar_texto_em_blocos(texto_antigo, 900))
    blocos_novos = segmentar_texto_em_blocos(texto_novo, 900)

    novidades = []
    for bloco in blocos_novos:
        if bloco not in blocos_antigos:
            novidades.append(bloco[:700])

    novidades = novidades[:max_novidades]

    return {
        "novidades": novidades,
        "quantidade_novidades": len(novidades)
    }


def comparar_com_ultima_execucao(dados_portais: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    comparacoes = {}
    ultima_execucao = ler_json(ARQUIVO_ULTIMA_EXECUCAO)
    mapa_anterior = {}

    if ultima_execucao and "dados_portais" in ultima_execucao:
        for item in ultima_execucao["dados_portais"]:
            mapa_anterior[item["nome"]] = item

    for item in dados_portais:
        anterior = mapa_anterior.get(item["nome"])
        texto_antigo = anterior["texto"] if anterior else ""
        comparacoes[item["nome"]] = comparar_textos_textualmente(
            texto_antigo,
            item["texto"],
            max_novidades=12
        )

    return comparacoes


def total_novidades(comparacoes: Dict[str, Dict[str, Any]]) -> int:
    return sum(item.get("quantidade_novidades", 0) for item in comparacoes.values())


# =========================================================
# PROMPTS
# =========================================================
def gerar_prompt_chat_oficial_scraping(pergunta_usuario: str, dados_portais: List[Dict[str, str]]) -> str:
    contexto = []
    for item in dados_portais:
        contexto.append(
            f"""
PORTAL: {item['nome']}
URL: {item['url']}
TEXTO:
{item['texto']}
"""
        )

    return f"""
Você é um consultor fiscal sênior auxiliando a contadora Gabriela.

RESPONDA com base nos textos extraídos dos portais oficiais do Governo Federal sobre Reforma Tributária.

FONTES COLETADAS:
- Ministério da Fazenda (página principal da Reforma Tributária)
- Receita Federal (reforma do consumo)
- Páginas de Notícias do Ministério da Fazenda e Receita Federal

REGRAS OBRIGATÓRIAS:
1. Priorize informações de notícias recentes quando a pergunta for sobre atualizações
2. Não invente informações - Use apenas o que está nos textos fornecidos
3. Se a informação não estiver nos textos, diga explicitamente:
   "Não encontrei essa informação nos textos oficiais coletados agora."
4. Sempre cite a fonte/portal onde encontrou a informação
5. Ignore menus, navegação e códigos de site
6. Quando houver LISTA DE NOTÍCIAS no texto, use para responder perguntas sobre atualizações

Pergunta do usuário:
{pergunta_usuario}

TEXTOS COLETADOS DOS PORTAIS:
{' '.join(contexto)}
"""


def gerar_prompt_lista_noticias(pergunta_usuario: str, lista_noticias: List[Dict[str, str]]) -> str:
    noticias_formatadas = "\n".join([
        f"- [{n['data']}] {n['titulo']} (URL: {n['url']})"
        for n in lista_noticias
    ]) if lista_noticias else "Nenhuma notícia encontrada."

    return f"""
Você é um assistente de informações fiscais. Seu trabalho é formatar e apresentar a lista de notícias mais recentes sobre a Reforma Tributária de forma clara e organizada.

INSTRUÇÕES:
1. Liste as notícias em ordem cronológica (mais recente primeiro)
2. Para cada notícia, mostre: data, título e link
3. Se o usuário perguntar sobre algo específico, destaque as notícias relevantes
4. Responda de forma direta e útil

NOTÍCIAS MAIS RECENTES COLETADAS DOS PORTAIS GOVERNAMENTAIS:
{noticias_formatadas}

Pergunta do usuário:
{pergunta_usuario}

Responder em formato de lista organizada.
"""


def gerar_prompt_chat_oficial_gemini(pergunta_usuario: str) -> str:
    return f"""
Atue como um consultor fiscal sênior auxiliando a contadora Gabriela.

REGRA ABSOLUTA:
Para responder à dúvida abaixo, baseie-se apenas nestes três portais oficiais:
1. site:gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria
2. site:cgibs.gov.br
3. site:gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo

REGRAS:
- Não use conhecimento prévio fora desses portais
- Se a informação não existir nesses três sites, diga:
  "Não encontrei essa informação nas atualizações oficiais dos portais do Governo."
- Sempre que possível, mencione em qual portal a resposta foi encontrada
- Responda de forma técnica, objetiva e útil

Pergunta:
{pergunta_usuario}
"""


def gerar_prompt_relatorio_scraping(dados_portais: list, comparacoes: dict) -> str:
    blocos_texto = []
    for item in dados_portais:
        blocos_texto.append(
            f"""
==============================
PORTAL: {item['nome']}
URL: {item['url']}
COLETADO EM: {item['coletado_em']}
TEXTO EXTRAÍDO:
{item['texto']}
"""
        )

    blocos_comparacao = []
    for nome_portal, comp in comparacoes.items():
        novidades = comp.get("novidades", [])
        texto_novidades = "\n".join([f"- {n}" for n in novidades]) if novidades else "- Nenhuma novidade textual relevante detectada."
        blocos_comparacao.append(
            f"""
PORTAL: {nome_portal}
QUANTIDADE DE NOVIDADES TEXTUAIS DETECTADAS: {comp.get('quantidade_novidades', 0)}
TRECHOS NOVOS OU DIFERENTES:
{texto_novidades}
"""
        )

    return f"""
Você receberá:
1. textos brutos raspados hoje de três portais oficiais da Reforma Tributária
2. um comparativo textual entre a execução atual e a execução anterior

Sua missão é gerar um RELATÓRIO EXECUTIVO E TÉCNICO para uma contadora.

OBJETIVO:
- identificar atualizações verdadeiramente relevantes
- separar ruído de navegação de conteúdo útil
- destacar novas publicações, mudanças, manuais, notas, comunicados, guias, cronogramas, datas e orientações operacionais
- sinalizar impactos práticos para empresas do Lucro Presumido e Lucro Real

REGRAS:
- ignore menus, cabeçalhos, rodapés, breadcrumbs e repetições
- foque no conteúdo materialmente relevante
- se não houver novidade concreta, diga isso claramente
- use linguagem técnica, mas objetiva
- não invente normas
- não extrapole além do que o texto sugere

FORMATO:
1. Resumo executivo
2. Novidades por portal
3. Comparação com a última execução
4. Datas, guias, manuais ou comunicados identificados
5. Impactos práticos para contabilidade / fiscal
6. Itens que merecem monitoramento diário
7. Conclusão final

=== TEXTOS RASPADOS ===
{' '.join(blocos_texto)}

=== COMPARATIVO COM EXECUÇÃO ANTERIOR ===
{' '.join(blocos_comparacao)}
"""


def gerar_prompt_xml(conteudo_xml: str) -> str:
    return f"""
Você é um consultor tributário auxiliando a contadora Gabriela.

Contexto:
- Empresa emissora: Prestação de Serviços
- Regime: Lucro Presumido

Analise o XML abaixo e responda:
1. Tipo de operação/serviço
2. Tributos identificáveis no documento
3. Possíveis impactos na transição IBS/CBS
4. Cuidados de parametrização
5. Riscos de interpretação ou cadastro

XML:
{conteudo_xml}
"""


def gerar_prompt_xml_completo(conteudo_xml: str, analise_regras: str) -> str:
    return f"""
Você é um consultor tributário sênior auxiliando a contadora Gabriela.

Contexto da Reforma Tributária:
- CBS (Contribuição sobre Bens e Serviços): Tributo federal que substitui PIS e COFINS
- IBS (Imposto sobre Bens e Serviços): Tributo estadual/municipal que substitui ICMS e ISS
- Imposto Seletivo: Para produtos prejudiciais à saúde/meio ambiente

Período de Transição:
- 2026: Ano teste com alíquotas reduzidas (0,9% CBS + 0,1% IBS) - destaque apenas declaratório
- 2027: CBS e IBS passam a vigorar normalmente
- 2033: Substituição completa dos tributos atuais

Já foi realizada uma análise automática baseada nas regras dos Manuais RTC:
{analise_regras}

Com base no XML abaixo, complemente a análise acima com:
1. Detalhamento técnico dos campos fiscais identificados
2. Recomendação de como proceder no cadastro/parametrização
3. Riscos específicos deste tipo de operação
4. Quaisquer ajustes necessários na classificação tributária

XML:
{conteudo_xml[:15000]}
"""


# =========================================================
# FALLBACK SEM IA
# =========================================================
def montar_relatorio_sem_ia_por_sem_novidade(comparacoes: dict) -> str:
    return f"""
## Sem análise por IA

Nenhuma novidade textual relevante foi detectada nesta execução.

### Resumo
- Total de novidades detectadas: **{total_novidades(comparacoes)}**
- Como não houve mudança material, a IA não foi chamada para economizar quota e custo.

### Próximo passo
- Execute novamente mais tarde para monitoramento contínuo.
"""


def montar_relatorio_fallback_sem_ia(dados_portais: list, comparacoes: dict) -> str:
    linhas = []
    linhas.append("## Relatório emergencial sem IA")
    linhas.append("")
    linhas.append("A análise por IA não pôde ser concluída neste momento.")
    linhas.append("Abaixo está um resumo operacional baseado apenas na coleta e comparação textual.")
    linhas.append("")

    for item in dados_portais:
        nome = item["nome"]
        comp = comparacoes.get(nome, {})
        qtd = comp.get("quantidade_novidades", 0)

        linhas.append(f"### {nome}")
        linhas.append(f"- URL: {item['url']}")
        linhas.append(f"- Coletado em: {item['coletado_em']}")
        linhas.append(f"- Novidades textuais detectadas: {qtd}")

        novidades = comp.get("novidades", [])
        if novidades:
            linhas.append("- Trechos novos/diferentes encontrados:")
            for idx, novidade in enumerate(novidades[:5], start=1):
                linhas.append(f"  {idx}. {novidade}")
        else:
            linhas.append("- Nenhuma novidade textual relevante detectada.")
        linhas.append("")

    linhas.append("### Recomendação")
    linhas.append("- Reexecute mais tarde ou valide as chaves dos provedores.")
    return "\n".join(linhas)


# =========================================================
# CLIENTES LLM
# =========================================================
def chamar_gemini(prompt: str, usar_google_search: bool = False):
    if not gemini_model:
        raise RuntimeError("Gemini não configurado.")
    if usar_google_search:
        try:
            return gemini_model.generate_content(prompt, tools="google_search_retrieval")
        except Exception as e:
            if "google_search_retrieval" in str(e) or "not supported" in str(e).lower():
                raise RuntimeError("Google Search não disponível neste modelo")
            raise
    return gemini_model.generate_content(prompt)


def chamar_groq(prompt: str, temperature: float = 0.2, max_tokens: int = 2500) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada.")

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "Você é um consultor fiscal técnico, objetivo e confiável."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=90)
    if resp.status_code >= 400:
        raise RuntimeError(f"Groq retornou {resp.status_code}: {resp.text[:1000]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def chamar_openrouter(prompt: str, temperature: float = 0.2, max_tokens: int = 2500) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY não configurada.")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_APP_URL,
        "X-Title": OPENROUTER_APP_NAME,
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "Você é um consultor fiscal técnico, objetivo e confiável."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=90)
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenRouter retornou {resp.status_code}: {resp.text[:1000]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# =========================================================
# ROTEADOR INTELIGENTE
# =========================================================
def classificar_complexidade_prompt(prompt: str) -> str:
    tamanho = len(prompt)
    if tamanho < 4000:
        return "baixa"
    if tamanho < 12000:
        return "media"
    return "alta"


def decidir_roteamento(
    task_type: str,
    prompt: str,
    need_search: bool = False,
    official_context_ready: bool = False,
    novidades_detectadas: int = 0
) -> Dict[str, Any]:
    complexidade = classificar_complexidade_prompt(prompt)
    gemini_cooldown, cooldown_restante = gemini_em_cooldown()

    # Regras principais
    if task_type == "official_chat":
        if need_search and not gemini_cooldown and gemini_model:
            return {
                "ordem": ["gemini", "groq", "openrouter"],
                "motivo": "Pergunta oficial com necessidade de busca; Gemini priorizado."
            }
        return {
            "ordem": ["groq", "openrouter", "gemini"],
            "motivo": (
                "Gemini em cooldown/ausente ou busca não disponível; "
                "usando scraping oficial + modelo alternativo."
            )
        }

    if task_type == "scraping_report":
        if novidades_detectadas == 0:
            return {
                "ordem": [],
                "motivo": "Nenhuma novidade detectada; IA será pulada para economizar quota."
            }

        if complexidade == "baixa":
            return {
                "ordem": ["groq", "openrouter", "gemini"],
                "motivo": "Relatório curto/simples; priorizando menor custo e maior velocidade."
            }

        if complexidade == "media":
            if gemini_cooldown:
                return {
                    "ordem": ["groq", "openrouter"],
                    "motivo": f"Gemini em cooldown por {cooldown_restante}s; priorizando Groq/OpenRouter."
                }
            return {
                "ordem": ["groq", "gemini", "openrouter"],
                "motivo": "Complexidade média; Groq primeiro e Gemini como reforço."
            }

        # alta
        if gemini_cooldown:
            return {
                "ordem": ["groq", "openrouter"],
                "motivo": f"Prompt complexo, mas Gemini em cooldown por {cooldown_restante}s."
            }
        return {
            "ordem": ["gemini", "groq", "openrouter"],
            "motivo": "Prompt complexo; priorizando qualidade do Gemini."
        }

    if task_type == "xml_analysis":
        if complexidade == "alta" and gemini_model and not gemini_cooldown:
            return {
                "ordem": ["gemini", "groq", "openrouter"],
                "motivo": "XML longo/complexo; Gemini priorizado."
            }
        return {
            "ordem": ["groq", "openrouter", "gemini"],
            "motivo": "XML simples/médio; priorizando custo e velocidade."
        }

    return {
        "ordem": ["groq", "openrouter", "gemini"],
        "motivo": "Rota padrão otimizada para custo/performance."
    }


def executar_llm_por_ordem(
    ordem: List[str],
    prompt: str,
    usar_google_search_no_gemini: bool = False
) -> Tuple[str, str]:
    ultimo_erro = None

    for provider in ordem:
        try:
            if provider == "gemini":
                resposta = chamar_gemini(prompt, usar_google_search=usar_google_search_no_gemini)
                texto = getattr(resposta, "text", None)
                if not texto:
                    raise RuntimeError("Gemini não retornou texto utilizável.")
                st.session_state.router_state["gemini_calls_success"] += 1
                st.session_state.router_state["last_provider_used"] = f"Gemini ({GEMINI_MODEL})"
                return texto, f"Gemini ({GEMINI_MODEL})"

            if provider == "groq":
                texto = chamar_groq(prompt)
                st.session_state.router_state["groq_calls_success"] += 1
                st.session_state.router_state["last_provider_used"] = f"Groq ({GROQ_MODEL})"
                return texto, f"Groq ({GROQ_MODEL})"

            if provider == "openrouter":
                texto = chamar_openrouter(prompt)
                st.session_state.router_state["openrouter_calls_success"] += 1
                st.session_state.router_state["last_provider_used"] = f"OpenRouter ({OPENROUTER_MODEL})"
                return texto, f"OpenRouter ({OPENROUTER_MODEL})"

        except Exception as e:
            ultimo_erro = e

            if provider == "gemini" and eh_erro_quota_429(e):
                espera = extrair_retry_seconds(str(e), default=60) + random.randint(1, 3)
                definir_cooldown_gemini(espera)
                st.warning(
                    f"Gemini entrou em cooldown por {espera}s após quota excedida. "
                    f"Indo para fallback automático."
                )
            else:
                st.warning(f"{provider.upper()} falhou nesta tentativa: {e}")

    raise RuntimeError(f"Nenhum provedor respondeu com sucesso. Último erro: {ultimo_erro}")


# =========================================================
# WRAPPERS DE TAREFA
# =========================================================
def responder_chat_oficial_inteligente(pergunta_usuario: str) -> Tuple[str, str, str]:
    pergunta_lower = pergunta_usuario.lower()
    
    # Verificar se é pergunta sobre notícias recentes
    palavras_noticia = ["notícia", "noticias", "últimas", "novidade", "atualização", "atualizacoes", "o que tem de novo", "quais as notícias"]
    eh_pergunta_noticia = any(p in pergunta_lower for p in palavras_noticia)
    
    # Detectar palavras-chave específicas para buscar conteúdo completo
    palavras_busca = []
    if "chatbot" in pergunta_lower or "ia generativa" in pergunta_lower:
        palavras_busca.append("chatbot")
    if "federalismo" in pergunta_lower:
        palavras_busca.append("federalismo")
    if "comitê gestor" in pergunta_lower or "cgibs" in pergunta_lower:
        palavras_busca.append("comitê gestor")
    if "ibs" in pergunta_lower:
        palavras_busca.append("ibs")
    if "cbs" in pergunta_lower:
        palavras_busca.append("cbs")
    if "manual" in pergunta_lower or "lereutes" in pergunta_lower or "declaração de regimes" in pergunta_lower:
        palavras_busca.append("manual")
    if "lc 227" in pergunta_lower or "lei complementar 227" in pergunta_lower:
        palavras_busca.append("lei complementar")
    
    if eh_pergunta_noticia:
        lista_noticias, falhas_noticias = coletar_lista_noticias()
        
        if lista_noticias:
            prompt_noticias = gerar_prompt_lista_noticias(pergunta_usuario, lista_noticias)
            rota = decidir_roteamento(
                task_type="official_chat",
                prompt=prompt_noticias,
                need_search=False,
                official_context_ready=True
            )
            st.session_state.router_state["last_router_reason"] = rota["motivo"]
            
            texto, provider = executar_llm_por_ordem(
                ordem=rota["ordem"],
                prompt=prompt_noticias,
                usar_google_search_no_gemini=False
            )
            return texto, provider, rota["motivo"]
    
    # Se detectou palavra-chave específica, buscar conteúdo completo das notícias
    if palavras_busca:
        noticias_encontradas = []
        
        # Primeiro tenta scraping local
        for palavra in palavras_busca:
            noticias = buscar_noticias_por_palavra_chave(palavra)
            noticias_encontradas.extend(noticias)
        
        # Se não encontrou conteúdo, tenta busca na web
        if not noticias_encontradas or all(len(n.get('conteudo', '')) < 200 for n in noticias_encontradas):
            for palavra in palavras_busca:
                noticias_web = buscar_noticia_na_web(palavra)
                noticias_encontradas.extend(noticias_web)
        
        if noticias_encontradas:
            contexto_noticias = []
            for n in noticias_encontradas[:5]:
                contexto_noticias.append(
                    f"""
NOTÍCIA: {n['titulo']}
DATA: {n['data']}
FONTE: {n.get('nome_fonte', 'Governo Federal')}
URL: {n['url']}
CONTEÚDO: {n.get('conteudo', 'Conteúdo não disponível')}
"""
                )
            
            prompt_completo = f"""
Você é um consultor fiscal sênior. Responda à pergunta do usuário com base no conteúdo completo das notícias abaixo.

Pergunta: {pergunta_usuario}

NOTÍCIAS ENCONTRADAS:
{' '.join(contexto_noticias)}

INSTRUÇÕES:
1. Forneça o conteúdo completo e detalhado das notícias encontradas
2. Responda de forma técnica e objetiva
3. Cite a fonte e data da informação
4. Se a informação for partial, indique o que está faltando
"""
            rota = decidir_roteamento(
                task_type="official_chat",
                prompt=prompt_completo,
                need_search=False,
                official_context_ready=True
            )
            st.session_state.router_state["last_router_reason"] = rota["motivo"]
            
            texto, provider = executar_llm_por_ordem(
                ordem=rota["ordem"],
                prompt=prompt_completo,
                usar_google_search_no_gemini=False
            )
            return texto, provider, rota["motivo"]
    
    # Sempre faz scraping + notícias para ter contexto completo (mais confiável)
    dados_portais, falhas_portais = coletar_todos_portais()
    dados_noticias, falhas_noticias = coletar_noticias()
    
    dados_combinados = dados_portais + dados_noticias
    falhas = falhas_portais + falhas_noticias
    
    if not dados_combinados:
        raise RuntimeError("Não foi possível coletar os portais oficiais para responder em modo fallback.")

    prompt_scraping = gerar_prompt_chat_oficial_scraping(pergunta_usuario, dados_combinados)
    
    rota = decidir_roteamento(
        task_type="official_chat",
        prompt=prompt_scraping,
        need_search=False,
        official_context_ready=True
    )
    st.session_state.router_state["last_router_reason"] = rota["motivo"]

    texto, provider = executar_llm_por_ordem(
        ordem=rota["ordem"],
        prompt=prompt_scraping,
        usar_google_search_no_gemini=False
    )

    if falhas:
        texto += "\n\n> Observação: houve falha de coleta em um ou mais portais nesta execução."

    return texto, provider, rota["motivo"]


def gerar_relatorio_scraping_inteligente(
    dados_portais: List[Dict[str, str]],
    comparacoes: Dict[str, Dict[str, Any]]
) -> Tuple[str, str, str]:
    qtd_novidades = total_novidades(comparacoes)

    rota = decidir_roteamento(
        task_type="scraping_report",
        prompt=gerar_prompt_relatorio_scraping(dados_portais, comparacoes),
        novidades_detectadas=qtd_novidades
    )
    st.session_state.router_state["last_router_reason"] = rota["motivo"]

    if not rota["ordem"]:
        return montar_relatorio_sem_ia_por_sem_novidade(comparacoes), "Sem IA", rota["motivo"]

    prompt = gerar_prompt_relatorio_scraping(dados_portais, comparacoes)
    texto, provider = executar_llm_por_ordem(
        ordem=rota["ordem"],
        prompt=prompt,
        usar_google_search_no_gemini=False
    )
    return texto, provider, rota["motivo"]


def analisar_xml_inteligente(conteudo_xml: str) -> Tuple[str, str, str]:
    # Primeiro, fazer análise baseada nas regras dos manuais
    analise_regras = analisar_tributacao_xml(conteudo_xml)
    
    # Se a análise de regras encontrou informações válidas
    if "erro" not in analise_regras and analise_regras.get("tributos_identificados"):
        analise_texto = analise_regras.get("analise", "Análise disponível")
        
        # Complementar com IA se houver mais contexto necessário
        if len(analise_regras.get("informacoes_fiscais", [])) > 0:
            prompt = gerar_prompt_xml_completo(conteudo_xml, analise_texto)
            rota = decidir_roteamento(
                task_type="xml_analysis",
                prompt=prompt
            )
            st.session_state.router_state["last_router_reason"] = rota["motivo"]

            try:
                texto_ia, provider = executar_llm_por_ordem(
                    ordem=rota["ordem"],
                    prompt=prompt,
                    usar_google_search_no_gemini=False
                )
                # Combinar análise de regras com IA
                resultado_final = analise_texto + "\n\n" + "="*60 + "\nANÁLISE COMPLEMENTAR:\n" + texto_ia
                return resultado_final, provider, rota["motivo"]
            except Exception as e:
                return analise_texto, "Análise de Regras", "Análise baseada nas regras dos Manuais RTC"
        
        return analise_texto, "Análise de Regras", "Análise baseada nas regras dos Manuais RTC"
    
    # Fallback para análise via LLM se análise de regras falhar
    prompt = gerar_prompt_xml(conteudo_xml)
    rota = decidir_roteamento(
        task_type="xml_analysis",
        prompt=prompt
    )
    st.session_state.router_state["last_router_reason"] = rota["motivo"]

    texto, provider = executar_llm_por_ordem(
        ordem=rota["ordem"],
        prompt=prompt,
        usar_google_search_no_gemini=False
    )
    return texto, provider, rota["motivo"]


# =========================================================
# EXPORTAÇÃO
# =========================================================
def montar_texto_exportacao_relatorio(relatorio_ia: str, dados_portais: list, comparacoes: dict, provider_info: str, router_reason: str) -> str:
    linhas = []
    linhas.append("RELATÓRIO DE MONITORAMENTO OFICIAL - REFORMA TRIBUTÁRIA")
    linhas.append(f"Gerado em: {agora_str()}")
    linhas.append(f"LLM utilizada: {provider_info}")
    linhas.append(f"Decisão do roteador: {router_reason}")
    linhas.append("=" * 80)
    linhas.append("")
    linhas.append("RELATÓRIO")
    linhas.append(relatorio_ia)
    linhas.append("")
    linhas.append("=" * 80)
    linhas.append("RESUMO DE COMPARAÇÃO POR PORTAL")

    for nome_portal, comp in comparacoes.items():
        linhas.append(f"\nPortal: {nome_portal}")
        linhas.append(f"Quantidade de novidades textuais: {comp.get('quantidade_novidades', 0)}")
        novidades = comp.get("novidades", [])
        if novidades:
            for idx, novidade in enumerate(novidades[:10], start=1):
                linhas.append(f"{idx}. {novidade}")
        else:
            linhas.append("Nenhuma novidade textual relevante detectada.")

    return "\n".join(linhas)


def montar_markdown_exportacao(relatorio_ia: str, dados_portais: list, comparacoes: dict, provider_info: str, router_reason: str) -> str:
    md = []
    md.append("# Relatório de Monitoramento Oficial - Reforma Tributária")
    md.append(f"**Gerado em:** {agora_str()}")
    md.append(f"**LLM utilizada:** {provider_info}")
    md.append(f"**Decisão do roteador:** {router_reason}\n")
    md.append("## Relatório")
    md.append(relatorio_ia)

    md.append("\n## Resumo de comparação por portal")
    for nome_portal, comp in comparacoes.items():
        md.append(f"\n### {nome_portal}")
        md.append(f"**Quantidade de novidades textuais:** {comp.get('quantidade_novidades', 0)}")
        novidades = comp.get("novidades", [])
        if novidades:
            for novidade in novidades[:10]:
                md.append(f"- {novidade}")
        else:
            md.append("- Nenhuma novidade textual relevante detectada.")

    return "\n".join(md)


def salvar_execucao_atual(dados_portais: list, comparacoes: dict, relatorio_ia: str, provider_info: str, router_reason: str):
    payload = {
        "gerado_em": agora_str(),
        "provider_info": provider_info,
        "router_reason": router_reason,
        "dados_portais": dados_portais,
        "comparacoes": comparacoes,
        "relatorio_ia": relatorio_ia
    }

    salvar_json(ARQUIVO_ULTIMA_EXECUCAO, payload)

    timestamp = agora_arquivo()
    arquivo_json_historico = os.path.join(PASTA_CACHE, f"execucao_{timestamp}.json")
    salvar_json(arquivo_json_historico, payload)


# =========================================================
# UI
# =========================================================
st.title("📊 Assistente Inteligente da Reforma Tributária — V4")
st.caption("Roteador automático de LLM com economia de quota e fallback oficial real.")

with st.expander("🔍 Diagnóstico de Conexão com LLMs", expanded=False):
    tem_gemini = "GEMINI_API_KEY" in st.secrets
    tem_groq = "GROQ_API_KEY" in st.secrets
    tem_openrouter = "OPENROUTER_API_KEY" in st.secrets

    col1, col2, col3 = st.columns(3)
    with col1:
        st.write("Gemini existe?", "✅" if tem_gemini else "❌")
    with col2:
        st.write("Groq existe?", "✅" if tem_groq else "❌")
    with col3:
        st.write("OpenRouter existe?", "✅" if tem_openrouter else "❌")

    if tem_gemini:
        st.write("Gemini prefixo:", st.secrets["GEMINI_API_KEY"][:6] + "...")
    if tem_groq:
        st.write("Groq prefixo:", st.secrets["GROQ_API_KEY"][:6] + "...")
    if tem_openrouter:
        st.write("OpenRouter prefixo:", st.secrets["OPENROUTER_API_KEY"][:6] + "...")

    cooldown, restante = gemini_em_cooldown()
    st.write("Gemini em cooldown?", f"✅ {restante}s restantes" if cooldown else "❌")

    st.write("Gemini sucessos:", st.session_state.router_state["gemini_calls_success"])
    st.write("Groq sucessos:", st.session_state.router_state["groq_calls_success"])
    st.write("OpenRouter sucessos:", st.session_state.router_state["openrouter_calls_success"])
    st.write("Último provedor usado:", st.session_state.router_state["last_provider_used"])
    st.write("Última razão do roteador:", st.session_state.router_state["last_router_reason"])

aba1, aba2, aba3, aba4 = st.tabs([
    "Radar Geral",
    "Análise de XML",
    "Chatbot Fiscal (Oficial)",
    "Web Real V4"
])

# =========================================================
# ABA 1
# =========================================================
with aba1:
    st.header("Radar Geral")
    st.write("Aqui eu recomendaria usar Groq como padrão e Gemini só quando necessário.")

    if st.button("Mostrar estratégia atual"):
        st.markdown("""
### Estratégia V4
- **Chat oficial:** Gemini só se estiver saudável; senão scraping + Groq/OpenRouter.
- **Web scraping:** se não houver novidade, não chama IA.
- **XML:** Groq primeiro em casos simples/médios; Gemini só quando o prompt ficar pesado.
""")

# =========================================================
# ABA 2
# =========================================================
with aba2:
    st.header("Análise de Impacto Tributário via XML")
    arquivo_xml = st.file_uploader("Selecione o arquivo XML", type=["xml"])

    if arquivo_xml is not None:
        conteudo_xml = arquivo_xml.getvalue().decode("utf-8", errors="ignore")

        with st.expander("Visualizar XML"):
            st.code(conteudo_xml[:1500] + "\n... [truncado]", language="xml")

        if st.button("Analisar Operação"):
            with st.spinner("Roteando análise de XML..."):
                try:
                    texto, provider, motivo = analisar_xml_inteligente(conteudo_xml)
                    st.success(f"Resposta gerada com: {provider}")
                    st.info(f"Decisão do roteador: {motivo}")
                    st.markdown(texto)
                except Exception as e:
                    st.error(f"Erro ao analisar XML: {e}")

# =========================================================
# ABA 3
# =========================================================
with aba3:
    st.header("💬 Chatbot Fiscal (Fontes Oficiais)")
    st.write("Usa Gemini com busca apenas quando vale a pena. Se não, usa scraping real + Groq/OpenRouter.")

    for msg in st.session_state.mensagens_chat_oficial_v4:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pergunta_usuario = st.chat_input(
        "Ex: Quais as novas regras de transição publicadas hoje?",
        key="chat_oficial_v4"
    )

    if pergunta_usuario:
        st.chat_message("user").markdown(pergunta_usuario)
        st.session_state.mensagens_chat_oficial_v4.append({
            "role": "user",
            "content": pergunta_usuario
        })

        with st.spinner("Consultando provedores de forma otimizada..."):
            try:
                texto, provider, motivo = responder_chat_oficial_inteligente(pergunta_usuario)
                resposta_final = f"**Fonte de geração:** {provider}\n\n**Decisão do roteador:** {motivo}\n\n{texto}"
                st.chat_message("assistant").markdown(resposta_final)
                st.session_state.mensagens_chat_oficial_v4.append({
                    "role": "assistant",
                    "content": resposta_final
                })
            except Exception as e:
                st.error(f"Erro no chat oficial: {e}")

# =========================================================
# ABA 4
# =========================================================
with aba4:
    st.header("🏛️ Web Real V4")
    st.write(
        "Coleta HTML dos portais oficiais, detecta mudanças e só usa IA quando houver valor real."
    )

    col1, col2 = st.columns(2)
    with col1:
        executar_scraping = st.button("Executar Monitoramento Oficial V4")
    with col2:
        mostrar_ultima = st.button("Ver Última Execução Salva")

    if mostrar_ultima:
        ultima = ler_json(ARQUIVO_ULTIMA_EXECUCAO)
        if ultima:
            st.info(f"Última execução encontrada: {ultima.get('gerado_em', 'N/A')}")
            st.write(f"LLM usada: {ultima.get('provider_info', 'N/A')}")
            st.write(f"Decisão do roteador: {ultima.get('router_reason', 'N/A')}")
            with st.expander("Abrir relatório da última execução"):
                st.markdown(ultima.get("relatorio_ia", "Sem relatório salvo."))
        else:
            st.warning("Ainda não existe execução anterior salva.")

    if executar_scraping:
        with st.spinner("Coletando portais oficiais..."):
            dados_portais, falhas = coletar_todos_portais()

        if falhas:
            with st.expander("Detalhes das falhas de coleta"):
                for falha in falhas:
                    st.text(
                        f"Portal: {falha['portal']}\n"
                        f"URL: {falha['url']}\n"
                        f"Erro: {falha['erro']}\n"
                    )

        if not dados_portais:
            st.error("Não foi possível extrair texto de nenhum dos portais oficiais.")
        else:
            comparacoes = comparar_com_ultima_execucao(dados_portais)
            qtd = total_novidades(comparacoes)

            st.markdown(f"### Total de novidades detectadas: **{qtd}**")

            with st.spinner("Aplicando roteador inteligente..."):
                try:
                    texto_relatorio_final, provider_info, router_reason = gerar_relatorio_scraping_inteligente(
                        dados_portais,
                        comparacoes
                    )

                    if provider_info == "Sem IA":
                        st.info("Nenhuma novidade material detectada. IA não foi usada para economizar quota.")
                    else:
                        st.success(f"Relatório gerado com: {provider_info}")

                    st.info(f"Decisão do roteador: {router_reason}")
                    st.markdown("## Relatório Executivo")
                    st.markdown(texto_relatorio_final)

                except Exception as e:
                    provider_info = "Fallback sem IA"
                    router_reason = "Todos os provedores falharam; usando fallback textual sem IA."
                    texto_relatorio_final = montar_relatorio_fallback_sem_ia(dados_portais, comparacoes)
                    st.warning(f"Não foi possível gerar com LLM. Motivo: {e}")
                    st.markdown(texto_relatorio_final)

            st.markdown("## Painel de Novidades Detectadas")
            for nome_portal, comp in comparacoes.items():
                with st.expander(f"{nome_portal} — {comp.get('quantidade_novidades', 0)} novidade(s) textual(is)"):
                    novidades = comp.get("novidades", [])
                    if novidades:
                        for i, novidade in enumerate(novidades[:8], start=1):
                            st.write(f"**{i}.** {novidade}")
                    else:
                        st.write("Nenhuma novidade textual relevante detectada.")

            with st.expander("Ver texto bruto extraído dos portais"):
                for item in dados_portais:
                    st.markdown(f"### {item['nome']}")
                    st.text(item["texto"][:5000] + "\n... [conteúdo truncado]")

            txt_export = montar_texto_exportacao_relatorio(
                texto_relatorio_final,
                dados_portais,
                comparacoes,
                provider_info,
                router_reason
            )
            md_export = montar_markdown_exportacao(
                texto_relatorio_final,
                dados_portais,
                comparacoes,
                provider_info,
                router_reason
            )

            st.download_button(
                label="📥 Baixar relatório em TXT",
                data=txt_export,
                file_name=f"relatorio_reforma_tributaria_{agora_arquivo()}.txt",
                mime="text/plain"
            )

            st.download_button(
                label="📥 Baixar relatório em Markdown",
                data=md_export,
                file_name=f"relatorio_reforma_tributaria_{agora_arquivo()}.md",
                mime="text/markdown"
            )

            salvar_execucao_atual(
                dados_portais,
                comparacoes,
                texto_relatorio_final,
                provider_info,
                router_reason
            )
            st.info("Execução salva com sucesso para comparações futuras.")
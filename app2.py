import os
import re
import time
import json
import random
import hashlib
from datetime import datetime
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
    page_title="Assistente Fiscal - Gabriela | V3",
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

# =========================================================
# SECRETS / MODELOS
# =========================================================
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", "")

# Modelos default. Você pode trocar nos secrets se quiser.
GEMINI_MODEL = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = st.secrets.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_MODEL = st.secrets.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

# OpenRouter recomenda headers opcionais para identificação do app
OPENROUTER_APP_NAME = st.secrets.get("OPENROUTER_APP_NAME", "Assistente Fiscal Gabriela")
OPENROUTER_APP_URL = st.secrets.get("OPENROUTER_APP_URL", "https://localhost")

# =========================================================
# FUNÇÕES AUXILIARES - DATA / JSON / HASH
# =========================================================
def agora_str() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


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
        return None, None

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        return model, GEMINI_MODEL
    except Exception as e:
        st.warning(f"Gemini indisponível no carregamento: {e}")
        return None, None


gemini_model, gemini_model_name = configurar_gemini()

# =========================================================
# FUNÇÕES AUXILIARES - ERROS / RETRY
# =========================================================
def extrair_retry_seconds(mensagem_erro: str, default: int = 35) -> int:
    try:
        padrao = r"retry in\s+([0-9]+(?:\.[0-9]+)?)s"
        match = re.search(padrao, mensagem_erro, re.IGNORECASE)
        if match:
            return max(1, int(float(match.group(1))) + 1)
    except Exception:
        pass
    return default


def eh_erro_quota_429(erro: Exception) -> bool:
    mensagem = str(erro).lower()
    return (
        "429" in mensagem
        or "quota exceeded" in mensagem
        or "rate limit" in mensagem
        or "too many requests" in mensagem
    )


# =========================================================
# FUNÇÕES AUXILIARES - SCRAPING
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


def coletar_portal(nome: str, url: str) -> Dict[str, str]:
    texto = extrair_texto_da_url(url)
    return {
        "nome": nome,
        "url": url,
        "texto": texto,
        "hash": gerar_hash_texto(texto),
        "coletado_em": agora_str()
    }


# =========================================================
# FUNÇÕES AUXILIARES - COMPARAÇÃO
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


# =========================================================
# FUNÇÕES AUXILIARES - PROMPTS
# =========================================================
def gerar_prompt_chat_oficial(pergunta_usuario: str) -> str:
    return f"""
Atue como um consultor fiscal sênior auxiliando a contadora Gabriela.

REGRA ABSOLUTA:
Para responder à dúvida abaixo, você deve se basear apenas em informações desses três portais oficiais:
1. gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria
2. cgibs.gov.br
3. gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo

REGRAS DE RESPOSTA:
- Não use conhecimento prévio fora desses portais.
- Se a informação não existir nesses três sites, diga:
  "Não encontrei essa informação nas atualizações oficiais dos portais do Governo."
- Sempre que possível, mencione em qual portal a resposta foi encontrada.
- Responda de forma técnica, objetiva e útil para uma contadora.
- Se houver divergência entre portais, informe isso claramente.
- Priorize publicações normativas, comunicados, manuais, guias, datas de implantação e orientações operacionais.

Dúvida da Gabriela:
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

FORMATO OBRIGATÓRIO:
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


# =========================================================
# FALLBACK SEM IA
# =========================================================
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
    linhas.append("- Reexecute a análise depois ou valide suas chaves/provedores alternativos.")

    return "\n".join(linhas)


# =========================================================
# CLIENTES LLM - GROQ / OPENROUTER
# =========================================================
def chamar_groq_chat(prompt: str, temperature: float = 0.2, max_tokens: int = 2500) -> str:
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


def chamar_openrouter_chat(prompt: str, temperature: float = 0.2, max_tokens: int = 2500) -> str:
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


def chamar_gemini(prompt: str, usar_google_search: bool = False):
    if not gemini_model:
        raise RuntimeError("Gemini não configurado.")
    if usar_google_search:
        return gemini_model.generate_content(prompt, tools="google_search_retrieval")
    return gemini_model.generate_content(prompt)


def gerar_texto_com_fallback(
    prompt: str,
    usar_google_search_no_gemini: bool = False,
    max_tentativas_gemini: int = 3
) -> Tuple[str, str]:
    """
    Retorna (texto, provedor_usado)
    Ordem:
    1. Gemini
    2. Groq
    3. OpenRouter
    """
    # 1) GEMINI
    if gemini_model:
        ultimo_erro_gemini = None
        for tentativa in range(1, max_tentativas_gemini + 1):
            try:
                resposta = chamar_gemini(prompt, usar_google_search=usar_google_search_no_gemini)
                texto = getattr(resposta, "text", None)
                if not texto:
                    raise RuntimeError("Gemini não retornou texto utilizável.")
                return texto, f"Gemini ({GEMINI_MODEL})"
            except Exception as e:
                ultimo_erro_gemini = e
                if eh_erro_quota_429(e) and tentativa < max_tentativas_gemini:
                    espera = extrair_retry_seconds(str(e), default=35) + random.randint(1, 3)
                    with st.spinner(f"Gemini com cota temporariamente excedida. Aguardando {espera}s para retry ({tentativa}/{max_tentativas_gemini})..."):
                        time.sleep(espera)
                else:
                    break
        st.warning(f"Gemini indisponível nesta tentativa: {ultimo_erro_gemini}")

    # 2) GROQ
    if GROQ_API_KEY:
        try:
            texto = chamar_groq_chat(prompt)
            return texto, f"Groq ({GROQ_MODEL})"
        except Exception as e:
            st.warning(f"Groq indisponível nesta tentativa: {e}")

    # 3) OPENROUTER
    if OPENROUTER_API_KEY:
        try:
            texto = chamar_openrouter_chat(prompt)
            return texto, f"OpenRouter ({OPENROUTER_MODEL})"
        except Exception as e:
            st.warning(f"OpenRouter indisponível nesta tentativa: {e}")

    raise RuntimeError("Nenhum provedor LLM disponível no momento. Verifique GEMINI_API_KEY, GROQ_API_KEY e OPENROUTER_API_KEY.")


# =========================================================
# EXPORTAÇÃO
# =========================================================
def montar_texto_exportacao_relatorio(relatorio_ia: str, dados_portais: list, comparacoes: dict, provider_info: str) -> str:
    linhas = []
    linhas.append("RELATÓRIO DE MONITORAMENTO OFICIAL - REFORMA TRIBUTÁRIA")
    linhas.append(f"Gerado em: {agora_str()}")
    linhas.append(f"LLM utilizada: {provider_info}")
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

    linhas.append("\n" + "=" * 80)
    linhas.append("PORTAIS CONSULTADOS")

    for item in dados_portais:
        linhas.append(f"\nPortal: {item['nome']}")
        linhas.append(f"URL: {item['url']}")
        linhas.append(f"Coletado em: {item['coletado_em']}")
        linhas.append(f"Hash: {item['hash']}")

    return "\n".join(linhas)


def montar_markdown_exportacao(relatorio_ia: str, dados_portais: list, comparacoes: dict, provider_info: str) -> str:
    md = []
    md.append("# Relatório de Monitoramento Oficial - Reforma Tributária")
    md.append(f"**Gerado em:** {agora_str()}")
    md.append(f"**LLM utilizada:** {provider_info}\n")
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

    md.append("\n## Portais consultados")
    for item in dados_portais:
        md.append(f"\n### {item['nome']}")
        md.append(f"- **URL:** {item['url']}")
        md.append(f"- **Coletado em:** {item['coletado_em']}")
        md.append(f"- **Hash:** `{item['hash']}`")

    return "\n".join(md)


def salvar_execucao_atual(dados_portais: list, comparacoes: dict, relatorio_ia: str, provider_info: str):
    payload = {
        "gerado_em": agora_str(),
        "provider_info": provider_info,
        "dados_portais": dados_portais,
        "comparacoes": comparacoes,
        "relatorio_ia": relatorio_ia
    }

    salvar_json(ARQUIVO_ULTIMA_EXECUCAO, payload)

    timestamp = agora_arquivo()
    arquivo_json_historico = os.path.join(PASTA_CACHE, f"execucao_{timestamp}.json")
    salvar_json(arquivo_json_historico, payload)


# =========================================================
# INTERFACE
# =========================================================
st.title("📊 Assistente Inteligente da Reforma Tributária — V3")
# =========================================================
# 🔍 DIAGNÓSTICO DE CHAVES (DEBUG LLMs)
# =========================================================
with st.expander("🔍 Diagnóstico de Conexão com LLMs (Debug)", expanded=False):

    st.markdown("### 🔐 Verificação de Secrets")

    tem_groq = "GROQ_API_KEY" in st.secrets
    tem_openrouter = "OPENROUTER_API_KEY" in st.secrets
    tem_gemini = "GEMINI_API_KEY" in st.secrets

    col1, col2, col3 = st.columns(3)

    with col1:
        st.write("Gemini existe?", "✅" if tem_gemini else "❌")

    with col2:
        st.write("Groq existe?", "✅" if tem_groq else "❌")

    with col3:
        st.write("OpenRouter existe?", "✅" if tem_openrouter else "❌")

    st.markdown("---")

    st.markdown("### 🔎 Prefixos das Chaves (seguro)")

    if tem_gemini:
        st.write("Gemini prefixo:", st.secrets["GEMINI_API_KEY"][:6] + "...")

    if tem_groq:
        st.write("Groq prefixo:", st.secrets["GROQ_API_KEY"][:6] + "...")

    if tem_openrouter:
        st.write("OpenRouter prefixo:", st.secrets["OPENROUTER_API_KEY"][:6] + "...")

    st.markdown("---")

    st.markdown("### ⚠️ Diagnóstico Inteligente")

    if not tem_groq and not tem_openrouter:
        st.error("❌ Nenhum fallback configurado (Groq/OpenRouter). Seu sistema depende só do Gemini.")

    elif tem_groq and not tem_openrouter:
        st.warning("⚠️ Apenas Groq configurado. OpenRouter ainda não está ativo.")

    elif not tem_groq and tem_openrouter:
        st.warning("⚠️ Apenas OpenRouter configurado. Groq ainda não está ativo.")

    elif tem_groq and tem_openrouter:
        st.success("✅ Fallback completo ativo (Gemini + Groq + OpenRouter)")

    if not tem_gemini:
        st.error("❌ Gemini não configurado — você perderá o grounding (busca web)")

    st.markdown("---")

    st.markdown("### 🧠 Possíveis Problemas")

    if not tem_groq or not tem_openrouter:
        st.info("""
Se a chave está correta mas aparece como ❌:

1. Verifique se colocou no **Streamlit Cloud (Secrets)** e não só local
2. Confirme o nome EXATO:
   - GROQ_API_KEY
   - OPENROUTER_API_KEY
3. Reinicie o app (Deploy → Reboot)
4. Verifique se o arquivo TOML não tem erro de sintaxe
""")

st.caption("Scraping oficial + fallback real de LLM: Gemini → Groq → OpenRouter")

with st.expander("Status dos provedores configurados"):
    st.write(f"Gemini: {'✅ configurado' if GEMINI_API_KEY else '❌ ausente'}")
    st.write(f"Groq: {'✅ configurado' if GROQ_API_KEY else '❌ ausente'}")
    st.write(f"OpenRouter: {'✅ configurado' if OPENROUTER_API_KEY else '❌ ausente'}")
    st.write(f"Modelo Gemini: {GEMINI_MODEL}")
    st.write(f"Modelo Groq: {GROQ_MODEL}")
    st.write(f"Modelo OpenRouter: {OPENROUTER_MODEL}")

aba1, aba2, aba3, aba4 = st.tabs([
    "Radar Geral",
    "Análise de XML",
    "Chatbot Fiscal (Oficial)",
    "Web Real V3"
])

# =========================================================
# ABA 1 - RADAR GERAL
# =========================================================
with aba1:
    st.header("Radar de Atualizações")
    st.write("Usa Gemini com busca quando possível; se falhar, cai para outros provedores.")

    if st.button("Buscar panorama do dia"):
        prompt_busca = """
Pesquise e resuma as últimas atualizações sobre a Reforma Tributária no Brasil,
com foco em IBS, CBS, SPED, EFD-Reinf e DCTFWeb.
Escreva para uma contadora de Lucro Presumido e Lucro Real.
"""
        with st.spinner("Consultando LLMs..."):
            try:
                texto, provider_info = gerar_texto_com_fallback(
                    prompt_busca,
                    usar_google_search_no_gemini=True,
                    max_tentativas_gemini=3
                )
                st.success(f"Resposta gerada com: {provider_info}")
                st.markdown(texto)
            except Exception as e:
                st.error(f"Erro ao consultar os provedores: {e}")

# =========================================================
# ABA 2 - XML
# =========================================================
with aba2:
    st.header("Análise de Impacto Tributário via XML")
    st.write("Analisa o XML com fallback de provedores.")

    arquivo_xml = st.file_uploader("Selecione o arquivo XML", type=["xml"])

    if arquivo_xml is not None:
        conteudo_xml = arquivo_xml.getvalue().decode("utf-8", errors="ignore")

        with st.expander("Visualizar XML"):
            st.code(conteudo_xml[:1500] + "\n... [truncado]", language="xml")

        if st.button("Analisar Operação"):
            prompt_analise = f"""
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
            with st.spinner("Analisando XML..."):
                try:
                    texto, provider_info = gerar_texto_com_fallback(prompt_analise)
                    st.success(f"Análise gerada com: {provider_info}")
                    st.markdown(texto)
                except Exception as e:
                    st.error(f"Erro ao analisar XML: {e}")

# =========================================================
# ABA 3 - CHAT OFICIAL
# =========================================================
with aba3:
    st.header("💬 Chatbot Fiscal (Fontes Oficiais)")
    st.write("Prioriza Gemini com busca. Se falhar, tenta Groq e OpenRouter com o mesmo prompt restritivo.")

    if "mensagens_chat_oficial_v3" not in st.session_state:
        st.session_state.mensagens_chat_oficial_v3 = []

    for msg in st.session_state.mensagens_chat_oficial_v3:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pergunta_usuario = st.chat_input(
        "Ex: Quais as novas regras de transição publicadas hoje?",
        key="chat_oficial_v3"
    )

    if pergunta_usuario:
        st.chat_message("user").markdown(pergunta_usuario)
        st.session_state.mensagens_chat_oficial_v3.append({
            "role": "user",
            "content": pergunta_usuario
        })

        prompt_chat = gerar_prompt_chat_oficial(pergunta_usuario)

        with st.spinner("Consultando provedores..."):
            try:
                texto, provider_info = gerar_texto_com_fallback(
                    prompt_chat,
                    usar_google_search_no_gemini=True,
                    max_tentativas_gemini=3
                )
                resposta_final = f"**Fonte de geração:** {provider_info}\n\n{texto}"
                st.chat_message("assistant").markdown(resposta_final)
                st.session_state.mensagens_chat_oficial_v3.append({
                    "role": "assistant",
                    "content": resposta_final
                })
            except Exception as e:
                st.error(f"Erro no chat oficial: {e}")

# =========================================================
# ABA 4 - WEB REAL V3
# =========================================================
with aba4:
    st.header("🏛️ Web Real V3")
    st.write(
        "Coleta HTML dos portais oficiais, extrai texto, compara com a última execução, "
        "e gera relatório com fallback real: Gemini → Groq → OpenRouter."
    )

    col1, col2 = st.columns(2)
    with col1:
        executar_scraping = st.button("Executar Monitoramento Oficial V3")
    with col2:
        mostrar_ultima = st.button("Ver Última Execução Salva")

    if mostrar_ultima:
        ultima = ler_json(ARQUIVO_ULTIMA_EXECUCAO)
        if ultima:
            st.info(f"Última execução encontrada: {ultima.get('gerado_em', 'N/A')}")
            st.write(f"LLM usada na última execução: {ultima.get('provider_info', 'N/A')}")
            with st.expander("Abrir relatório da última execução"):
                st.markdown(ultima.get("relatorio_ia", "Sem relatório salvo."))
        else:
            st.warning("Ainda não existe execução anterior salva.")

    if executar_scraping:
        dados_portais = []
        comparacoes = {}
        falhas = []
        provider_info = "Nenhuma"
        texto_relatorio_final = ""

        ultima_execucao = ler_json(ARQUIVO_ULTIMA_EXECUCAO)
        mapa_anterior = {}

        if ultima_execucao and "dados_portais" in ultima_execucao:
            for item in ultima_execucao["dados_portais"]:
                mapa_anterior[item["nome"]] = item

        with st.spinner("Iniciando coleta com tratamento avançado de conexão e compatibilidade TLS..."):
            for portal in URLS_OFICIAIS:
                nome = portal["nome"]
                url = portal["url"]

                try:
                    item_atual = coletar_portal(nome, url)
                    dados_portais.append(item_atual)

                    item_antigo = mapa_anterior.get(nome)
                    texto_antigo = item_antigo["texto"] if item_antigo else ""
                    comparacao = comparar_textos_textualmente(
                        texto_antigo,
                        item_atual["texto"],
                        max_novidades=12
                    )
                    comparacoes[nome] = comparacao

                    st.toast(f"✅ Coleta concluída: {nome}")
                except Exception as e:
                    falhas.append({"portal": nome, "url": url, "erro": str(e)})
                    comparacoes[nome] = {"novidades": [], "quantidade_novidades": 0}
                    st.warning(f"Falha ao acessar {nome}")

        if falhas:
            with st.expander("Detalhes das falhas de coleta"):
                for falha in falhas:
                    st.text(
                        f"Portal: {falha['portal']}\n"
                        f"URL: {falha['url']}\n"
                        f"Erro: {falha['erro']}\n"
                    )

        if dados_portais:
            prompt_relatorio = gerar_prompt_relatorio_scraping(dados_portais, comparacoes)

            with st.spinner("Gerando relatório analítico..."):
                try:
                    texto_relatorio_final, provider_info = gerar_texto_com_fallback(
                        prompt_relatorio,
                        usar_google_search_no_gemini=False,
                        max_tentativas_gemini=3
                    )
                    st.success(f"Relatório gerado com: {provider_info}")
                    st.markdown("## Relatório Executivo")
                    st.markdown(texto_relatorio_final)

                except Exception as e:
                    st.warning(f"Não foi possível gerar com LLM. Motivo: {e}")
                    provider_info = "Fallback sem IA"
                    texto_relatorio_final = montar_relatorio_fallback_sem_ia(dados_portais, comparacoes)
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
                provider_info
            )
            md_export = montar_markdown_exportacao(
                texto_relatorio_final,
                dados_portais,
                comparacoes,
                provider_info
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

            salvar_execucao_atual(dados_portais, comparacoes, texto_relatorio_final, provider_info)
            st.info("Execução salva com sucesso para comparações futuras.")
        else:
            st.error("Não foi possível extrair texto de nenhum dos portais oficiais no momento.")
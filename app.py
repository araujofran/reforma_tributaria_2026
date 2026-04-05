import time
import streamlit as st
import google.generativeai as genai
from bs4 import BeautifulSoup
from curl_cffi import requests as requests_cffi
import requests

# ==========================================
# CONFIGURAÇÃO GERAL
# ==========================================
st.set_page_config(page_title="Assistente Fiscal - Gabriela", layout="wide")

HEADERS = {
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
    "https://www.gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria",
    "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo",
    "https://www.cgibs.gov.br/"
]

# ==========================================
# FUNÇÕES AUXILIARES
# ==========================================
def configurar_modelo():
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

        modelo_escolhido = None
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                modelo_escolhido = m.name
                if "pro" in m.name.lower() or "flash" in m.name.lower():
                    break

        if modelo_escolhido:
            return genai.GenerativeModel(modelo_escolhido)
        else:
            st.error("ERRO: Nenhum modelo disponível para esta chave de API.")
            st.stop()

    except KeyError:
        st.error("ERRO: A variável 'GEMINI_API_KEY' não foi encontrada nos Secrets do Streamlit.")
        st.stop()
    except Exception as e:
        st.error(f"ERRO DE CONEXÃO COM A API: {e}")
        st.stop()


def baixar_html_com_curl_cffi(url: str) -> str:
    sess = requests_cffi.Session()
    resp = sess.get(
        url,
        headers=HEADERS,
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
        headers=HEADERS,
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
        except Exception as e1:
            ultimo_erro = e1
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

    for tag in soup(["script", "style", "noscript", "svg", "img", "header", "footer"]):
        tag.decompose()

    texto = soup.get_text(separator=" ", strip=True)

    while "  " in texto:
        texto = texto.replace("  ", " ")

    return texto


def extrair_texto_da_url(url: str, limite_chars: int = 15000) -> str:
    html = baixar_html(url)
    texto = limpar_html_para_texto(html)
    return texto[:limite_chars]


def gerar_prompt_analise_scraping(textos_extraidos: str) -> str:
    return f"""
Você receberá abaixo o texto bruto extraído hoje dos portais oficiais:
1. Ministério da Fazenda
2. Receita Federal
3. CGIBS

Sua tarefa:
- analisar o conteúdo
- identificar ATUALIZAÇÕES, MANUAIS, DATAS, NOTAS, GUIAS, LEGISLAÇÕES e NOVIDADES TÉCNICAS relacionadas à Reforma Tributária
- ignorar menus, rodapés, itens repetidos e navegação do site
- entregar um relatório claro, objetivo e técnico para uma contadora

Formato da resposta:
1. Resumo executivo
2. Novidades identificadas por portal
3. Datas e publicações relevantes
4. Impactos práticos para empresas do Lucro Presumido e Lucro Real
5. O que merece acompanhamento imediato

TEXTOS EXTRAÍDOS DOS SITES:
{textos_extraidos}
"""


# ==========================================
# MODELO
# ==========================================
model = configurar_modelo()

# ==========================================
# INTERFACE
# ==========================================
st.title("📊 Assistente Inteligente da Reforma Tributária")

aba1, aba2, aba3, aba4 = st.tabs([
    "Radar Geral (Google)",
    "Análise de XML (IBS/CBS)",
    "Chatbot Fiscal (Oficial)",
    "Web Real (Scraping Oficial)"
])

# ------------------------------------------
# ABA 1: ATUALIZAÇÕES COM GOOGLE SEARCH GROUNDING
# ------------------------------------------
with aba1:
    st.header("Radar de Atualizações (Via Google)")
    st.write("Pesquisa nas principais fontes da internet em tempo real usando a busca do Google.")

    if st.button("Buscar no Google Hoje"):
        with st.spinner("Pesquisando na web..."):
            prompt_busca = """
Pesquise no Google as últimas atualizações sobre a Reforma Tributária no Brasil,
focando em regras do IBS, CBS, SPED, EFD-Reinf e DCTFWeb para o ano atual.
Resuma as mudanças para uma contadora de Lucro Presumido e Real.
"""
            try:
                resposta = model.generate_content(prompt_busca, tools="google_search_retrieval")
                st.success("Relatório gerado com dados atualizados da Web!")
                st.markdown(resposta.text)
            except Exception:
                st.warning("Busca ao vivo restrita. Utilizando a base interna do modelo.")
                resposta_fallback = model.generate_content(prompt_busca)
                st.markdown(resposta_fallback.text)

# ------------------------------------------
# ABA 2: ANÁLISE DE XML DA NOTA FISCAL
# ------------------------------------------
with aba2:
    st.header("Análise de Impacto Tributário via XML")
    st.write("Verifique a tributação de transição (IBS/CBS) subindo o arquivo da nota.")

    arquivo_xml = st.file_uploader("Selecione o arquivo XML", type=["xml"])

    if arquivo_xml is not None:
        conteudo_xml = arquivo_xml.getvalue().decode("utf-8", errors="ignore")

        with st.expander("Visualizar XML"):
            st.code(conteudo_xml[:1000] + "\n... [truncado]", language="xml")

        if st.button("Analisar Operação"):
            with st.spinner("Analisando regras do IVA Dual..."):
                prompt_analise = f"""
Você é um consultor ajudando uma contadora (Gabriela).
Empresa emissora: Prestação de Serviços (Lucro Presumido).

Analise este XML:
{conteudo_xml}

Responda de forma objetiva:
1. Tipo de serviço/operação identificado
2. Impostos atuais aparentes no XML
3. Como a operação tende a ficar no IBS/CBS
4. Cuidados de parametrização fiscal e sistêmica
5. Pontos de atenção para transição tributária
"""
                try:
                    resposta_xml = model.generate_content(prompt_analise)
                    st.success("Análise Fiscal Concluída!")
                    st.markdown(resposta_xml.text)
                except Exception as e:
                    st.error(f"Erro ao analisar o arquivo: {e}")

# ------------------------------------------
# ABA 3: CHATBOT FISCAL RESTRITO AOS SITES OFICIAIS
# ------------------------------------------
with aba3:
    st.header("💬 Tire dúvidas com a IA Fiscal (Fontes Oficiais)")
    st.write("Respostas baseadas estritamente no Ministério da Fazenda, Receita Federal e CGIBS.")

    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []

    for msg in st.session_state.mensagens:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pergunta_usuario = st.chat_input("Ex: Quais as novas regras de transição publicadas hoje?")

    if pergunta_usuario:
        st.chat_message("user").markdown(pergunta_usuario)
        st.session_state.mensagens.append({"role": "user", "content": pergunta_usuario})

        with st.spinner("Consultando os 3 portais oficiais do governo em tempo real..."):
            try:
                comando_oculto = f"""
Atue como um consultor fiscal sênior auxiliando a contadora Gabriela.

REGRA ABSOLUTA:
Para responder à dúvida abaixo, você é OBRIGADO a pesquisar na internet e basear sua resposta APENAS nos dados encontrados nestes três sites exatos:

1. site:gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria
2. site:cgibs.gov.br
3. site:gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo

REGRAS DE RESPOSTA:
- Não use conhecimento prévio.
- Não use fontes diferentes desses três portais.
- Se a informação não existir nesses três sites, diga exatamente:
  "Não encontrei essa informação nas atualizações oficiais de hoje dos portais do Governo."
- Sempre que possível, mencione em qual dos três portais a resposta foi encontrada.
- Responda de forma técnica, objetiva e útil para uma contadora.

Dúvida da Gabriela:
{pergunta_usuario}
"""

                try:
                    resposta_chat = model.generate_content(
                        comando_oculto,
                        tools="google_search_retrieval"
                    )
                except Exception:
                    resposta_chat = model.generate_content(comando_oculto)

                st.chat_message("assistant").markdown(resposta_chat.text)
                st.session_state.mensagens.append({"role": "assistant", "content": resposta_chat.text})

            except Exception as e:
                st.error(f"Erro no chat: {e}")

# ------------------------------------------
# ABA 4: WEB REAL (WEB SCRAPING)
# ------------------------------------------
with aba4:
    st.header("Monitoramento Direto (Scraping Oficial)")
    st.write(
        "Acessa o HTML das páginas oficiais do Governo, extrai o texto bruto "
        "e analisa se há novas publicações normativas relacionadas à Reforma Tributária."
    )

    if st.button("Executar Web Scraping nos Portais do Governo"):
        textos_extraidos = ""
        falhas = []

        with st.spinner("Iniciando coleta com tratamento avançado de conexão e compatibilidade TLS..."):
            for url in URLS_OFICIAIS:
                try:
                    texto_limpo = extrair_texto_da_url(url, limite_chars=15000)

                    textos_extraidos += f"\n\n--- TEXTO EXTRAÍDO DA URL: {url} ---\n"
                    textos_extraidos += texto_limpo

                    st.toast(f"✅ Sucesso ao ler: {url}")

                except Exception as erro_scraping:
                    falhas.append((url, str(erro_scraping)))
                    st.warning(f"Falha ao acessar {url}")

        if falhas:
            with st.expander("Ver detalhes das falhas de leitura"):
                for url, erro in falhas:
                    st.text(f"URL: {url}\nErro: {erro}\n")

        if textos_extraidos.strip():
            with st.spinner("Enviando os textos oficiais para leitura e interpretação da IA..."):
                prompt_scraping = gerar_prompt_analise_scraping(textos_extraidos)

                try:
                    relatorio_scraping = model.generate_content(prompt_scraping)
                    st.success("Scraping e análise concluídos com sucesso!")

                    with st.expander("Ver texto bruto extraído"):
                        st.text(textos_extraidos[:5000] + "\n... [texto longo ocultado]")

                    st.markdown("### 🏛️ Relatório Oficial Baseado nos Portais")
                    st.markdown(relatorio_scraping.text)

                except Exception as e:
                    st.error(f"Erro na geração da IA após o scraping: {e}")
        else:
            st.error("Não foi possível extrair texto de nenhum dos portais oficiais no momento.")
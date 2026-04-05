import os
import re
import time
import json
import hashlib
from datetime import datetime

import streamlit as st
import google.generativeai as genai
from bs4 import BeautifulSoup
from curl_cffi import requests as requests_cffi
import requests

# =========================================================
# CONFIGURAÇÃO GERAL
# =========================================================
st.set_page_config(
    page_title="Assistente Fiscal - Gabriela",
    layout="wide"
)

PASTA_CACHE = "cache_scraping"
ARQUIVO_ULTIMA_EXECUCAO = os.path.join(PASTA_CACHE, "ultima_execucao.json")
os.makedirs(PASTA_CACHE, exist_ok=True)

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
# FUNÇÕES AUXILIARES - GEMINI
# =========================================================
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


# =========================================================
# FUNÇÕES AUXILIARES - ARQUIVOS / CACHE
# =========================================================
def agora_str():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def agora_arquivo():
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


def caminho_cache_portal(nome_portal: str) -> str:
    nome_limpo = re.sub(r"[^a-zA-Z0-9_]+", "_", nome_portal.lower()).strip("_")
    return os.path.join(PASTA_CACHE, f"{nome_limpo}.json")


# =========================================================
# FUNÇÕES AUXILIARES - SCRAPING
# =========================================================
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

    # limpeza básica
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def segmentar_texto_em_blocos(texto: str, tamanho_bloco: int = 1200):
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


def comparar_textos_textualmente(texto_antigo: str, texto_novo: str, max_novidades: int = 20):
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


def extrair_texto_da_url(url: str, limite_chars: int = 18000) -> str:
    html = baixar_html(url)
    texto = limpar_html_para_texto(html)
    return texto[:limite_chars]


def coletar_portal(nome: str, url: str):
    texto = extrair_texto_da_url(url)
    hash_texto = gerar_hash_texto(texto)
    timestamp = agora_str()

    return {
        "nome": nome,
        "url": url,
        "texto": texto,
        "hash": hash_texto,
        "coletado_em": timestamp
    }


# =========================================================
# FUNÇÕES AUXILIARES - PROMPTS
# =========================================================
def gerar_prompt_chat_oficial(pergunta_usuario: str) -> str:
    return f"""
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


def gerar_prompt_resumo_novidades(comparacoes: dict) -> str:
    return f"""
Com base neste dicionário de comparação entre scraping atual e anterior:
{json.dumps(comparacoes, ensure_ascii=False, indent=2)}

Resuma em linguagem executiva:
- quais portais tiveram mudança
- se a mudança parece relevante ou apenas estrutural
- o que deve ser monitorado no próximo ciclo
"""


# =========================================================
# FUNÇÕES AUXILIARES - RELATÓRIOS / EXPORTAÇÃO
# =========================================================
def montar_texto_exportacao_relatorio(relatorio_ia: str, dados_portais: list, comparacoes: dict) -> str:
    linhas = []
    linhas.append("RELATÓRIO DE MONITORAMENTO OFICIAL - REFORMA TRIBUTÁRIA")
    linhas.append(f"Gerado em: {agora_str()}")
    linhas.append("=" * 80)
    linhas.append("")
    linhas.append("RELATÓRIO IA")
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


def montar_markdown_exportacao(relatorio_ia: str, dados_portais: list, comparacoes: dict) -> str:
    md = []
    md.append("# Relatório de Monitoramento Oficial - Reforma Tributária")
    md.append(f"**Gerado em:** {agora_str()}\n")
    md.append("## Relatório IA")
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


def salvar_execucao_atual(dados_portais: list, comparacoes: dict, relatorio_ia: str):
    payload = {
        "gerado_em": agora_str(),
        "dados_portais": dados_portais,
        "comparacoes": comparacoes,
        "relatorio_ia": relatorio_ia
    }
    salvar_json(ARQUIVO_ULTIMA_EXECUCAO, payload)

    timestamp = agora_arquivo()
    arquivo_json_historico = os.path.join(PASTA_CACHE, f"execucao_{timestamp}.json")
    salvar_json(arquivo_json_historico, payload)


# =========================================================
# MODELO
# =========================================================
model = configurar_modelo()

# =========================================================
# INTERFACE
# =========================================================
st.title("📊 Assistente Inteligente da Reforma Tributária")
st.caption("Monitoramento oficial focado em Ministério da Fazenda, Receita Federal e CGIBS.")

aba1, aba2, aba3, aba4 = st.tabs([
    "Radar Geral (Google)",
    "Análise de XML (IBS/CBS)",
    "Chatbot Fiscal (Oficial)",
    "Web Real V2 (Scraping Oficial)"
])

# =========================================================
# ABA 1
# =========================================================
with aba1:
    st.header("Radar de Atualizações (Via Google)")
    st.write("Pesquisa ampla na internet em tempo real.")

    if st.button("Buscar no Google Hoje"):
        with st.spinner("Pesquisando na web..."):
            prompt_busca = """
Pesquise no Google as últimas atualizações sobre a Reforma Tributária no Brasil,
focando em IBS, CBS, SPED, EFD-Reinf e DCTFWeb para o ano atual.
Resuma as mudanças para uma contadora de Lucro Presumido e Real.
"""
            try:
                resposta = model.generate_content(prompt_busca, tools="google_search_retrieval")
                st.success("Relatório gerado com dados atualizados da Web!")
                st.markdown(resposta.text)
            except Exception:
                st.warning("Busca ao vivo indisponível. Utilizando resposta sem grounding.")
                resposta = model.generate_content(prompt_busca)
                st.markdown(resposta.text)

# =========================================================
# ABA 2
# =========================================================
with aba2:
    st.header("Análise de Impacto Tributário via XML")
    st.write("Verifique a tributação de transição (IBS/CBS) com upload do XML.")

    arquivo_xml = st.file_uploader("Selecione o arquivo XML", type=["xml"])

    if arquivo_xml is not None:
        conteudo_xml = arquivo_xml.getvalue().decode("utf-8", errors="ignore")

        with st.expander("Visualizar XML"):
            st.code(conteudo_xml[:1500] + "\n... [truncado]", language="xml")

        if st.button("Analisar Operação"):
            with st.spinner("Analisando XML..."):
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
                try:
                    resposta_xml = model.generate_content(prompt_analise)
                    st.success("Análise concluída!")
                    st.markdown(resposta_xml.text)
                except Exception as e:
                    st.error(f"Erro ao analisar o XML: {e}")

# =========================================================
# ABA 3
# =========================================================
with aba3:
    st.header("💬 Tire dúvidas com a IA Fiscal (Fontes Oficiais)")
    st.write("Respostas baseadas estritamente no Ministério da Fazenda, Receita Federal e CGIBS.")

    if "mensagens_chat_oficial" not in st.session_state:
        st.session_state.mensagens_chat_oficial = []

    for msg in st.session_state.mensagens_chat_oficial:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pergunta_usuario = st.chat_input("Ex: Quais as novas regras de transição publicadas hoje?", key="chat_oficial")

    if pergunta_usuario:
        st.chat_message("user").markdown(pergunta_usuario)
        st.session_state.mensagens_chat_oficial.append({"role": "user", "content": pergunta_usuario})

        with st.spinner("Consultando os 3 portais oficiais do governo em tempo real..."):
            try:
                prompt_chat = gerar_prompt_chat_oficial(pergunta_usuario)

                try:
                    resposta_chat = model.generate_content(prompt_chat, tools="google_search_retrieval")
                except Exception:
                    resposta_chat = model.generate_content(prompt_chat)

                st.chat_message("assistant").markdown(resposta_chat.text)
                st.session_state.mensagens_chat_oficial.append({"role": "assistant", "content": resposta_chat.text})

            except Exception as e:
                st.error(f"Erro no chat oficial: {e}")

# =========================================================
# ABA 4
# =========================================================
with aba4:
    st.header("🏛️ Web Real V2 (Scraping Oficial)")
    st.write(
        "Coleta HTML dos portais oficiais, extrai texto, compara com a última execução, "
        "destaca novidades e gera relatório exportável."
    )

    col1, col2 = st.columns(2)

    with col1:
        executar_scraping = st.button("Executar Monitoramento Oficial V2")

    with col2:
        mostrar_ultima = st.button("Ver Última Execução Salva")

    if mostrar_ultima:
        ultima = ler_json(ARQUIVO_ULTIMA_EXECUCAO)
        if ultima:
            st.info(f"Última execução encontrada: {ultima.get('gerado_em', 'N/A')}")
            with st.expander("Abrir relatório da última execução"):
                st.markdown(ultima.get("relatorio_ia", "Sem relatório salvo."))
        else:
            st.warning("Ainda não existe execução anterior salva.")

    if executar_scraping:
        dados_portais = []
        comparacoes = {}
        falhas = []

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
                    comparacao = comparar_textos_textualmente(texto_antigo, item_atual["texto"], max_novidades=12)
                    comparacoes[nome] = comparacao

                    st.toast(f"✅ Coleta concluída: {nome}")

                except Exception as e:
                    falhas.append({"portal": nome, "url": url, "erro": str(e)})
                    comparacoes[nome] = {
                        "novidades": [],
                        "quantidade_novidades": 0
                    }
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
            with st.spinner("Gerando relatório analítico com base nos textos oficiais..."):
                try:
                    prompt_relatorio = gerar_prompt_relatorio_scraping(dados_portais, comparacoes)
                    relatorio = model.generate_content(prompt_relatorio)

                    st.success("Scraping e análise concluídos com sucesso!")
                    st.markdown("## Relatório Executivo")
                    st.markdown(relatorio.text)

                    # Painel de comparação
                    st.markdown("## Painel de Novidades Detectadas")
                    for nome_portal, comp in comparacoes.items():
                        with st.expander(f"{nome_portal} — {comp.get('quantidade_novidades', 0)} novidade(s) textual(is)"):
                            novidades = comp.get("novidades", [])
                            if novidades:
                                for i, novidade in enumerate(novidades[:8], start=1):
                                    st.write(f"**{i}.** {novidade}")
                            else:
                                st.write("Nenhuma novidade textual relevante detectada.")

                    # Texto bruto
                    with st.expander("Ver texto bruto extraído dos portais"):
                        for item in dados_portais:
                            st.markdown(f"### {item['nome']}")
                            st.text(item["texto"][:5000] + "\n... [conteúdo truncado]")

                    # Exportações
                    txt_export = montar_texto_exportacao_relatorio(relatorio.text, dados_portais, comparacoes)
                    md_export = montar_markdown_exportacao(relatorio.text, dados_portais, comparacoes)

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

                    # Persistência
                    salvar_execucao_atual(dados_portais, comparacoes, relatorio.text)

                    st.info("Execução salva com sucesso para comparações futuras.")

                except Exception as e:
                    st.error(f"Erro ao gerar relatório da IA: {e}")
        else:
            st.error("Não foi possível extrair texto de nenhum dos portais oficiais no momento.")
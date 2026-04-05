import streamlit as st
import google.generativeai as genai
import requests
import cloudscraper
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURAÇÃO DA API (LLM) E BUSCA DINÂMICA
# ==========================================
st.set_page_config(page_title="Assistente Fiscal - Gabriela", layout="wide")

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    modelo_escolhido = None
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            modelo_escolhido = m.name
            if 'pro' in m.name.lower() or 'flash' in m.name.lower():
                break 

    if modelo_escolhido:
        model = genai.GenerativeModel(modelo_escolhido)
    else:
        st.error("ERRO: Nenhum modelo disponível para esta chave de API.")
        st.stop()

except KeyError:
    st.error("ERRO: A variável 'GEMINI_API_KEY' não foi encontrada nos Secrets do Streamlit.")
    st.stop()
except Exception as e:
    st.error(f"ERRO DE CONEXÃO COM A API: {e}")
    st.stop()

# ==========================================
# INTERFACE DO USUÁRIO E ABAS
# ==========================================
st.title("📊 Assistente Inteligente da Reforma Tributária")

aba1, aba2, aba3, aba4 = st.tabs([
    "Radar Geral (Google)", 
    "Análise de XML (IBS/CBS)", 
    "Chatbot Fiscal", 
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
                resposta = model.generate_content(prompt_busca, tools='google_search_retrieval')
                st.success("Relatório gerado com dados atualizados da Web!")
                st.markdown(resposta.text)
            except Exception as e:
                st.warning("Busca ao vivo restrita. Utilizando a base interna.")
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
        conteudo_xml = arquivo_xml.getvalue().decode("utf-8")
        with st.expander("Visualizar XML"):
            st.code(conteudo_xml[:1000] + "\n... [truncado]", language='xml')
            
        if st.button("Analisar Operação"):
            with st.spinner("Analisando regras do IVA Dual..."):
                prompt_analise = f"""
                Você é um consultor ajudando uma contadora (Gabriela). 
                Empresa emissora: Prestação de Serviços (Lucro Presumido).
                Analise este XML: {conteudo_xml}
                Responda: 1. Tipo de serviço? 2. Impostos atuais? 3. Como fica no IBS/CBS e como parametrizar?
                """
                try:
                    resposta_xml = model.generate_content(prompt_analise)
                    st.success("Análise Fiscal Concluída!")
                    st.markdown(resposta_xml.text)
                except Exception as e:
                    st.error(f"Erro ao analisar o arquivo: {e}")

# ------------------------------------------
# ABA 3: CHATBOT FISCAL COM MEMÓRIA
# ------------------------------------------
with aba3:
    st.header("💬 Tire dúvidas com a IA Fiscal")
    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []

    for msg in st.session_state.mensagens:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pergunta_usuario = st.chat_input("Ex: Como fica a retenção na fonte com a CBS?")
    if pergunta_usuario:
        st.chat_message("user").markdown(pergunta_usuario)
        st.session_state.mensagens.append({"role": "user", "content": pergunta_usuario})

        with st.spinner("Buscando respostas..."):
            try:
                contexto = "Atue como consultor fiscal auxiliando uma contadora. Dúvida: "
                try:
                    resposta_chat = model.generate_content(contexto + pergunta_usuario, tools='google_search_retrieval')
                except:
                    resposta_chat = model.generate_content(contexto + pergunta_usuario)
                    
                st.chat_message("assistant").markdown(resposta_chat.text)
                st.session_state.mensagens.append({"role": "assistant", "content": resposta_chat.text})
            except Exception as e:
                st.error(f"Erro no chat: {e}")

# ------------------------------------------
# ABA 4: WEB REAL (WEB SCRAPING)
# ------------------------------------------
with aba4:
    st.header("Monitoramento Direto (Scraping Oficial)")
    st.write("Acessa o código HTML das páginas oficiais do Governo (Fazenda, Receita e CGIBS), extrai o texto bruto e analisa se há novas publicações normativas.")
    
    urls_oficiais = [
        "https://www.gov.br/fazenda/pt-br/acesso-a-informacao/acoes-e-programas/reforma-tributaria",
        "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo",
        "https://www.cgibs.gov.br/"
    ]
    
    if st.button("Executar Web Scraping nos Portais do Governo"):
        textos_extraidos = ""
        
        with st.spinner("Ativando Cloudscraper antibloqueio e acessando servidores..."):
            # Cria o scraper especializado em pular firewalls de segurança (como o do CGIBS)
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                }
            )
            
            for url in urls_oficiais:
                try:
                    # Usamos o scraper em vez do 'requests'
                    resposta_site = scraper.get(url, timeout=20) 
                    
                    if resposta_site.status_code == 200:
                        soup = BeautifulSoup(resposta_site.content, 'html.parser')
                        texto_limpo = soup.get_text(separator=' ', strip=True)
                        
                        textos_extraidos += f"\n\n--- TEXTO EXTRAÍDO DA URL: {url} ---\n"
                        textos_extraidos += texto_limpo[:15000]
                    else:
                        st.warning(f"Não foi possível acessar a URL {url}. Status: {resposta_site.status_code}")
                except Exception as erro_scraping:
                    st.error(f"Erro ao tentar raspar a URL {url}: {erro_scraping}")
        
        if textos_extraidos:
            with st.spinner("Enviando textos oficiais para leitura e interpretação da LLM..."):
                prompt_scraping = f"""
                Você receberá abaixo o texto bruto extraído (web scraping) hoje dos portais do Ministério da Fazenda, Receita Federal e CGIBS.
                Analise todo o texto em busca de ATUALIZAÇÕES, MANUAIS, DATAS ou LEGISLAÇÕES sobre a Reforma Tributária.
                Ignore partes de menu do site, rodapés ou links inúteis. 
                Entregue um relatório apontando exclusivamente as normativas e novidades técnicas vigentes identificadas nestes textos.
                
                TEXTOS RASPADOS DOS SITES:
                {textos_extraidos}
                """
                try:
                    relatorio_scraping = model.generate_content(prompt_scraping)
                    st.success("Scraping e Análise concluídos com sucesso!")
                    
                    with st.expander("Ver o texto bruto (HTML convertido) que o robô extraiu"):
                        st.text(textos_extraidos[:2000] + "\n... [Texto muito longo ocultado]")
                        
                    st.markdown("### 🏛️ Relatório Oficial Baseado nos Portais:")
                    st.markdown(relatorio_scraping.text)
                except Exception as e:
                    st.error(f"Erro na geração da IA pós-scraping: {e}")
        else:
            st.error("Não conseguimos extrair texto de nenhum dos portais oficiais no momento.")
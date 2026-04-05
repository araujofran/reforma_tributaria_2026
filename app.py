import streamlit as st
import google.generativeai as genai

# ==========================================
# CONFIGURAÇÃO DA API (LLM) - BUSCA DINÂMICA
# ==========================================
try:
    # 1. Autentica com a chave
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # 2. Pergunta ao Google quais modelos estão disponíveis para essa chave
    modelo_escolhido = None
    for m in genai.list_models():
        # Verifica se o modelo serve para gerar conteúdo (text/chat)
        if 'generateContent' in m.supported_generation_methods:
            modelo_escolhido = m.name
            # Se encontrar a família flash ou pro, dá preferência
            if 'flash' in m.name.lower() or 'pro' in m.name.lower():
                break 
                
    # 3. Instancia o modelo correto
    if modelo_escolhido:
        model = genai.GenerativeModel(modelo_escolhido)
        # st.sidebar.success(f"Conectado ao modelo: {modelo_escolhido}") # Opcional: tire o '#' para ver o nome na tela
    else:
        st.error("ERRO: Nenhum modelo de geração de texto disponível para esta chave de API.")

except KeyError:
    st.error("ERRO: A variável 'GEMINI_API_KEY' não foi encontrada nos Secrets do Streamlit.")
except Exception as e:
    st.error(f"ERRO DE CONEXÃO COM A API: {e}")

# ==========================================
# INTERFACE DO USUÁRIO
# ==========================================
st.set_page_config(page_title="Assistente Fiscal - Gabriela", layout="wide")
st.title("📊 Assistente Inteligente da Reforma Tributária")

# Criando abas para separar as funcionalidades
aba1, aba2 = st.tabs(["Atualizações Diárias", "Análise de XML (IBS/CBS)"])

# ------------------------------------------
# ABA 1: CONSULTA DE ATUALIZAÇÕES
# ------------------------------------------
with aba1:
    st.header("O que mudou hoje?")
    st.write("Clique no botão abaixo para buscar e resumir as atualizações dos portais oficiais (Fazenda, Receita e CGIBS).")
    
    if st.button("Buscar Atualizações de Hoje"):
        with st.spinner("Consultando bases oficiais e gerando relatório..."):
            # Aqui no futuro você conectaria o script de web scraping.
            # Para este exemplo, pedimos para o LLM gerar um resumo com base no conhecimento dele até o momento.
            prompt_busca = """
            Atue como um especialista na Reforma Tributária Brasileira. 
            Faça um resumo das principais regras de transição vigentes para 2026 focadas em SPED, REINF e DCTFWeb.
            O público alvo é uma contadora de empresas de Lucro Real e Presumido.
            """
            try:
                resposta = model.generate_content(prompt_busca)
                st.success("Relatório gerado com sucesso!")
                st.markdown(resposta.text)
            except Exception as e:
                st.error(f"Erro ao consultar o LLM: {e}")

# ------------------------------------------
# ABA 2: ANÁLISE DE XML DA NOTA FISCAL
# ------------------------------------------
with aba2:
    st.header("Análise de Impacto Tributário via XML")
    st.write("Faça o upload do XML de uma Nota Fiscal de Serviço (NFS-e) para verificar as regras de IBS/CBS.")
    
    arquivo_xml = st.file_uploader("Arraste ou selecione o arquivo XML", type=["xml"])
    
    if arquivo_xml is not None:
        # Lendo o conteúdo do XML
        conteudo_xml = arquivo_xml.getvalue().decode("utf-8")
        
        with st.expander("Visualizar conteúdo do XML carregado"):
            st.code(conteudo_xml[:1000] + "\n... [conteúdo truncado para visualização]", language='xml')
            
        if st.button("Analisar XML"):
            with st.spinner("Analisando operações e cruzando com regras do IBS/CBS..."):
                
                # O "Contexto Operacional da Gabriela" é embutido diretamente no prompt
                prompt_analise = f"""
                Você é um consultor tributário sênior auxiliando uma contadora. 
                A empresa emissora desta nota é do segmento de Prestação de Serviços (Lucro Presumido).
                
                Analise o seguinte conteúdo de um arquivo XML de Nota Fiscal:
                {conteudo_xml}
                
                Com base na Reforma Tributária (IBS e CBS):
                1. Identifique o tipo de serviço prestado (se possível pelo XML).
                2. Quais impostos atuais incidem sobre essa operação (ex: ISS, PIS, COFINS)?
                3. Como essa operação será tributada na transição para IBS e CBS? Indique se haverá necessidade de destaque em novos campos ou se enquadra em alíquota reduzida.
                
                Seja direto, técnico e foque na ação que a contadora precisa tomar no sistema ERP.
                """
                
                try:
                    resposta_xml = model.generate_content(prompt_analise)
                    st.success("Análise concluída!")
                    st.markdown("### 📋 Resultado da Análise:")
                    st.markdown(resposta_xml.text)
                except Exception as e:
                    st.error(f"Erro ao analisar o XML: {e}")
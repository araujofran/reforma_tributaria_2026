import streamlit as st
import google.generativeai as genai

# ==========================================
# CONFIGURAÇÃO DA API (LLM) E BUSCA DINÂMICA
# ==========================================
st.set_page_config(page_title="Assistente Fiscal - Gabriela", layout="wide")

try:
    # 1. Autenticação segura via Secrets
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # 2. Busca qual modelo está disponível e compatível com texto
    modelo_escolhido = None
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            modelo_escolhido = m.name
            # Dá prioridade para os modelos mais robustos
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

aba1, aba2, aba3 = st.tabs(["Atualizações Diárias (Web)", "Análise de XML (IBS/CBS)", "Chatbot Fiscal (Ao Vivo)"])

# ------------------------------------------
# ABA 1: ATUALIZAÇÕES COM GOOGLE SEARCH
# ------------------------------------------
with aba1:
    st.header("O que mudou hoje?")
    st.write("Consulta ao vivo as últimas notícias e leis nos portais governamentais.")
    
    if st.button("Buscar Atualizações de Hoje"):
        with st.spinner("Conectando à internet para buscar as últimas portarias..."):
            prompt_busca = """
            Pesquise no Google as últimas atualizações sobre a Reforma Tributária no Brasil, 
            focando em regras do IBS, CBS, SPED, EFD-Reinf e DCTFWeb para o ano atual.
            Aja como um consultor sênior resumindo as mudanças para uma contadora de Lucro Presumido e Real.
            Seja estruturado e mostre os impactos diretos na rotina.
            """
            try:
                # Tenta gerar a resposta usando a busca em tempo real do Google
                resposta = model.generate_content(
                    prompt_busca,
                    tools='google_search_retrieval' # ATIVA O GROUNDING NA WEB
                )
                st.success("Relatório gerado com dados atualizados da Web!")
                st.markdown(resposta.text)
            except Exception as e:
                # Fallback: Se a busca web falhar (por restrição da chave), usa o conhecimento interno
                st.warning("Nota: A busca ao vivo encontrou uma restrição de API. Utilizando a base de conhecimento interno super atualizada da IA.")
                resposta_fallback = model.generate_content(prompt_busca)
                st.markdown(resposta_fallback.text)

# ------------------------------------------
# ABA 2: ANÁLISE DE XML DA NOTA FISCAL
# ------------------------------------------
with aba2:
    st.header("Análise de Impacto Tributário via XML")
    st.write("Faça o upload do XML de uma Nota Fiscal de Serviço para verificar as regras (Lucro Presumido).")
    
    arquivo_xml = st.file_uploader("Selecione o arquivo XML", type=["xml"])
    
    if arquivo_xml is not None:
        conteudo_xml = arquivo_xml.getvalue().decode("utf-8")
        
        with st.expander("Visualizar conteúdo do arquivo carregado"):
            st.code(conteudo_xml[:1000] + "\n... [conteúdo longo truncado]", language='xml')
            
        if st.button("Analisar Operação"):
            with st.spinner("Cruzando dados da nota com a legislação do IVA Dual..."):
                prompt_analise = f"""
                Você é um consultor tributário sênior ajudando a Gabriela, contadora. 
                A empresa emissora da nota abaixo é do segmento de Prestação de Serviços (Lucro Presumido).
                
                Analise este XML:
                {conteudo_xml}
                
                Responda estritamente:
                1. Qual o tipo de serviço prestado?
                2. Quais impostos atuais incidem hoje nesta nota (ex: ISS, PIS, COFINS)?
                3. Como essa exata operação será tributada na transição para o IBS e a CBS? Haverá necessidade de destaque nestes mesmos valores?
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
    st.write("Pergunte sobre regras, DCTFWeb, SPED ou como proceder em cenários específicos.")

    # Inicializa o histórico de mensagens na memória do sistema
    if "mensagens" not in st.session_state:
        st.session_state.mensagens = []

    # Exibe todo o histórico na tela (estilo WhatsApp/ChatGPT)
    for msg in st.session_state.mensagens:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Caixa de texto para a Gabriela digitar
    pergunta_usuario = st.chat_input("Ex: Como fica a retenção na fonte com a chegada da CBS?")

    if pergunta_usuario:
        # Mostra a pergunta dela na tela e salva no histórico
        st.chat_message("user").markdown(pergunta_usuario)
        st.session_state.mensagens.append({"role": "user", "content": pergunta_usuario})

        with st.spinner("Analisando a legislação e buscando respostas..."):
            try:
                contexto_gabriela = "Você é um consultor fiscal sênior auxiliando uma contadora. Dúvida direta: "
                
                try:
                    # Tenta usar a busca na web também no chat
                    resposta_chat = model.generate_content(
                        contexto_gabriela + pergunta_usuario,
                        tools='google_search_retrieval'
                    )
                except:
                    # Se falhar, vai com a memória interna
                    resposta_chat = model.generate_content(contexto_gabriela + pergunta_usuario)
                    
                texto_resposta = resposta_chat.text
                
                # Mostra a resposta da IA na tela e salva no histórico
                with st.chat_message("assistant"):
                    st.markdown(texto_resposta)
                    
                st.session_state.mensagens.append({"role": "assistant", "content": texto_resposta})
                
            except Exception as e:
                st.error(f"Erro no chat: {e}")
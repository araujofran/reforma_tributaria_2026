```markdown
# 📊 Assistente Inteligente da Reforma Tributária

Um aplicativo interativo desenvolvido em **Streamlit** que utiliza **Google Gemini AI** para apoiar contadores e profissionais da área fiscal na adaptação às mudanças da Reforma Tributária Brasileira (IBS e CBS).

---

## 🚀 Funcionalidades

- **Atualizações Diárias**  
  Consulta e resume as principais regras de transição da Reforma Tributária, com foco em **SPED, REINF e DCTFWeb**.

- **Análise de XML de Nota Fiscal (NFS-e)**  
  Permite o upload de arquivos XML e gera uma análise técnica sobre o impacto tributário da operação, indicando:
  - Impostos atuais (ISS, PIS, COFINS)  
  - Regras de transição para IBS e CBS  
  - Ações práticas para configuração no ERP  

---

## 🛠️ Tecnologias Utilizadas

- [Streamlit](https://streamlit.io/) – Interface web simples e poderosa  
- [Google Generative AI (Gemini)](https://ai.google.dev/) – Modelo LLM para análise e geração de relatórios  
- Python 3.10+  

---

## 🔑 Configuração da API

No **Streamlit Cloud**, configure sua chave da API Gemini em **Settings > Secrets**:

```toml
# .streamlit/secrets.toml
GEMINI_API_KEY = "sua_chave_aqui"
```

---

## ▶️ Como Executar Localmente

1. Clone este repositório:
   ```bash
   git clone https://github.com/araujofran/reforma_tributaria_2026.git
   cd reforma_tributaria_2026
   ```

2. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   venv\Scripts\activate   # Windows
   source venv/bin/activate # Linux/Mac
   ```

3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

4. Execute o aplicativo:
   ```bash
   streamlit run app.py
   ```

---

## 🎯 Público-Alvo

- Contadores de empresas **Lucro Real** e **Lucro Presumido**  
- Profissionais de ERP e compliance fiscal  
- Consultores tributários que desejam se preparar para a transição IBS/CBS  

---

## 🌟 Diferenciais

- Interface amigável e intuitiva  
- Análises técnicas embasadas em IA  
- Foco em **ações práticas** para o dia a dia da contabilidade  
- Ferramenta pensada para **agilidade e precisão** na adaptação às novas regras  

---

## 📌 Próximos Passos

- Integração com web scraping de portais oficiais (Receita, Fazenda, CGIBS)  
- Dashboards comparativos de impacto tributário  
- Exportação de relatórios em PDF  

---

## 👩‍💼 Autoria

Projeto desenvolvido por **Francisco Ferreira de Araujo** com foco em inovação fiscal e apoio à classe contábil na Reforma Tributária 2026.

📱 (11) 95739-7660

💼 https://www.linkedin.com/in/francisco-ferreira-de-araujo-1b432033/

💻 https://github.com/araujofran

```


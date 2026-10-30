import streamlit as st
import pandas as pd
import pdfplumber
import zipfile
import io
import re
from PIL import Image, ImageDraw, ImageFont

# --- FUNÇÕES DE EXTRAÇÃO E PROCESSAMENTO DE DADOS ---

def extrair_dados_pdf(uploaded_file):
    """Extrai os dados do PDF de forma mais flexível e retorna o texto bruto para depuração."""
    dados_extraidos = []
    texto_bruto = ""
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            dia_atual = None
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                    
                texto_bruto += text + "\n--- FIM DA PÁGINA ---\n"
                linhas = text.split('\n')
                
                for linha in linhas:
                    linha_limpa = linha.replace('|', '').strip()
                    if not linha_limpa:
                        continue
                    
                    # 1. Procurar cabeçalho do Dia
                    match_dia = re.search(r"(DOMINGO|SEGUNDA|TERÇA|QUARTA|QUINTA|SEXTA|SÁBADO).*DIA\s*\d+", linha_limpa, re.IGNORECASE)
                    if match_dia:
                        dia_atual = match_dia.group(0).upper()
                        continue
                        
                    # 2. Procurar evento pela Hora
                    match_evento = re.search(r"^(\d{2}h\d{0,2})\s+(.+)", linha_limpa)
                    
                    if match_evento and dia_atual:
                        hora = match_evento.group(1).strip()
                        resto_linha = match_evento.group(2).strip()
                        
                        presidente = ""
                        atividade = "Missa" 
                        comunidade = ""
                        
                        # Isolar o Presidente
                        match_pres = re.search(r"(Pe\.|Sem\.|Diác\.|Pé).+$", resto_linha, re.IGNORECASE)
                        if match_pres:
                            presidente = match_pres.group(0).strip()
                            resto_linha = resto_linha.replace(presidente, "").strip()
                            
                        # Isolar a Atividade
                        palavras_chave_atividade = [
                            "Missa e Novena", "Adoração ao Santíssimo", 
                            "Celebração da Palavra", "Missa", "Batizados", "Casamento"
                        ]
                        for palavra in palavras_chave_atividade:
                            if palavra.lower() in resto_linha.lower():
                                idx = resto_linha.lower().find(palavra.lower())
                                atividade = resto_linha[idx:idx+len(palavra)].strip()
                                resto_linha = resto_linha.replace(atividade, "").strip()
                                break
                                
                        comunidade = resto_linha.strip()
                        
                        dados_extraidos.append({
                            "Dia": dia_atual,
                            "Hora": hora,
                            "Comunidade": comunidade,
                            "Atividade": atividade,
                            "Presidente": presidente
                        })
    except Exception as e:
        st.error(f"Erro de processamento da biblioteca: {e}")
        
    return pd.DataFrame(dados_extraidos), texto_bruto

# --- FUNÇÕES DE GERAÇÃO DE IMAGENS ---

def desenhar_tabela(draw, x, y, cabecalhos, linha_dados, largura_colunas, cor_fundo, cor_texto):
    """Desenha uma única linha da tabela na imagem."""
    fonte = ImageFont.load_default() 
    draw.rectangle([x, y, x + sum(largura_colunas), y + 30], fill=cor_fundo)
    
    x_atual = x
    for i, texto in enumerate(linha_dados):
        draw.text((x_atual + 5, y + 5), str(texto), font=fonte, fill=cor_texto)
        x_atual += largura_colunas[i]

def gerar_imagens(df):
    """Gera as imagens empilhando múltiplos dias na mesma foto até preencher o espaço vertical."""
    imagens = []
    
    largura = 1080
    altura = 1350
    fundo_creme = (253, 251, 247) 
    verde_escuro = (30, 86, 49) 
    verde_claro = (232, 245, 233) 
    branco = (255, 255, 255)
    
    fonte_titulo = ImageFont.load_default()
    
    def novo_slide():
        """Cria um canvas em branco com a cor de fundo e o rodapé."""
        img = Image.new('RGB', (largura, altura), color=fundo_creme)
        draw = ImageDraw.Draw(img)
        draw.text((50, altura - 50), "ESCALA DE MISSAS · NOVEMBRO DE 2026", font=fonte_titulo, fill=verde_escuro)
        return img, draw, 50 
        
    img_atual, draw_atual, y_atual = novo_slide()
    
    dias_unicos = df['Dia'].unique()
    cabecalhos = ["HORA", "COMUNIDADE", "ATIVIDADE", "PRESIDENTE"]
    largura_colunas = [80, 420, 260, 200]
    
    for dia in dias_unicos:
        eventos_do_dia = df[df['Dia'] == dia].to_dict('records')
        
        # Estimar espaço que este dia vai ocupar: Título (40) + Cabeçalhos (30) + (linhas * 30) + margem (40)
        altura_estimada = 40 + 30 + (len(eventos_do_dia) * 30) + 40
        
        # Se não couber e a imagem não estiver vazia, cria nova imagem
        if y_atual + altura_estimada > 1250 and y_atual > 50:
            imagens.append(img_atual)
            img_atual, draw_atual, y_atual = novo_slide()
            
        eventos_restantes = eventos_do_dia.copy()
        continuacao = False
        
        while eventos_restantes:
            titulo_texto = f"{dia} (Continuação)" if continuacao else dia
            
            # Desenhar faixa do dia
            draw_atual.rectangle([50, y_atual, largura - 50, y_atual + 40], fill=verde_escuro)
            
            # Centralizar o título na faixa
            try:
                bbox = draw_atual.textbbox((0, 0), titulo_texto, font=fonte_titulo)
                w_texto = bbox[2] - bbox[0]
            except AttributeError:
                w_texto = len(titulo_texto) * 6 
                
            x_texto = (largura - w_texto) / 2
            draw_atual.text((x_texto, y_atual + 12), titulo_texto, font=fonte_titulo, fill=branco)
            y_atual += 40
            
            # Desenhar cabeçalhos das colunas
            desenhar_tabela(draw_atual, 50, y_atual, cabecalhos, cabecalhos, largura_colunas, verde_escuro, branco)
            y_atual += 30
            
            # Preencher as linhas
            eventos_processados = 0
            for i, evento in enumerate(eventos_restantes):
                if y_atual > 1220: # Limite inferior de segurança antes do rodapé
                    break
                    
                cor_fundo = verde_claro if i % 2 == 0 else branco
                linha_dados = [evento['Hora'], evento['Comunidade'], evento['Atividade'], evento['Presidente']]
                desenhar_tabela(draw_atual, 50, y_atual, cabecalhos, linha_dados, largura_colunas, cor_fundo, verde_escuro)
                y_atual += 30
                eventos_processados += 1
            
            eventos_restantes = eventos_restantes[eventos_processados:]
            y_atual += 40 # Margem extra após o dia
            
            if eventos_restantes:
                # Se ainda sobrou evento, finaliza este slide e cria outro
                imagens.append(img_atual)
                img_atual, draw_atual, y_atual = novo_slide()
                continuacao = True
                
    # Adicionar o último slide gerado
    if y_atual > 50:
        imagens.append(img_atual)
        
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for i, img in enumerate(imagens):
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="PNG")
            zip_file.writestr(f"escala_{i+1:02d}.png", img_buffer.getvalue())
            
    return zip_buffer.getvalue()

# --- INTERFACE ---

st.title("Gerador de Escalas de Missas")
uploaded_file = st.file_uploader("Escolher ficheiro PDF", type="pdf")

if uploaded_file is not None:
    st.write("Processando o PDF...")
    df, texto_bruto = extrair_dados_pdf(uploaded_file)
    
    if not df.empty:
        st.success("Dados extraídos!")
        df_editado = st.data_editor(df, num_rows="dynamic")
        
        if st.button("Gerar Imagens"):
            with st.spinner("Gerando imagens..."):
                zip_data = gerar_imagens(df_editado)
                st.download_button(label="Descarregar ZIP", data=zip_data, file_name="escalas.zip", mime="application/zip")
    else:
        st.warning("Não foi possível formatar os dados automaticamente.")
        st.info("Por favor, copie algumas linhas do texto bruto abaixo e cole no chat para eu ajustar as regras de leitura:")
        st.text_area("Como o computador leu o PDF:", texto_bruto, height=300)

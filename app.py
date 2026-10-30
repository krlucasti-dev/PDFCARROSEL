import streamlit as st
import pandas as pd
import pdfplumber
import zipfile
import io
import re
import urllib.request
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

# --- FUNÇÕES DE EXTRAÇÃO E PROCESSAMENTO DE DADOS ---

def extrair_dados_pdf(uploaded_file):
    eventos_brutos = []
    texto_bruto = ""
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            dia_atual = None
            evento_atual = None
            
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
                        
                    # Filtro agressivo para ignorar cabeçalhos e rodapés
                    linha_upper = linha_limpa.upper()
                    ignorar = ["PARÓQUIA", "ARQUIDIOCESE", "FORANIA", "E VOS DAREI", "CONHECIMENTO", "PRAÇA GETÚLIO", "TELEFONE:", "ESCALA DE MISSAS", "SABAR", "DE N. SRA."]
                    if any(x in linha_upper for x in ignorar):
                        continue
                    
                    # 1. Procurar cabeçalho do Dia
                    match_dia = re.search(r"(DOMINGO|SEGUNDA|TERÇA|QUARTA|QUINTA|SEXTA|SÁBADO).*DIA\s*\d+", linha_limpa, re.IGNORECASE)
                    if match_dia:
                        dia_atual = match_dia.group(0).upper()
                        if evento_atual:
                            eventos_brutos.append(evento_atual)
                            evento_atual = None
                        continue
                        
                    # 2. Procurar evento pela Hora
                    match_evento = re.search(r"^(\d{2}h\d{0,2})\s+(.+)", linha_limpa)
                    
                    if match_evento and dia_atual:
                        if evento_atual:
                            eventos_brutos.append(evento_atual)
                            
                        evento_atual = {
                            "Dia": dia_atual,
                            "Hora": match_evento.group(1).strip(),
                            "Resto": match_evento.group(2).strip()
                        }
                    elif evento_atual:
                        evento_atual["Resto"] += " " + linha_limpa
                            
            if evento_atual:
                eventos_brutos.append(evento_atual)
                
    except Exception as e:
        st.error(f"Erro de leitura do PDF: {e}")

    dados_finais = []
    
    for evt in eventos_brutos:
        resto = evt["Resto"]
        
        # 1. Auto-correção de gralhas antes de extrair o presidente
        resto = re.sub(r'Pé\s+', 'Pe. ', resto, flags=re.IGNORECASE)
        resto = re.sub(r'PeHélio', 'Pe. Hélio', resto, flags=re.IGNORECASE)
        resto = re.sub(r'Pé\s*Héli\s*o', 'Pe. Hélio', resto, flags=re.IGNORECASE)
        
        presidente = ""
        # 2. Extrair APENAS o título + 1 nome (ex: "Pe. Fernando"), barrando a junção com lixo
        match_pres = re.search(r"(Pe\.|Sem\.|Diác\.|Diac\.)\s+([A-Za-zÀ-ÿ]+)", resto, re.IGNORECASE)
        if match_pres:
            presidente = match_pres.group(0).strip()
            resto = resto.replace(presidente, "").strip()
            
        # 3. Isolar a Atividade
        atividade = "Missa"
        palavras_chave_atividade = [
            "Missa (Normalistas)", "Adoração ao Santíssimo Sacramento", "Adoração ao Santíssimo",
            "Missa e Novena", "Celebração da Palavra", "Missa", "Batizados", "Casamento"
        ]
        for palavra in palavras_chave_atividade:
            if palavra.lower() in resto.lower():
                idx = resto.lower().find(palavra.lower())
                atividade = resto[idx:idx+len(palavra)].strip()
                resto = resto.replace(atividade, "").strip()
                break
                
        # 4. Comunidade é o que sobrou
        comunidade = resto.strip()
        
        # Limpeza final de pontuação arrastada
        comunidade = re.sub(r'^\.$', '', comunidade).strip()
        
        dados_finais.append({
            "Dia": evt["Dia"],
            "Hora": evt["Hora"],
            "Comunidade": comunidade,
            "Atividade": atividade,
            "Presidente": presidente
        })
        
    return pd.DataFrame(dados_finais), texto_bruto

# --- FUNÇÕES DE GERAÇÃO DE IMAGENS ---

def carregar_fonte(tamanho):
    font_path = "Roboto-Regular.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf"
        try:
            urllib.request.urlretrieve(url, font_path)
        except Exception:
            return ImageFont.load_default()
    try:
        return ImageFont.truetype(font_path, tamanho)
    except Exception:
        return ImageFont.load_default()

def desenhar_tabela(draw, x, y, cabecalhos, linha_dados, largura_colunas, cor_fundo, cor_texto, fonte, altura_base):
    max_linhas_texto = 1
    textos_quebrados = []
    
    for i, texto in enumerate(linha_dados):
        caracteres_limite = int((largura_colunas[i] / 100) * 12)
        linhas_do_texto = textwrap.wrap(str(texto), width=caracteres_limite) if str(texto) else [""]
        textos_quebrados.append(linhas_do_texto)
        if len(linhas_do_texto) > max_linhas_texto:
            max_linhas_texto = len(linhas_do_texto)
            
    altura_final = altura_base + ((max_linhas_texto - 1) * 25)
    
    draw.rectangle([x, y, x + sum(largura_colunas), y + altura_final], fill=cor_fundo)
    
    x_atual = x
    for i, linhas in enumerate(textos_quebrados):
        y_texto = y + 15
        for linha_texto in linhas:
            draw.text((x_atual + 15, y_texto), linha_texto, font=fonte, fill=cor_texto)
            y_texto += 25
        x_atual += largura_colunas[i]
        
    return altura_final

def gerar_imagens(df, texto_rodape):
    imagens = []
    largura = 1080
    altura = 1350
    fundo_creme = (253, 251, 247) 
    verde_escuro = (30, 86, 49) 
    verde_claro = (232, 245, 233) 
    branco = (255, 255, 255)
    
    fonte_titulo = carregar_fonte(28)
    fonte_tabela = carregar_fonte(22)
    fonte_rodape = carregar_fonte(20)
    
    altura_linha = 55
    altura_cabecalho_dia = 60
    
    logo_img = None
    if os.path.exists("logomatriz-site.png"):
        try:
            logo_img = Image.open("logomatriz-site.png").convert("RGBA")
            proporcao = 80 / float(logo_img.size[1])
            nova_largura = int((float(logo_img.size[0]) * float(proporcao)))
            logo_img = logo_img.resize((nova_largura, 80), Image.Resampling.LANCZOS)
        except Exception:
            pass
    
    def novo_slide():
        img = Image.new('RGB', (largura, altura), color=fundo_creme)
        draw = ImageDraw.Draw(img)
        draw.text((50, altura - 70), f"ESCALA DE MISSAS · {texto_rodape.upper()}", font=fonte_rodape, fill=verde_escuro)
        if logo_img:
            img.paste(logo_img, (largura - logo_img.size[0] - 50, altura - 100), logo_img)
        return img, draw, 50 
        
    img_atual, draw_atual, y_atual = novo_slide()
    
    dias_unicos = df['Dia'].unique()
    cabecalhos = ["HORA", "COMUNIDADE", "ATIVIDADE", "PRESIDENTE"]
    largura_colunas = [100, 430, 250, 200] 
    
    for dia in dias_unicos:
        eventos_do_dia = df[df['Dia'] == dia].to_dict('records')
        
        altura_estimada = altura_cabecalho_dia + altura_linha + (len(eventos_do_dia) * (altura_linha + 20)) + 40
        
        if y_atual + altura_estimada > 1180 and y_atual > 50:
            imagens.append(img_atual)
            img_atual, draw_atual, y_atual = novo_slide()
            
        eventos_restantes = eventos_do_dia.copy()
        continuacao = False
        
        while eventos_restantes:
            titulo_texto = f"{dia} (Continuação)" if continuacao else dia
            
            draw_atual.rectangle([50, y_atual, largura - 50, y_atual + altura_cabecalho_dia], fill=verde_escuro)
            try:
                bbox = draw_atual.textbbox((0, 0), titulo_texto, font=fonte_titulo)
                w_texto = bbox[2] - bbox[0]
            except AttributeError:
                w_texto = len(titulo_texto) * 15 
                
            x_texto = (largura - w_texto) / 2
            draw_atual.text((x_texto, y_atual + 15), titulo_texto, font=fonte_titulo, fill=branco)
            y_atual += altura_cabecalho_dia
            
            y_atual += desenhar_tabela(draw_atual, 50, y_atual, cabecalhos, cabecalhos, largura_colunas, verde_escuro, branco, fonte_tabela, altura_linha)
            
            eventos_processados = 0
            for i, evento in enumerate(eventos_restantes):
                if y_atual > 1150: 
                    break
                    
                cor_fundo = verde_claro if i % 2 == 0 else branco
                linha_dados = [evento['Hora'], evento['Comunidade'], evento['Atividade'], evento['Presidente']]
                
                altura_gasta = desenhar_tabela(draw_atual, 50, y_atual, cabecalhos, linha_dados, largura_colunas, cor_fundo, verde_escuro, fonte_tabela, altura_linha)
                y_atual += altura_gasta
                eventos_processados += 1
            
            eventos_restantes = eventos_restantes[eventos_processados:]
            y_atual += 40 
            
            if eventos_restantes:
                imagens.append(img_atual)
                img_atual, draw_atual, y_atual = novo_slide()
                continuacao = True
                
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

texto_rodape = st.text_input("Mês e Ano (aparecerá no rodapé):", value="NOVEMBRO DE 2026")
uploaded_file = st.file_uploader("Escolher ficheiro PDF", type="pdf")

if uploaded_file is not None:
    st.write("A processar o PDF...")
    df, texto_bruto = extrair_dados_pdf(uploaded_file)
    
    if not df.empty:
        st.success("Dados extraídos com sucesso! Revise na tabela abaixo:")
        df_editado = st.data_editor(df, num_rows="dynamic")
        
        if st.button("Gerar Imagens"):
            with st.spinner("A gerar imagens..."):
                zip_data = gerar_imagens(df_editado, texto_rodape)
                st.download_button(label="Descarregar ZIP", data=zip_data, file_name="escalas.zip", mime="application/zip")
    else:
        st.warning("Não foi possível formatar os dados automaticamente.")

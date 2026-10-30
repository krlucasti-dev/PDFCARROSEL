
import streamlit as st
import pandas as pd
import pdfplumber
import zipfile
import io
import re
from PIL import Image, ImageDraw, ImageFont

# --- FUNÇÕES DE EXTRAÇÃO E PROCESSAMENTO DE DADOS ---

def extrair_dados_pdf(uploaded_file):
    """Extrai os dados do PDF carregado utilizando pdfplumber."""
    dados_extraidos = []
    
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                
                # Procura por linhas de cabeçalho de dia (ex: "DOMINGO - DIA 01")
                dia_atual = None
                
                # A extração de tabelas com pdfplumber pode precisar de ajustes
                # dependendo da estrutura exata do PDF. Esta é uma abordagem básica
                # baseada na estrutura esperada de linhas.
                
                linhas = text.split('\n')
                for linha in linhas:
                    # Verifica se a linha parece um cabeçalho de dia
                    match_dia = re.search(r"([A-ZÇÃ]+\s*[A-ZÇÃ]*\s*-\s*DIA\s*\d+)", linha, re.IGNORECASE)
                    if match_dia:
                        dia_atual = match_dia.group(1).strip()
                        continue # Vai para a próxima linha, pois esta é o cabeçalho
                        
                    # Verifica se a linha parece uma entrada de evento
                    # Ex: "07h Nossa Senhora da Conceição Missa Pe. Fernando"
                    # Usamos uma expressão regular simples para detetar a hora no início
                    match_evento = re.match(r"(\d{2}h\d{0,2})\s+(.+)", linha)
                    
                    if match_evento and dia_atual:
                        hora = match_evento.group(1).strip()
                        resto_linha = match_evento.group(2).strip()
                        
                        # Tenta separar comunidade, atividade e presidente
                        # Isto pode ser complexo se não houver delimitadores claros
                        # Vamos assumir uma divisão baseada em palavras-chave ou posições se possível
                        # Para simplificar na prova de conceito, vamos dividir em 3 partes, mas na prática
                        # pode ser necessário mais lógica de parsing aqui.
                        
                        partes = re.split(r'\s{2,}', resto_linha) # Divide por 2 ou mais espaços
                        
                        comunidade = partes[0] if len(partes) > 0 else ""
                        atividade = partes[1] if len(partes) > 1 else ""
                        presidente = partes[2] if len(partes) > 2 else ""
                        
                        # Se não dividiu bem por espaços, tentamos uma abordagem diferente
                        if len(partes) < 3:
                            # Tenta encontrar o presidente (geralmente começa com Pe. ou Sem. ou Diác.)
                            match_pres = re.search(r"(Pe\.|Sem\.|Diác\.)\s+([A-Za-zÀ-ÿ]+)", resto_linha)
                            if match_pres:
                                presidente = match_pres.group(0)
                                resto_linha = resto_linha.replace(presidente, "").strip()
                                
                            # Tenta encontrar a atividade (Missa, Batizados, Celebração, etc)
                            palavras_chave_atividade = ["Missa", "Batizados", "Celebração da Palavra", "Adoração", "Casamento"]
                            for palavra in palavras_chave_atividade:
                                if palavra in resto_linha:
                                    atividade = palavra
                                    comunidade = resto_linha.replace(palavra, "").strip()
                                    break
                        
                        dados_extraidos.append({
                            "Dia": dia_atual,
                            "Hora": hora,
                            "Comunidade": comunidade,
                            "Atividade": atividade,
                            "Presidente": presidente
                        })
    except Exception as e:
        st.error(f"Erro ao processar o PDF: {e}")
        
    return pd.DataFrame(dados_extraidos)

# --- FUNÇÕES DE GERAÇÃO DE IMAGENS ---

def desenhar_tabela(draw, x, y, cabecalhos, linha_dados, largura_colunas, cor_fundo, cor_texto):
    """Desenha uma única linha da tabela na imagem."""
    fonte = ImageFont.load_default() # Em produção, carregar uma fonte TTF
    
    # Desenha o fundo da linha
    draw.rectangle([x, y, x + sum(largura_colunas), y + 30], fill=cor_fundo)
    
    # Desenha os textos das colunas
    x_atual = x
    for i, texto in enumerate(linha_dados):
        draw.text((x_atual + 5, y + 5), str(texto), font=fonte, fill=cor_texto)
        x_atual += largura_colunas[i]

def criar_imagem_slide(dia, eventos, num_slide):
    """Cria uma imagem (slide) para um dia específico com os seus eventos."""
    largura = 1080
    altura = 1350
    fundo_creme = (253, 251, 247) # #FDFBF7
    verde_escuro = (30, 86, 49) # #1E5631
    verde_claro = (232, 245, 233) # #E8F5E9
    branco = (255, 255, 255)
    
    img = Image.new('RGB', (largura, altura), color=fundo_creme)
    draw = ImageDraw.Draw(img)
    
    # Em produção, carregar fontes reais
    fonte_titulo = ImageFont.load_default()
    
    # Título do Dia
    titulo_texto = dia
    if num_slide > 1:
        titulo_texto += " (Continuação)"
        
    draw.rectangle([50, 50, largura - 50, 100], fill=verde_escuro)
    draw.text((largura/2 - 100, 65), titulo_texto, font=fonte_titulo, fill=branco)
    
    # Cabeçalho da Tabela
    cabecalhos = ["HORA", "COMUNIDADE", "ATIVIDADE", "PRESIDENTE"]
    largura_colunas = [100, 400, 280, 200]
    y_atual = 120
    
    desenhar_tabela(draw, 50, y_atual, cabecalhos, cabecalhos, largura_colunas, verde_escuro, branco)
    y_atual += 30
    
    # Linhas de Dados
    for i, evento in enumerate(eventos):
        cor_fundo = verde_claro if i % 2 == 0 else branco
        linha_dados = [evento['Hora'], evento['Comunidade'], evento['Atividade'], evento['Presidente']]
        desenhar_tabela(draw, 50, y_atual, cabecalhos, linha_dados, largura_colunas, cor_fundo, verde_escuro)
        y_atual += 30
        
    # Rodapé
    rodape_texto = "ESCALA DE MISSAS · NOVEMBRO DE 2026"
    draw.text((50, altura - 50), rodape_texto, font=fonte_titulo, fill=verde_escuro)
    
    return img

def gerar_imagens(df):
    """Gera as imagens com base no DataFrame e retorna um buffer ZIP."""
    imagens = []
    
    # Agrupa por dia
    dias_unicos = df['Dia'].unique()
    
    for dia in dias_unicos:
        eventos_do_dia = df[df['Dia'] == dia].to_dict('records')
        
        # Paginação (máx 8 eventos por slide)
        max_eventos_por_slide = 8
        num_slides = (len(eventos_do_dia) + max_eventos_por_slide - 1) // max_eventos_por_slide
        
        for slide_idx in range(num_slides):
            inicio = slide_idx * max_eventos_por_slide
            fim = inicio + max_eventos_por_slide
            eventos_slide = eventos_do_dia[inicio:fim]
            
            img = criar_imagem_slide(dia, eventos_slide, slide_idx + 1)
            imagens.append(img)
            
    # Cria o ZIP em memória
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for i, img in enumerate(imagens):
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="PNG")
            zip_file.writestr(f"escala_{i+1:02d}.png", img_buffer.getvalue())
            
    return zip_buffer.getvalue()

# --- INTERFACE DO UTILIZADOR (STREAMLIT) ---

st.title("Gerador de Escalas de Missas para Instagram")
st.write("Faça o upload do PDF da escala mensal para gerar as imagens do carrossel.")

uploaded_file = st.file_uploader("Escolher ficheiro PDF", type="pdf")

if uploaded_file is not None:
    st.write("A processar o ficheiro PDF...")
    df = extrair_dados_pdf(uploaded_file)
    
    if not df.empty:
        st.success("Dados extraídos com sucesso!")
        st.write("Revise e edite os dados extraídos abaixo antes de gerar as imagens:")
        
        # Tabela editável
        df_editado = st.data_editor(df, num_rows="dynamic")
        
        if st.button("Aprovar Dados e Gerar Imagens"):
            with st.spinner("A gerar imagens..."):
                zip_data = gerar_imagens(df_editado)
                
                st.success("Imagens geradas com sucesso!")
                st.download_button(
                    label="Descarregar Imagens (ZIP)",
                    data=zip_data,
                    file_name="escalas_instagram.zip",
                    mime="application/zip"
                )
    else:
        st.warning("Não foi possível extrair dados do PDF. Verifique se o formato é suportado.")


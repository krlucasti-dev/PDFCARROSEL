
import streamlit as st
import pandas as pd
import pdfplumber
import zipfile
import io
import re
import calendar
import unicodedata

from datetime import datetime
from PIL import Image, ImageDraw, ImageFont


# ============================================================
# CONFIGURAÇÃO DA APLICAÇÃO
# ============================================================

st.set_page_config(
    page_title="Gerador de Escalas",
    page_icon="⛪",
    layout="wide",
    initial_sidebar_state="expanded"
)

LARGURA = 1080
ALTURA = 1350

MESES = [
    "Janeiro", "Fevereiro", "Março", "Abril",
    "Maio", "Junho", "Julho", "Agosto",
    "Setembro", "Outubro", "Novembro", "Dezembro"
]

DIAS = [
    "DOMINGO", "SEGUNDA", "TERÇA", "QUARTA",
    "QUINTA", "SEXTA", "SÁBADO"
]

ATIVIDADES = [
    "Adoração ao Santíssimo",
    "Celebração Eucarística",
    "Celebração da Palavra",
    "Missa e Novena",
    "Missa",
    "Batizados",
    "Casamento",
    "Confissão",
    "Novena",
    "Terço",
    "Adoração"
]


# ============================================================
# FONTES
# ============================================================

def carregar_fonte(tamanho, negrito=False):

    caminhos = []

    if negrito:
        caminhos = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        ]
    else:
        caminhos = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
        ]

    for caminho in caminhos:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except (OSError, IOError):
            continue

    return ImageFont.load_default()


# ============================================================
# FUNÇÕES AUXILIARES DE TEXTO
# ============================================================

def normalizar(texto):
    texto = str(texto).strip().lower()

    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caractere) != "Mn"
    )


def limpar_texto(texto):

    texto = str(texto)

    texto = re.sub(r"\s+", " ", texto)

    texto = texto.strip(" |;,-\t")

    return texto


def quebrar_texto(texto, fonte, largura, draw):

    palavras = str(texto).split()

    linhas = []
    linha_atual = ""

    for palavra in palavras:

        tentativa = (
            palavra if not linha_atual
            else linha_atual + " " + palavra
        )

        largura_texto = draw.textbbox(
            (0, 0), tentativa, font=fonte
        )[2]

        if largura_texto <= largura:
            linha_atual = tentativa

        else:
            if linha_atual:
                linhas.append(linha_atual)

            linha_atual = palavra

    if linha_atual:
        linhas.append(linha_atual)

    return linhas


def desenhar_texto_multilinha(
    draw,
    texto,
    posicao,
    fonte,
    cor,
    largura_maxima,
    max_linhas=2,
    espacamento=8
):

    x, y = posicao

    linhas = quebrar_texto(
        texto,
        fonte,
        largura_maxima,
        draw
    )

    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]

        ultima = linhas[-1]

        while ultima and draw.textbbox(
            (0, 0), ultima + "...", font=fonte
        )[2] > largura_maxima:
            ultima = ultima[:-1]

        linhas[-1] = ultima.rstrip() + "..."

    for linha in linhas:

        draw.text(
            (x, y),
            linha,
            font=fonte,
            fill=cor
        )

        altura_linha = draw.textbbox(
            (0, 0), linha, font=fonte
        )[3]

        y += altura_linha + espacamento

    return y


# ============================================================
# EXTRAÇÃO DO PDF
# ============================================================

def identificar_dia(linha):

    padrao = (
        r"\b(DOMINGO|SEGUNDA(?:[- ]FEIRA)?|"
        r"TERÇA(?:[- ]FEIRA)?|QUARTA(?:[- ]FEIRA)?|"
        r"QUINTA(?:[- ]FEIRA)?|SEXTA(?:[- ]FEIRA)?|"
        r"SÁBADO)\b"
        r".*?(?:DIA\s*)?(\d{1,2})\b"
    )

    resultado = re.search(
        padrao,
        linha,
        re.IGNORECASE
    )

    if not resultado:
        return None

    dia = resultado.group(1).upper()
    numero = resultado.group(2)

    return f"{dia} - DIA {int(numero):02d}"


def identificar_horario(linha):

    resultado = re.match(
        r"^\s*(\d{1,2}\s*[hH]\s*\d{0,2}|\d{1,2}:\d{2})\b\s*(.*)",
        linha
    )

    if not resultado:
        return None, None

    hora = resultado.group(1)
    restante = resultado.group(2)

    hora = re.sub(r"\s+", "", hora).lower()

    if ":" in hora:
        hora = hora.replace(":", "h")

    return hora, restante.strip()


def identificar_presidente(texto):

    padrao = (
        r"\b(Pe\.?|Padre|Sem\.?|Seminarista|"
        r"Diác\.?|Diácono|Dom)\s*"
    )

    resultado = re.search(
        padrao,
        texto,
        re.IGNORECASE
    )

    if not resultado:
        return "", texto

    presidente = limpar_texto(
        texto[resultado.start():]
    )

    restante = limpar_texto(
        texto[:resultado.start()]
    )

    return presidente, restante


def identificar_atividade(texto):

    texto_normalizado = normalizar(texto)

    atividades_ordenadas = sorted(
        ATIVIDADES,
        key=len,
        reverse=True
    )

    for atividade in atividades_ordenadas:

        atividade_normalizada = normalizar(atividade)

        posicao = texto_normalizado.find(
            atividade_normalizada
        )

        if posicao >= 0:

            inicio = posicao
            fim = posicao + len(atividade)

            atividade_encontrada = texto[inicio:fim]

            restante = (
                texto[:inicio] + " " + texto[fim:]
            )

            return (
                limpar_texto(atividade_encontrada),
                limpar_texto(restante)
            )

    return "Missa", limpar_texto(texto)


def extrair_dados_pdf(arquivo):

    dados = []
    texto_bruto = ""
    dia_atual = None

    try:

        arquivo.seek(0)

        with pdfplumber.open(arquivo) as pdf:

            for pagina in pdf.pages:

                texto = pagina.extract_text()

                if not texto:
                    continue

                texto_bruto += (
                    texto + "\n--- FIM DA PÁGINA ---\n"
                )

                for linha in texto.split("\n"):

                    linha = limpar_texto(
                        linha.replace("|", "")
                    )

                    if not linha:
                        continue

                    # Identifica o dia da semana
                    dia_encontrado = identificar_dia(
                        linha
                    )

                    if dia_encontrado:
                        dia_atual = dia_encontrado
                        continue

                    # Identifica o horário
                    hora, restante = identificar_horario(
                        linha
                    )

                    if not hora or not dia_atual:
                        continue

                    # Identifica o presidente
                    presidente, restante = (
                        identificar_presidente(restante)
                    )

                    # Identifica a atividade
                    atividade, comunidade = (
                        identificar_atividade(restante)
                    )

                    dados.append({
                        "Dia": dia_atual,
                        "Hora": hora,
                        "Comunidade": comunidade,
                        "Atividade": atividade,
                        "Presidente": presidente
                    })

    except Exception as erro:

        st.error(
            f"Erro ao processar o PDF: {erro}"
        )

    colunas = [
        "Dia",
        "Hora",
        "Comunidade",
        "Atividade",
        "Presidente"
    ]

    return pd.DataFrame(
        dados,
        columns=colunas
    ), texto_bruto


# ============================================================
# CORES E ELEMENTOS VISUAIS
# ============================================================

def converter_cor(hexadecimal):

    hexadecimal = hexadecimal.lstrip("#")

    return tuple(
        int(hexadecimal[i:i+2], 16)
        for i in (0, 2, 4)
    )


def clarear_cor(cor, quantidade=0.90):

    return tuple(
        int(c + (255 - c) * quantidade)
        for c in cor
    )


def desenhar_cabecalho(
    draw,
    titulo,
    mes,
    ano,
    cor_principal
):

    branco = (255, 255, 255)
    fonte_pequena = carregar_fonte(27)
    fonte_titulo = carregar_fonte(48, True)

    draw.rectangle(
        [0, 0, LARGURA, 270],
        fill=cor_principal
    )

    draw.text(
        (75, 65),
        "PROGRAMAÇÃO PAROQUIAL",
        font=fonte_pequena,
        fill=(220, 235, 225)
    )

    draw.text(
        (75, 112),
        titulo,
        font=fonte_titulo,
        fill=branco
    )

    draw.text(
        (78, 190),
        f"{mes.upper()} DE {ano}",
        font=fonte_pequena,
        fill=(220, 235, 225)
    )


def desenhar_rodape(
    draw,
    numero,
    total,
    cor_principal
):

    fonte = carregar_fonte(23)

    draw.line(
        [(65, 1270), (1015, 1270)],
        fill=(220, 220, 220),
        width=2
    )

    draw.text(
        (70, 1290),
        "IGREJA MATRIZ",
        font=fonte,
        fill=cor_principal
    )

    texto_pagina = f"{numero:02d} / {total:02d}"

    largura = draw.textbbox(
        (0, 0),
        texto_pagina,
        font=fonte
    )[2]

    draw.text(
        (1010 - largura, 1290),
        texto_pagina,
        font=fonte,
        fill=cor_principal
    )


# ============================================================
# CAPA DO CARROSSEL
# ============================================================

def criar_capa(
    df,
    mes,
    ano,
    cor_principal
):

    imagem = Image.new(
        "RGB",
        (LARGURA, ALTURA),
        (250, 249, 245)
    )

    draw = ImageDraw.Draw(imagem)

    branco = (255, 255, 255)

    fonte_chamada = carregar_fonte(29)
    fonte_titulo = carregar_fonte(75, True)
    fonte_mes = carregar_fonte(48)
    fonte_info = carregar_fonte(28)

    # Fundo superior
    draw.rectangle(
        [0, 0, LARGURA, 850],
        fill=cor_principal
    )

    draw.rectangle(
        [0, 820, LARGURA, 850],
        fill=clarear_cor(cor_principal, 0.55)
    )

    draw.text(
        (85, 160),
        "IGREJA MATRIZ",
        font=fonte_chamada,
        fill=(220, 235, 225)
    )

    draw.text(
        (80, 310),
        "Escala de",
        font=fonte_titulo,
        fill=branco
    )

    draw.text(
        (80, 405),
        "Celebrações",
        font=fonte_titulo,
        fill=branco
    )

    draw.text(
        (85, 550),
        f"{mes} de {ano}",
        font=fonte_mes,
        fill=(230, 240, 232)
    )

    # Cartão de informações
    draw.rounded_rectangle(
        [65, 930, 1015, 1150],
        radius=30,
        fill=branco
    )

    total_eventos = len(df)
    total_dias = df["Dia"].nunique()

    draw.text(
        (105, 975),
        f"{total_eventos} celebrações programadas",
        font=fonte_info,
        fill=cor_principal
    )

    draw.text(
        (105, 1040),
        f"{total_dias} dias de programação",
        font=fonte_info,
        fill=(100, 100, 100)
    )

    draw.text(
        (85, 1220),
        "Confira os horários e locais das celebrações",
        font=carregar_fonte(23),
        fill=(100, 100, 100)
    )

    return imagem


# ============================================================
# SLIDES DAS CELEBRAÇÕES
# ============================================================

def criar_slide(
    dia,
    eventos,
    mes,
    ano,
    numero_slide,
    total_slides,
    cor_principal
):

    imagem = Image.new(
        "RGB",
        (LARGURA, ALTURA),
        (250, 249, 245)
    )

    draw = ImageDraw.Draw(imagem)

    cor_clara = clarear_cor(
        cor_principal,
        0.90
    )

    branco = (255, 255, 255)
    cinza = (105, 105, 105)

    desenhar_cabecalho(
        draw,
        "Celebrações",
        mes,
        ano,
        cor_principal
    )

    fonte_dia = carregar_fonte(34, True)
    fonte_hora = carregar_fonte(34, True)
    fonte_comunidade = carregar_fonte(30, True)
    fonte_info = carregar_fonte(23)

    draw.text(
        (70, 305),
        dia,
        font=fonte_dia,
        fill=cor_principal
    )

    y = 380

    altura_cartao = 155
    espacamento = 20

    for evento in eventos:

        draw.rounded_rectangle(
            [
                60,
                y,
                1020,
                y + altura_cartao
            ],
            radius=22,
            fill=branco
        )

        # Identificação do horário
        draw.rounded_rectangle(
            [
                80,
                y + 25,
                230,
                y + 130
            ],
            radius=18,
            fill=cor_clara
        )

        draw.text(
            (105, y + 60),
            str(evento["Hora"]),
            font=fonte_hora,
            fill=cor_principal
        )

        # Comunidade
        draw.text(
            (260, y + 18),
            str(evento["Comunidade"]) or "Comunidade não informada",
            font=fonte_comunidade,
            fill=cor_principal
        )

        # Atividade
        desenhar_texto_multilinha(
            draw,
            evento["Atividade"],
            (260, y + 65),
            fonte_info,
            cinza,
            710,
            max_linhas=1
        )

        # Presidente
        presidente = str(
            evento["Presidente"]
        ).strip()

        if presidente:

            desenhar_texto_multilinha(
                draw,
                presidente,
                (260, y + 103),
                fonte_info,
                cinza,
                710,
                max_linhas=1
            )

        y += altura_cartao + espacamento

    desenhar_rodape(
        draw,
        numero_slide,
        total_slides,
        cor_principal
    )

    return imagem


# ============================================================
# GERAÇÃO DO CARROSSEL
# ============================================================

def gerar_carrossel(
    df,
    mes,
    ano,
    cor_hex,
    eventos_por_slide=5
):

    cor_principal = converter_cor(cor_hex)

    imagens = []

    # Capa
    imagens.append(
        criar_capa(
            df,
            mes,
            ano,
            cor_principal
        )
    )

    # Agrupa os eventos por dia
    dias_unicos = df["Dia"].drop_duplicates().tolist()

    grupos = []

    for dia in dias_unicos:

        eventos = df[
            df["Dia"] == dia
        ].to_dict("records")

        for inicio in range(
            0,
            len(eventos),
            eventos_por_slide
        ):

            grupos.append((
                dia,
                eventos[
                    inicio:inicio + eventos_por_slide
                ]
            ))

    total_slides = len(grupos) + 1

    # Cria os slides
    for indice, (dia, eventos) in enumerate(grupos):

        imagem = criar_slide(
            dia,
            eventos,
            mes,
            ano,
            indice + 2,
            total_slides,
            cor_principal
        )

        imagens.append(imagem)

    return imagens


# ============================================================
# EXPORTAÇÃO ZIP
# ============================================================

def gerar_zip(imagens):

    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as arquivo_zip:

        for indice, imagem in enumerate(imagens):

            imagem_buffer = io.BytesIO()

            imagem.save(
                imagem_buffer,
                format="PNG",
                optimize=True
            )

            arquivo_zip.writestr(
                f"escala_{indice + 1:02d}.png",
                imagem_buffer.getvalue()
            )

    buffer.seek(0)

    return buffer.getvalue()


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1200px;
        }

        h1 {
            font-weight: 750;
            letter-spacing: -1px;
        }

        .subtitulo {
            color: #777;
            font-size: 16px;
            margin-bottom: 25px;
        }

        div[data-testid="stFileUploader"] {
            border-radius: 12px;
        }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("Gerador de Escalas")

st.markdown(
    '<p class="subtitulo">'
    'Transforme PDFs de escalas de celebrações '
    'em carrosséis prontos para o Instagram.'
    '</p>',
    unsafe_allow_html=True
)

# ------------------------------------------------------------
# CONFIGURAÇÕES LATERAIS
# ------------------------------------------------------------

with st.sidebar:

    st.header("Personalização")

    hoje = datetime.now()

    mes = st.selectbox(
        "Mês da escala",
        MESES,
        index=hoje.month - 1
    )

    ano = st.number_input(
        "Ano",
        min_value=2020,
        max_value=2100,
        value=hoje.year,
        step=1
    )

    cor_hex = st.color_picker(
        "Cor principal",
        "#1E5631"
    )

    eventos_por_slide = st.slider(
        "Celebrações por slide",
        min_value=3,
        max_value=5,
        value=5
    )

    st.divider()

    st.caption(
        "Formato das imagens: 1080 × 1350 pixels"
    )

# ------------------------------------------------------------
# UPLOAD
# ------------------------------------------------------------

st.subheader("1. Enviar escala")

arquivo_pdf = st.file_uploader(
    "Selecione o PDF da escala de celebrações",
    type=["pdf"],
    help="Envie um PDF que contenha texto selecionável."
)

if arquivo_pdf:

    with st.spinner("Lendo e analisando o PDF..."):

        df, texto_bruto = extrair_dados_pdf(
            arquivo_pdf
        )

    if not df.empty:

        st.success(
            f"{len(df)} celebrações identificadas!"
        )

        st.subheader("2. Conferir informações")

        st.info(
            "Confira os dados extraídos. "
            "Você pode editar qualquer campo antes de gerar "
            "o carrossel."
        )

        df_editado = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="editor_escalas"
        )

        st.caption(
            "Atenção: confira principalmente os nomes das "
            "comunidades e dos presidentes."
        )

        st.divider()

        st.subheader("3. Gerar carrossel")

        if st.button(
            "Gerar imagens do carrossel",
            type="primary",
            use_container_width=True
        ):

            if df_editado.empty:

                st.error(
                    "Adicione pelo menos uma celebração."
                )

            else:

                obrigatorias = [
                    "Dia",
                    "Hora",
                    "Comunidade",
                    "Atividade",
                    "Presidente"
                ]

                if df_editado[
                    obrigatorias
                ].isnull().any().any():

                    df_editado = df_editado.fillna("")

                with st.spinner(
                    "Criando as imagens..."
                ):

                    imagens = gerar_carrossel(
                        df_editado,
                        mes,
                        int(ano),
                        cor_hex,
                        eventos_por_slide
                    )

                    arquivo_zip = gerar_zip(
                        imagens
                    )

                st.session_state[
                    "imagens_geradas"
                ] = imagens

                st.session_state[
                    "arquivo_zip"
                ] = arquivo_zip

                st.success(
                    f"Carrossel criado com "
                    f"{len(imagens)} imagens!"
                )

        # ----------------------------------------------------
        # RESULTADO
        # ----------------------------------------------------

        if "imagens_geradas" in st.session_state:

            st.divider()

            st.subheader("4. Visualizar carrossel")

            imagens = st.session_state[
                "imagens_geradas"
            ]

            col1, col2 = st.columns(2)

            with col1:

                st.metric(
                    "Total de imagens",
                    len(imagens)
                )

            with col2:

                st.metric(
                    "Resolução",
                    "1080 × 1350"
                )

            for indice, imagem in enumerate(imagens):

                with st.expander(
                    f"Imagem {indice + 1:02d}",
                    expanded=(indice == 0)
                ):

                    st.image(
                        imagem,
                        use_container_width=True
                    )

                    buffer = io.BytesIO()

                    imagem.save(
                        buffer,
                        format="PNG"
                    )

                    st.download_button(
                        label="Baixar esta imagem",
                        data=buffer.getvalue(),
                        file_name=(
                            f"escala_{indice + 1:02d}.png"
                        ),
                        mime="image/png",
                        key=f"download_{indice}"
                    )

            st.divider()

            st.download_button(
                label="Baixar carrossel completo (ZIP)",
                data=st.session_state["arquivo_zip"],
                file_name="carrossel_escalas.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True
            )

    else:

        st.warning(
            "Não foi possível identificar automaticamente "
            "as celebrações neste PDF."
        )

        st.info(
            "O PDF pode ser digitalizado como imagem ou "
            "utilizar uma estrutura diferente da esperada."
        )

        with st.expander(
            "Visualizar texto extraído para diagnóstico"
        ):

            st.text_area(
                "Texto encontrado no PDF",
                texto_bruto,
                height=350
            )

else:

    st.markdown(
        """
        ### Como utilizar

        1. Envie o PDF da escala.
        2. Confira e corrija os dados identificados.
        3. Escolha as cores e a quantidade de celebrações.
        4. Gere e baixe as imagens do carrossel.
        """
    )

    st.caption(
        "Desenvolvido para facilitar a divulgação "
        "das escalas de celebrações paroquiais."
    )

import streamlit as st
import pandas as pd
import pdfplumber
import zipfile
import io
import re
import unicodedata

from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


# ==========================================================
# CONFIGURAÇÕES
# ==========================================================

st.set_page_config(
    page_title="Gerador de Escalas",
    page_icon="⛪",
    layout="wide"
)

W, H = 1080, 1350

CREME = (253, 251, 247)
VERDE = (30, 86, 49)
VERDE_CLARO = (232, 245, 233)
BRANCO = (255, 255, 255)

MESES = [
    "Janeiro", "Fevereiro", "Março", "Abril",
    "Maio", "Junho", "Julho", "Agosto",
    "Setembro", "Outubro", "Novembro", "Dezembro"
]

# As larguras somam 980 px, que é a largura da tabela.
LARGURAS = [100, 430, 250, 200]


# ==========================================================
# FONTES
# ==========================================================

def localizar_fonte(negrito=False):
    """
    Procura uma fonte TrueType com suporte a português.
    Não usa ImageFont.load_default(), pois ela pode gerar
    texto minúsculo e problemas com caracteres acentuados.
    """

    nome = "DejaVuSans-Bold.ttf" if negrito else "DejaVuSans.ttf"

    pasta_projeto = Path(__file__).resolve().parent

    caminhos = [
        pasta_projeto / "fonts" / nome,
        pasta_projeto / nome,
        Path("C:/Windows/Fonts/arialbd.ttf" if negrito else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf" if negrito else "C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu") / nome,
        Path("/usr/share/fonts/dejavu") / nome,
        Path("/usr/share/fonts/truetype/liberation2") / (
            "LiberationSans-Bold.ttf" if negrito else "LiberationSans-Regular.ttf"
        ),
    ]

    for caminho in caminhos:
        try:
            if caminho.exists():
                return str(caminho)
        except OSError:
            continue

    raise FileNotFoundError(
        "Não encontrei uma fonte TrueType compatível. "
        "Coloque DejaVuSans.ttf e DejaVuSans-Bold.ttf "
        "na pasta 'fonts' junto do app.py."
    )


@st.cache_resource
def carregar_fonte(tamanho, negrito=False):
    return ImageFont.truetype(
        localizar_fonte(negrito),
        int(tamanho)
    )


def fonte(tamanho, negrito=False):
    return carregar_fonte(tamanho, negrito)


# ==========================================================
# TEXTO E MEDIDAS
# ==========================================================

def limpar(texto):
    return re.sub(r"\s+", " ", str(texto)).strip(" |;\t")


def normalizar(texto):
    texto = str(texto).strip().lower()
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caractere) != "Mn"
    )


def largura_texto(draw, texto, f):
    caixa = draw.textbbox((0, 0), str(texto), font=f)
    return caixa[2] - caixa[0]


def quebrar_linhas(draw, texto, f, limite):
    palavras = str(texto).split()
    linhas = []
    atual = ""

    for palavra in palavras:
        teste = f"{atual} {palavra}".strip()

        if largura_texto(draw, teste, f) <= limite:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra

    if atual:
        linhas.append(atual)

    return linhas or [""]


# ==========================================================
# IDENTIFICAÇÃO DOS DIAS
# ==========================================================

def identificar_dia(linha):
    padrao = (
        r"\b(DOMINGO|SEGUNDA(?:\s*[-–]?\s*FEIRA)?|"
        r"TERÇA(?:\s*[-–]?\s*FEIRA)?|"
        r"QUARTA(?:\s*[-–]?\s*FEIRA)?|"
        r"QUINTA(?:\s*[-–]?\s*FEIRA)?|"
        r"SEXTA(?:\s*[-–]?\s*FEIRA)?|SÁBADO)\b"
        r"\s*[-–]?\s*DIA\s*(\d{1,2})"
        r"(?:\s*[-–]\s*(.*))?"
    )

    resultado = re.search(padrao, linha, re.IGNORECASE)

    if not resultado:
        return None

    nome = limpar(resultado.group(1)).upper()
    numero = int(resultado.group(2))
    observacao = limpar(resultado.group(3) or "")

    nome = re.sub(r"\s*[-–]?\s*FEIRA$", " FEIRA", nome)
    titulo = f"{nome} – DIA {numero:02d}"

    if observacao:
        titulo += f" – {observacao}"

    return titulo


# ==========================================================
# IDENTIFICAÇÃO DOS EVENTOS
# ==========================================================

def identificar_horario(linha):
    resultado = re.match(
        r"^\s*(\d{1,2}\s*[hH]\s*\d{0,2}|\d{1,2}:\d{2})\b\s*(.*)",
        linha
    )

    if not resultado:
        return None, None

    hora = re.sub(r"\s+", "", resultado.group(1)).lower()
    hora = hora.replace(":", "h")

    return hora, limpar(resultado.group(2))


def identificar_presidente(texto):
    padrao = (
        r"\b(Pe\.?|Pé\.?|Padre|Sem\.?|Seminarista|"
        r"Diác\.?|Diácono|Dom)\s*"
        r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ].*$"
    )

    resultado = re.search(padrao, texto, re.IGNORECASE)

    if not resultado:
        return "", limpar(texto)

    presidente = limpar(texto[resultado.start():])
    restante = limpar(texto[:resultado.start()])

    return presidente, restante


ATIVIDADES = [
    "Adoração ao Santíssimo Sacramento",
    "Adoração ao Santíssimo",
    "Celebração da Palavra",
    "Missa e Novena",
    "Celebração Eucarística",
    "Missa (Normalistas)",
    "Missa",
    "Batizados",
    "Casamento",
    "Confissão",
    "Novena",
    "Terço",
    "Adoração"
]


def identificar_atividade(texto):
    texto_norm = normalizar(texto)

    for atividade in sorted(ATIVIDADES, key=len, reverse=True):
        atividade_norm = normalizar(atividade)
        posicao = texto_norm.find(atividade_norm)

        if posicao == -1:
            continue

        inicio = posicao
        fim = posicao + len(atividade)
        nome = texto[inicio:fim]

        restante = limpar(texto[:inicio] + " " + texto[fim:])

        complemento = re.match(r"^\s*(\([^)]*\))", restante)

        if complemento:
            nome += " " + complemento.group(1)
            restante = limpar(restante[complemento.end():])

        return limpar(nome), restante

    return "Missa", limpar(texto)


def processar_linha_evento(linha, dia):
    hora, restante = identificar_horario(linha)

    if not hora:
        return None

    presidente, restante = identificar_presidente(restante)
    atividade, comunidade = identificar_atividade(restante)

    return {
        "Dia": dia,
        "Hora": hora,
        "Comunidade": limpar(comunidade),
        "Atividade": limpar(atividade),
        "Presidente": limpar(presidente)
    }


# ==========================================================
# EXTRAÇÃO DO PDF
# ==========================================================

def extrair_pdf(arquivo):
    eventos = []
    texto_bruto = ""
    dia_atual = None
    ultimo_evento = None

    with pdfplumber.open(arquivo) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text(
                x_tolerance=3,
                y_tolerance=3
            )

            if not texto:
                continue

            texto_bruto += texto + "\n"

            for linha_original in texto.splitlines():
                linha = limpar(linha_original.replace("|", " "))

                if not linha:
                    continue

                dia = identificar_dia(linha)

                if dia:
                    dia_atual = dia
                    ultimo_evento = None
                    continue

                if re.search(
                    r"HORA\s+COMUNIDADE|"
                    r"PARÓQUIA NOSSA SENHORA|"
                    r"ARQUIDIOCESE|"
                    r"PRAÇA GETÚLIO|"
                    r"TELEFONE:|E-MAIL:",
                    linha,
                    re.IGNORECASE
                ):
                    continue

                if not dia_atual:
                    continue

                evento = processar_linha_evento(linha, dia_atual)

                if evento:
                    eventos.append(evento)
                    ultimo_evento = evento

                elif ultimo_evento:
                    presidente, restante = identificar_presidente(linha)

                    if presidente:
                        ultimo_evento["Presidente"] = presidente
                    elif "santissimo" in normalizar(
                        ultimo_evento["Atividade"]
                    ):
                        ultimo_evento["Atividade"] = limpar(
                            ultimo_evento["Atividade"] + " " + linha
                        )

    return pd.DataFrame(eventos, columns=[
        "Dia", "Hora", "Comunidade", "Atividade", "Presidente"
    ]), texto_bruto


# ==========================================================
# ALTURA DAS LINHAS E DOS DIAS
# ==========================================================

def altura_linha(evento, draw):
    f = fonte(22)

    textos = [
        evento["Hora"],
        evento["Comunidade"],
        evento["Atividade"],
        evento["Presidente"]
    ]

    quantidades = []

    for indice, texto in enumerate(textos):
        limite = LARGURAS[indice] - 30
        linhas = quebrar_linhas(
            draw,
            texto if texto else "-",
            f,
            limite
        )
        quantidades.append(len(linhas))

    return max(58, 24 + max(quantidades) * 29)


def altura_dia(dia, eventos, draw):
    altura_titulo = 65
    altura_cabecalho = 50
    espacamento = 38

    altura_eventos = sum(
        altura_linha(evento, draw)
        for evento in eventos
    )

    return (
        altura_titulo
        + altura_cabecalho
        + altura_eventos
        + espacamento
    )


# ==========================================================
# AGRUPAMENTO AUTOMÁTICO DOS DIAS
# ==========================================================

def agrupar_dias(df):
    draw = ImageDraw.Draw(Image.new("RGB", (W, H)))

    grupos = []

    for dia in df["Dia"].drop_duplicates():
        eventos = df[df["Dia"] == dia].to_dict("records")
        grupos.append((dia, eventos))

    paginas = []
    pagina_atual = []
    altura_atual = 90
    altura_disponivel = 1120

    for dia, eventos in grupos:
        altura = altura_dia(dia, eventos, draw)

        if pagina_atual and altura_atual + altura > altura_disponivel:
            paginas.append(pagina_atual)
            pagina_atual = []
            altura_atual = 90

        if altura > altura_disponivel:
            if pagina_atual:
                paginas.append(pagina_atual)
                pagina_atual = []
                altura_atual = 90

            bloco = []
            altura_bloco = 90

            for evento in eventos:
                altura_evento = altura_linha(evento, draw)

                if (
                    bloco
                    and altura_bloco + altura_evento + 115
                    > altura_disponivel
                ):
                    paginas.append([(dia, bloco)])
                    bloco = []
                    altura_bloco = 90

                bloco.append(evento)
                altura_bloco += altura_evento

            if bloco:
                pagina_atual = [(dia, bloco)]
                altura_atual = altura_dia(dia, bloco, draw)

        else:
            pagina_atual.append((dia, eventos))
            altura_atual += altura

    if pagina_atual:
        paginas.append(pagina_atual)

    return paginas


# ==========================================================
# DESENHO DAS CÉLULAS
# ==========================================================

def desenhar_celula(
    draw,
    x,
    y,
    largura,
    altura,
    texto,
    f,
    cor_texto,
    alinhamento="left"
):
    padding = 15

    linhas = quebrar_linhas(
        draw,
        str(texto) if texto else "-",
        f,
        largura - padding * 2
    )

    altura_texto = len(linhas) * 29
    y_texto = y + max(8, (altura - altura_texto) // 2)

    for linha in linhas:
        largura_linha = largura_texto(draw, linha, f)

        if alinhamento == "center":
            x_texto = x + (largura - largura_linha) // 2
        else:
            x_texto = x + padding

        draw.text(
            (x_texto, y_texto),
            linha,
            font=f,
            fill=cor_texto
        )

        y_texto += 29


# ==========================================================
# DESENHO DE CADA DIA
# ==========================================================

def desenhar_dia(draw, dia, eventos, y):
    x = 50
    largura_total = 980

    # Faixa do título
    altura_titulo = 65

    draw.rectangle(
        [x, y, x + largura_total, y + altura_titulo],
        fill=VERDE
    )

    f_titulo = fonte(28)
    largura_titulo = largura_texto(draw, dia, f_titulo)

    draw.text(
        (
            x + (largura_total - largura_titulo) // 2,
            y + 17
        ),
        dia,
        font=f_titulo,
        fill=BRANCO
    )

    y += altura_titulo

    # Cabeçalho das colunas
    altura_cabecalho = 50

    draw.rectangle(
        [x, y, x + largura_total, y + altura_cabecalho],
        fill=VERDE
    )

    cabecalhos = [
        "HORA", "COMUNIDADE", "ATIVIDADE", "PRESIDENTE"
    ]

    f_cabecalho = fonte(21)
    x_atual = x

    for indice, texto in enumerate(cabecalhos):
        desenhar_celula(
            draw,
            x_atual,
            y,
            LARGURAS[indice],
            altura_cabecalho,
            texto,
            f_cabecalho,
            BRANCO
        )
        x_atual += LARGURAS[indice]

    y += altura_cabecalho

    # Linhas dos eventos
    f_dados = fonte(22)

    for indice, evento in enumerate(eventos):
        altura = altura_linha(evento, draw)

        fundo = VERDE_CLARO if indice % 2 == 0 else BRANCO

        draw.rectangle(
            [x, y, x + largura_total, y + altura],
            fill=fundo
        )

        valores = [
            evento["Hora"],
            evento["Comunidade"],
            evento["Atividade"],
            evento["Presidente"]
        ]

        x_atual = x

        for coluna, valor in enumerate(valores):
            desenhar_celula(
                draw,
                x_atual,
                y,
                LARGURAS[coluna],
                altura,
                valor,
                f_dados,
                VERDE
            )
            x_atual += LARGURAS[coluna]

        y += altura

    return y + 38


# ==========================================================
# RODAPÉ
# ==========================================================

def desenhar_rodape(draw, mes, ano, numero, total):
    draw.text(
        (50, 1285),
        f"ESCALA DE MISSAS · {mes.upper()} DE {ano}",
        font=fonte(18),
        fill=VERDE
    )

    pagina = f"{numero:02d} / {total:02d}"
    f_pagina = fonte(17)
    largura = largura_texto(draw, pagina, f_pagina)

    draw.text(
        (1030 - largura, 1285),
        pagina,
        font=f_pagina,
        fill=VERDE
    )


# ==========================================================
# GERAÇÃO DAS IMAGENS
# ==========================================================

def gerar_imagens(df, mes, ano):
    paginas = agrupar_dias(df)
    imagens = []
    total = len(paginas)

    for indice, grupos in enumerate(paginas):
        imagem = Image.new("RGB", (W, H), CREME)
        draw = ImageDraw.Draw(imagem)

        y = 50

        for dia, eventos in grupos:
            y = desenhar_dia(draw, dia, eventos, y)

        desenhar_rodape(
            draw,
            mes,
            ano,
            indice + 1,
            total
        )

        imagens.append(imagem)

    return imagens


# ==========================================================
# EXPORTAÇÃO ZIP
# ==========================================================

def gerar_zip(imagens):
    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as zip_file:

        for indice, imagem in enumerate(imagens):
            arquivo = io.BytesIO()
            imagem.save(arquivo, format="PNG", optimize=True)

            zip_file.writestr(
                f"escala_{indice + 1:02d}.png",
                arquivo.getvalue()
            )

    buffer.seek(0)
    return buffer.getvalue()


# ==========================================================
# INTERFACE STREAMLIT
# ==========================================================

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1200px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    h1 {
        color: #1E5631;
        font-weight: 700;
        letter-spacing: -1px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("Gerador de Escalas")

st.caption(
    "Transforme a escala de celebrações em imagens "
    "prontas para publicar no Instagram."
)

with st.sidebar:
    st.header("Configurações")

    hoje = datetime.now()

    mes = st.selectbox(
        "Mês",
        MESES,
        index=hoje.month - 1
    )

    ano = st.number_input(
        "Ano",
        min_value=2020,
        max_value=2100,
        value=hoje.year
    )

    st.divider()
    st.caption("Formato: 1080 × 1350 pixels")
    st.caption("Identidade visual: verde e creme")


st.subheader("1. Enviar PDF")

arquivo_pdf = st.file_uploader(
    "Selecione a escala de celebrações",
    type=["pdf"]
)

if arquivo_pdf:
    try:
        with st.spinner("Analisando o documento..."):
            df, texto_bruto = extrair_pdf(arquivo_pdf)

        if df.empty:
            st.warning("Nenhuma celebração foi identificada.")
            st.text_area(
                "Texto extraído do PDF",
                texto_bruto,
                height=300
            )

        else:
            st.success(
                f"{len(df)} celebrações identificadas."
            )

            st.subheader("2. Conferir escala")

            df_editado = st.data_editor(
                df,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key="editor"
            )

            st.caption(
                "Confira nomes, horários e atividades antes "
                "de gerar as imagens. Você pode editar a tabela."
            )

            st.divider()
            st.subheader("3. Gerar carrossel")

            if st.button(
                "Gerar imagens",
                type="primary",
                use_container_width=True
            ):
                df_final = df_editado.copy().fillna("")

                df_final = df_final[
                    df_final["Dia"].astype(str).str.strip() != ""
                ]

                if df_final.empty:
                    st.error("Não existem celebrações para gerar.")
                else:
                    try:
                        with st.spinner("Montando as tabelas..."):
                            imagens = gerar_imagens(
                                df_final,
                                mes,
                                int(ano)
                            )

                            zip_data = gerar_zip(imagens)

                        st.session_state["imagens"] = imagens
                        st.session_state["zip"] = zip_data

                        st.success(
                            f"{len(imagens)} imagens geradas!"
                        )

                    except FileNotFoundError as erro:
                        st.error(str(erro))

            if "imagens" in st.session_state:
                st.divider()
                st.subheader("4. Visualização")

                imagens = st.session_state["imagens"]

                st.write(f"Total de slides: {len(imagens)}")

                for indice, imagem in enumerate(imagens):
                    with st.expander(
                        f"Slide {indice + 1}",
                        expanded=(indice == 0)
                    ):
                        st.image(
                            imagem,
                            use_container_width=True
                        )

                        buffer = io.BytesIO()
                        imagem.save(buffer, format="PNG")

                        st.download_button(
                            "Baixar imagem",
                            data=buffer.getvalue(),
                            file_name=f"escala_{indice + 1:02d}.png",
                            mime="image/png",
                            key=f"img_{indice}"
                        )

                st.download_button(
                    "Baixar carrossel completo (ZIP)",
                    data=st.session_state["zip"],
                    file_name="carrossel_escalas.zip",
                    mime="application/zip",
                    type="primary",
                    use_container_width=True
                )

    except Exception as erro:
        st.error(f"Erro durante o processamento: {erro}")

else:
    st.info(
        "Envie um PDF para começar a montar seu carrossel."
    )

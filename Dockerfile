FROM python:3.12

# System deps for Manim: LaTeX, cairo, pango, ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2-dev \
    libpango1.0-dev \
    libglib2.0-dev \
    pkg-config \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-science \
    dvipng \
    dvisvgm \
    ghostscript \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project
COPY . .

RUN mkdir -p papers output data

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Default: run the API server (used by Render/Docker deployments).
# To run the CLI instead: docker run ... python -m src.pipeline run paper.pdf
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}"]
